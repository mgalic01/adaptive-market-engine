import json
import os
import subprocess
import sys


def claims_summary():
    """Active claims on open PRs (docs/AGENT_HANDOFF.md, "Claims"). Unknown is said out loud."""
    script = os.path.join("scripts", "claims.py")
    check = 'python scripts/claims.py check <PR> --as "[Bob]"'
    if not os.path.exists(script):
        return f"Claims: scripts/claims.py is not in this checkout; run `{check}` from main."
    try:
        res = subprocess.run(
            [sys.executable, script, "status"], capture_output=True, text=True, timeout=60
        )
    except Exception:
        res = None
    if res is None or res.returncode != 0:
        return f"Claims: UNKNOWN (could not be read). Run `{check}` before any push or merge."
    held = [line for line in res.stdout.splitlines() if "claimed by" in line]
    rule = (
        f"Before a push or merge on a PR run `{check}`. Exit 1 means another holder has "
        "it: do not push or merge, comment on the PR instead."
    )
    if not held:
        return "Claims: no active claim on any open PR. " + rule
    return "Claims (another holder's PR: no push, no merge):\n" + "\n".join(held) + "\n" + rule


def fetch_latest_pr_updates():
    # Only run in adaptive-market-engine repository directory
    if not (os.path.exists("src/crypto_grid_bot") and os.path.exists("docs/AGENT_HANDOFF.md")):
        sys.exit(0)

    repo = "mgalic01/adaptive-market-engine"
    updates = []
    try:
        # Use gh CLI via subprocess (handles GitHub auth for private repositories)
        cmd = [
            "gh",
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--json",
            "number",
            "--limit",
            "10",
        ]
        # Clear any invalid GITHUB_TOKEN environment variable so gh uses stored token/gh auth
        env = os.environ.copy()
        if "GITHUB_TOKEN" in env:
            del env["GITHUB_TOKEN"]

        res = subprocess.run(cmd, capture_output=True, text=True, timeout=8, env=env)
        # Without gh, still fall through to the claims summary below.
        ok = res.returncode == 0 and res.stdout.strip()
        open_prs = json.loads(res.stdout) if ok else []
        for pr in open_prs:
            pr_num = pr.get("number")
            comments_cmd = [
                "gh",
                "pr",
                "view",
                str(pr_num),
                "--repo",
                repo,
                "--comments",
                "--json",
                "comments",
            ]
            res_c = subprocess.run(comments_cmd, capture_output=True, text=True, timeout=8, env=env)
            if res_c.returncode == 0 and res_c.stdout.strip():
                data = json.loads(res_c.stdout)
                comments = data.get("comments", [])
                for c in reversed(comments):
                    body = c.get("body", "")
                    author = c.get("author", {}).get("login", "")
                    created_at = c.get("createdAt", "")
                    if "@bob" in body.lower() or "bob" in body.lower() or "handoff" in body.lower():
                        preview = body.strip().replace("\r\n", "\n")
                        if len(preview) > 300:
                            preview = preview[:300] + "..."
                        updates.append(f"- [PR #{pr_num}] {author} at {created_at}:\n  {preview}")
                        break
    except Exception:
        pass

    parts = []
    if updates:
        parts.append(
            "Recent GitHub updates/mentions for Bob on adaptive-market-engine:\n"
            + "\n".join(updates)
        )
    parts.append(claims_summary())
    if parts:
        context_msg = "\n\n".join(parts)
        output = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context_msg,
            }
        }
        sys.stdout.write(json.dumps(output))
    sys.exit(0)


if __name__ == "__main__":
    fetch_latest_pr_updates()
