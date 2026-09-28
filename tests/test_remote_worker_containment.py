"""Opt-in real CLI tests against a loopback model fixture, never a paid endpoint."""

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from local_worker import SCHEMA, child_environment, command  # noqa: E402

CLI = os.environ.get("CODEX_TEST_EXECUTABLE")
pytestmark = pytest.mark.skipif(not CLI, reason="requires pinned disposable CLI; no real login")
CANARY = "DUMMY_AUTH_CANARY_791083_ONLY"
RESULT = {
    "number": 1,
    "head": "a" * 40,
    "verdict": "BLOCKED",
    "review": "Offline fixture only. Not a real PR review or authenticated deployment evidence.",
}


def probe(tmp_path, *, attack=False, enable_shell=False):
    assert CLI and Path(CLI).is_file()
    home, auth_home = tmp_path / "home", tmp_path / "codex"
    home.mkdir()
    auth_home.mkdir()
    auth = auth_home / "auth.json"
    auth.write_text(json.dumps({"OPENAI_API_KEY": CANARY}), encoding="utf-8")
    sentinel = tmp_path / "mcp-started"
    # A configured server must never launch under --ignore-user-config.
    mcp_args = ["-c", f"from pathlib import Path; Path({str(sentinel)!r}).touch()"]
    (auth_home / "config.toml").write_text(
        f"[mcp_servers.fixture]\ncommand = {json.dumps(sys.executable)}\n"
        f"args = {json.dumps(mcp_args)}\n",
        encoding="utf-8",
    )
    (tmp_path / "schema.json").write_text(json.dumps(SCHEMA), encoding="utf-8")
    requests = []
    headers = []
    attacks = [
        ("exec_command", {"cmd": f"cat {auth}"}),
        ("shell", {"command": ["cat", str(auth)]}),
        ("read_file", {"path": str(auth)}),
        ("exec", {"code": "await tools.exec_command({cmd:'echo DUMMY'});"}),
        ("browser", {"url": "http://127.0.0.1/"}),
        ("mcp__fixture__read_auth", {"path": str(auth)}),
    ]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            length = int(self.headers["Content-Length"])
            assert 0 < length < 2_000_000
            requests.append(json.loads(self.rfile.read(length)))
            headers.append(dict(self.headers))
            message = {
                "id": "msg_fixture",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": json.dumps(RESULT), "annotations": []}],
            }
            items = [message]
            if attack and len(requests) == 1:
                items = [
                    {
                        "type": "function_call",
                        "id": f"fc_{i}",
                        "call_id": f"call_{i}",
                        "name": name,
                        "arguments": json.dumps(arguments),
                        "status": "completed",
                    }
                    for i, (name, arguments) in enumerate(attacks)
                ]
            response = {
                "id": "resp_fixture",
                "object": "response",
                "status": "completed",
                "output": items,
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            }
            events = [
                {
                    "type": "response.created",
                    "response": {**response, "status": "in_progress", "output": []},
                },
                *[
                    {"type": "response.output_item.done", "output_index": i, "item": item}
                    for i, item in enumerate(items)
                ],
                {"type": "response.completed", "response": response},
            ]
            body = "".join("data: " + json.dumps(e) + "\n\n" for e in events).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    output = tmp_path / "result.json"
    args = command(CLI, tmp_path, output)
    settings = [
        'model_provider="fixture"',
        'model="fixture-model"',
        'model_providers.fixture.name="Offline fixture"',
        f'model_providers.fixture.base_url="http://127.0.0.1:{server.server_port}/v1"',
        'model_providers.fixture.wire_api="responses"',
        "model_providers.fixture.requires_openai_auth=false",
    ]
    if enable_shell:
        args[args.index("features.shell_tool=false")] = "features.shell_tool=true"
    args = args[:-1] + [item for setting in settings for item in ("-c", setting)] + ["-"]
    env = child_environment(os.environ)
    for key in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA"):
        env[key] = str(home)
    env["CODEX_HOME"] = str(auth_home)
    try:
        process = subprocess.run(
            args,
            input="Return the fixture JSON. This is a local protocol test.",
            text=True,
            encoding="utf-8",
            capture_output=True,
            env=env,
            timeout=40,
            check=False,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert process.returncode == 0, process.stderr[-2000:]
    assert requests and json.loads(output.read_text(encoding="utf-8")) == RESULT
    assert not sentinel.exists(), "CLI loaded ignored MCP configuration"
    assert CANARY not in json.dumps(requests) + json.dumps(headers)
    assert CANARY not in process.stdout + process.stderr + output.read_text(encoding="utf-8")
    return requests


def test_real_cli_rejects_hostile_tools_without_auth_disclosure(tmp_path):
    requests = probe(tmp_path, attack=True)
    for request in requests:
        assert {t.get("name", t["type"]) for t in request["tools"]} <= {"request_user_input"}
    results = [
        item
        for request in requests
        for item in request["input"]
        if item.get("type") == "function_call_output"
    ]
    assert len(results) == 6
    assert all("unsupported call:" in item["output"] for item in results)


def test_probe_detects_deliberately_enabled_shell(tmp_path):
    # Negative control: a broken command boundary must visibly advertise execution.
    requests = probe(tmp_path, enable_shell=True)
    tools = {t.get("name", t["type"]) for t in requests[0]["tools"]}
    assert tools - {"request_user_input"}, "probe could not distinguish enabled shell"
