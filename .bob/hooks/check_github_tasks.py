import json
import os
import subprocess
import sys


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
        if res.returncode != 0 or not res.stdout.strip():
            sys.exit(0)

        open_prs = json.loads(res.stdout)
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

    if updates:
        context_msg = (
            "Recent GitHub updates/mentions for Bob on adaptive-market-engine:\n"
            + "\n".join(updates)
        )
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
