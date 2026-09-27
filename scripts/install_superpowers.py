#!/usr/bin/env python
"""
Utility script to download and install the complete Superpowers agentic skills framework
from obra/superpowers into the .bob workspace directory.
"""

import urllib.error
import urllib.request
from pathlib import Path

SKILLS = [
    "using-superpowers",
    "brainstorming",
    "writing-plans",
    "executing-plans",
    "systematic-debugging",
    "test-driven-development",
    "verification-before-completion",
    "finishing-a-development-branch",
    "subagent-driven-development",
    "dispatching-parallel-agents",
    "requesting-code-review",
    "receiving-code-review",
    "using-git-worktrees",
    "writing-skills",
    "diagnosing-superpowers"
]

BASE_URL = "https://raw.githubusercontent.com/obra/superpowers/main/skills/{}/SKILL.md"

def install_superpowers():
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
                url,
                headers={"User-Agent": "Mozilla/5.0 (IBM Bob Agent Installer)"}
            )
            
            with urllib.request.urlopen(req, timeout=10) as response:
                content = response.read().decode("utf-8")
                
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
