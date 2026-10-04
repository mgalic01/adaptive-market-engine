#!/usr/bin/env python
"""
Utility script to download and install the complete Superpowers agentic skills framework
from obra/superpowers into the .bob workspace directory.
"""

import hashlib
import urllib.error
import urllib.request
from pathlib import Path

# Skill files are agent instructions, so they are pinned: one upstream commit, and the
# SHA-256 of each file's bytes at that commit (the vendored .bob/skills copies are
# identical to it). To update, review the upstream diff, then change COMMIT and every
# hash together.
COMMIT = "8ca22dba9a94f28898bbce59f2537ff4d87c747d"  # main on 2026-09-25, "Release v6.4.2"
SKILLS = {
    "using-superpowers": "82c5c8866ad7f5dd4440ce66bd7806ba48a2f13771beae5cf112e53f08fe36ba",
    "brainstorming": "a32d2255354775aa124855aa7100cf276bea096fff4ebb3a0edf57be216e6c72",
    "writing-plans": "a6c67c1900064347c2a329990dd3c555657c51c3ec53b259a08aa01a2c26139a",
    "executing-plans": "f38e8f2ddcf079f65493adc713c1fed78421dfaf5f4dbf6b3a6b2b1d95466e71",
    "systematic-debugging": "808fc5717aa88ad65efff312b11c186294d3e6ee301afb584e2f86599b137787",
    "test-driven-development": "64b03fce4aee5a97a93160cea8111f3ba13a17b7c001db4bd5836d67fd10705d",
    "verification-before-completion": (
        "2befe7fc55bcadaa3d97dd9e8efeb633d2561c0ebe74c5a8b17c4d9e7e4520b3"
    ),
    "finishing-a-development-branch": (
        "8db5a922b242dd4e1bf824cb91c13b3e8d8e8a86d6ceaf7f0774eb9cce909d65"
    ),
    "subagent-driven-development": (
        "8dde5589ee083fb4999106d116f01c8fdaf3116a8a9813fdedeb80329de49046"
    ),
    "dispatching-parallel-agents": (
        "1968923066f3b707eb01d1992cdf4c42284c3855f70253b9cd5000ff45fca13c"
    ),
    "requesting-code-review": "cfcee1b06774e7c0517f1e09be1a11f2d5680257072723e709ddbcf7e08b795a",
    "receiving-code-review": "091df1629510af1b92fc4abd6f96732ebedb4cb2c0f3457e8f2740b0504a2438",
    "using-git-worktrees": "8cfb86f121269e8f7f12361e6795c4f6738828340e28964c9229d365666c9edd",
    "writing-skills": "bbdfe742f853562e643a3d40d64476359d47881e39cef80a189283fa26d11ab9",
    "diagnosing-superpowers": "5a652f8132cc901eb5ca61f89157839f87a2f20aed037fc7a2b51051bc37cd19",
}

BASE_URL = "https://raw.githubusercontent.com/obra/superpowers/" + COMMIT + "/skills/{}/SKILL.md"


def install_superpowers() -> None:
    workspace_root = Path(__file__).resolve().parent.parent
    bob_skills_dir = workspace_root / ".bob" / "skills"

    print(f"[*] Starting installation of Superpowers into workspace: {workspace_root}")
    print(f"[*] Destination directory: {bob_skills_dir}")

    # Create the skills directory if it doesn't exist
    bob_skills_dir.mkdir(parents=True, exist_ok=True)

    installed_count = 0
    failed_count = 0

    for skill in SKILLS:
        skill_dir = bob_skills_dir / skill
        skill_file = skill_dir / "SKILL.md"
        url = BASE_URL.format(skill)

        print(f"[-] Downloading {skill}...", end="", flush=True)

        try:
            # Add a user-agent to avoid potential GitHub blocks
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0 (IBM Bob Agent Installer)"}
            )

            # Fixed HTTPS host and literal skill list; no user-selected URL scheme.
            with urllib.request.urlopen(req, timeout=10) as response:  # nosec B310
                data = response.read()

            # Refuse anything but the pinned bytes; the existing file stays untouched.
            if hashlib.sha256(data).hexdigest() != SKILLS[skill]:
                print(" FAILED (SHA-256 mismatch)")
                failed_count += 1
                continue
            content = data.decode("utf-8")

            # Create directory for individual skill
            skill_dir.mkdir(parents=True, exist_ok=True)

            # Write content
            with open(skill_file, "w", encoding="utf-8") as f:
                f.write(content)

            print(" SUCCESS")
            installed_count += 1

        except urllib.error.HTTPError as e:
            print(f" FAILED (HTTP {e.code})")
            failed_count += 1
        except Exception as e:
            print(f" FAILED ({str(e)})")
            failed_count += 1

    print("\n[+] Installation summary:")
    print(f"    - Total skills: {len(SKILLS)}")
    print(f"    - Successfully installed: {installed_count}")
    print(f"    - Failed: {failed_count}")

    if installed_count == len(SKILLS):
        print("\n[OK] All Superpowers skills successfully installed!")
    else:
        print("\n[WARN] Installation completed with some issues. Check the failures.")


if __name__ == "__main__":
    install_superpowers()
