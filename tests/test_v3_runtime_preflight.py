"""Synthetic repositories and isolated interpreters only; no market inputs."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_trial_register import candidate, completion, encode

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PYTHON = os.environ.get("V3_PREFLIGHT_TEST_PYTHON", sys.executable)


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args]).decode().strip()


@pytest.fixture
def registered(tmp_path):
    from trial_register import code_digest

    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.name", "Synthetic")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "core.autocrlf", "false")
    blobs = {"docs/spec.md": b"spec\n", "config/run.json": b"{}\n", "config/manifest.json": b"{}\n"}
    for name, raw in blobs.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(raw)
    git(root, "add", ".")
    git(root, "commit", "-qm", "spec")
    reg = candidate()
    reg["payload"]["spec"].update(
        commit=git(root, "rev-parse", "HEAD"), sha256=hashlib.sha256(b"spec\n").hexdigest()
    )
    register = root / "docs/trials/register.jsonl"
    register.parent.mkdir()
    register.write_bytes(encode(reg))
    git(root, "add", ".")
    git(root, "commit", "-qm", "register")
    implementation = {
        "scripts/v3_runtime_preflight.py": (ROOT / "scripts/v3_runtime_preflight.py").read_bytes(),
        "scripts/trial_register.py": (ROOT / "scripts/trial_register.py").read_bytes(),
        "src/crypto_grid_bot/__init__.py": b"VALUE = 1\n",
        "scripts/helper.py": b"VALUE = 1\n",
        "scripts/byte_identity_baseline.json": b'{"fixture":1}\n',
        "pyproject.toml": b"# synthetic\n",
        "src/fixture.bin": b"\x00\n",
    }
    for name, raw in implementation.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(raw)
    git(root, "add", ".")
    git(root, "commit", "-qm", "implementation")
    done = completion()
    done["payload"].update(
        code_commit=git(root, "rev-parse", "HEAD"),
        code_paths=sorted(implementation),
        code_sha256=code_digest(implementation),
    )
    for name in ("config", "manifest"):
        done["payload"][name]["sha256"] = hashlib.sha256(b"{}\n").hexdigest()
    register.write_bytes(encode(reg, done))
    git(root, "add", ".")
    git(root, "commit", "-qm", "complete")
    return root, git(root, "rev-parse", "HEAD")


def run(registered, before="", after="", isolated=True, no_site=True):
    root, revision = registered
    code = f"""
import sys
import importlib.util
from pathlib import Path
root = Path({str(root)!r})
spec = importlib.util.spec_from_file_location(
    'v3_runtime_preflight', root / 'scripts/v3_runtime_preflight.py')
runtime = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runtime
spec.loader.exec_module(runtime)
{before}
snapshot = runtime.preflight_runtime(root, 'v3', {revision!r})
import helper, crypto_grid_bot
{after}
runtime.recheck_runtime(snapshot)
print('PREFLIGHT_OK')
"""
    return subprocess.run(
        [
            RUNTIME_PYTHON,
            *(["-I"] if isolated else []),
            *(["-S"] if no_site else []),
            "-B",
            "-c",
            code,
        ],
        capture_output=True,
        text=True,
    )


def test_valid_and_crlf(registered):
    root, _ = registered
    for name in ("scripts/helper.py", "pyproject.toml"):
        p = root / name
        p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
    (root / "notes.txt").write_text("unrelated")
    done = json.loads((root / "docs/trials/register.jsonl").read_text().splitlines()[-1])
    result = run(
        registered, after=f"assert snapshot.code_sha256 == {done['payload']['code_sha256']!r}"
    )
    assert result.returncode == 0, result.stderr
    assert "PREFLIGHT_OK" in result.stdout


@pytest.mark.parametrize(
    "damage", ["dirty", "missing", "staged", "assume", "skip", "binary", "head"]
)
def test_checkout_mismatch(registered, damage):
    root, _ = registered
    p = root / "scripts/helper.py"
    old = p.stat()
    if damage in ("assume", "skip"):
        git(
            root,
            "update-index",
            "--assume-unchanged" if damage == "assume" else "--skip-worktree",
            "scripts/helper.py",
        )
    if damage == "missing":
        p.unlink()
    elif damage == "binary":
        (root / "src/fixture.bin").write_bytes(b"\x00\r\n")
    else:
        p.write_bytes(b"VALUE = 2\n")
        if damage not in ("staged", "head"):
            os.utime(p, ns=(old.st_atime_ns, old.st_mtime_ns))
    if damage in ("staged", "head"):
        git(root, "add", ".")
        if damage == "staged":
            p.write_bytes(b"VALUE = 1\n")
        else:
            git(root, "commit", "-qm", "different")
    result = run(registered)
    assert result.returncode != 0
    assert "ValueError" in result.stderr and "PREFLIGHT_OK" not in result.stdout


@pytest.mark.parametrize(
    "name",
    [
        "scripts/json.py",
        "src/crypto_grid_bot/extra.py",
        "scripts/helper.pyc",
        "scripts/native.pyd",
        "scripts/__pycache__/helper.cpython-312.pyc",
    ],
)
def test_shadowing_even_ignored(registered, name):
    root, _ = registered
    (root / ".gitignore").write_text("*.pyc\n*.pyd\nextra.py\njson.py\n")
    p = root / name
    p.parent.mkdir(exist_ok=True)
    p.write_bytes(b"shadow")
    result = run(registered)
    assert result.returncode != 0 and "ValueError" in result.stderr


@pytest.mark.parametrize(
    "after",
    [
        "helper.__file__ = str(root.parent / 'foreign.py')",
        "helper.__spec__.origin = str(root.parent / 'foreign.py')",
        "helper.__spec__.loader = None",
        "helper.__spec__.loader.path = str(root.parent / 'foreign.py')",
        "crypto_grid_bot.__path__ = [str(root.parent)]",
        "(root / 'scripts/helper.py').write_bytes(b'VALUE = 2\\n')",
    ],
)
def test_origin_and_recheck_failures(registered, after):
    result = run(registered, after=after)
    assert result.returncode != 0 and "ValueError" in result.stderr
    assert "PREFLIGHT_OK" not in result.stdout


def test_requires_isolated_start(registered):
    result = run(registered, isolated=False)
    assert result.returncode != 0 and "isolated" in result.stderr


def test_requires_no_site_startup(registered):
    result = run(registered, no_site=False)
    assert result.returncode != 0 and "-S" in result.stderr


def test_foreign_preloaded_module(registered):
    result = run(
        registered, before="import types; sys.modules['helper'] = types.ModuleType('helper')"
    )
    assert result.returncode != 0 and "ValueError" in result.stderr


def test_source_symlink(registered):
    root, _ = registered
    p = root / "scripts/helper.py"
    foreign = root.parent / "foreign.py"
    foreign.write_bytes(p.read_bytes())
    p.unlink()
    try:
        p.symlink_to(foreign)
    except OSError:
        pytest.skip("symlink creation unavailable")
    result = run(registered)
    assert result.returncode != 0 and "ValueError" in result.stderr


def test_parent_junction(registered):
    if os.name != "nt":
        pytest.skip("Windows junction fixture")
    root, _ = registered
    package = root / "src/crypto_grid_bot"
    foreign = root.parent / "foreign_package"
    package.rename(foreign)
    # One native shell creates a link, never removes or moves a computed tree.
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(package), str(foreign)], capture_output=True
    )
    if result.returncode:
        pytest.skip("junction creation unavailable")
    result = run(registered)
    assert result.returncode != 0 and "redirected path" in result.stderr


def test_wrong_root(registered):
    result = run(registered, before="root = root / 'scripts'")
    assert result.returncode != 0 and "root mismatch" in result.stderr


def test_recheck_head_change(registered):
    result = run(registered, after="runtime._git(root, 'checkout', '--detach', 'HEAD^')")
    assert result.returncode != 0 and "HEAD mismatch" in result.stderr


@pytest.mark.parametrize("raw", [b" VALUE = 1\n", b"VALUE = 1\n\n", b"VALUE = 1\r"])
def test_no_other_whitespace_normalization(registered, raw):
    root, _ = registered
    (root / "scripts/helper.py").write_bytes(raw)
    result = run(registered)
    assert result.returncode != 0 and "working file mismatch" in result.stderr


def test_stdlib_shadow_never_executes(registered):
    root, _ = registered
    sentinel = root / "executed.txt"
    (root / "scripts/hashlib.py").write_text(
        f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('bad')\n"
    )
    result = run(registered)
    assert result.returncode != 0
    assert not sentinel.exists()


def test_preloaded_local_project_module_rejected(registered):
    result = run(registered, before="sys.path.insert(0, str(root / 'scripts')); import helper")
    assert result.returncode != 0 and "preloaded" in result.stderr


@pytest.mark.parametrize("edit", [False, True])
def test_known_json_checkout_line_endings_only(registered, edit):
    root, _ = registered
    path = root / "scripts/byte_identity_baseline.json"
    raw = path.read_bytes().replace(b"\n", b"\r\n")
    path.write_bytes(raw.replace(b":1", b":2") if edit else raw)
    result = run(registered)
    if edit:
        assert result.returncode != 0 and "working file mismatch" in result.stderr
    else:
        assert result.returncode == 0, result.stderr


def test_incomplete_committed_registration(registered):
    root, _ = registered
    path = root / "docs/trials/register.jsonl"
    path.write_bytes(path.read_bytes().splitlines()[0] + b"\n")
    git(root, "add", ".")
    git(root, "commit", "-qm", "without completion")
    result = run((root, git(root, "rev-parse", "HEAD")))
    assert result.returncode != 0 and "one committed completion required" in result.stderr
