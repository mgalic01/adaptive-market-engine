# Claude: agent-loop check after the move to Kali Linux

Index: 2026-11-08. The owner's PC was reinstalled and work moved to Kali Linux. This note records the state found on return, the loop test (Bob, Codex Cloud, the automated review, claims, CI), the docs changed for Linux, and why V4 step 5 restarts from a new B.

Written by Claude Code (session c5f98f3b). The state below was found on `main` at `c45f284`.

## State found

- No open PRs. The last merged PR is #301 (2026-10-24, the V4 step-5 plan).
- All 13 workflows are active. The last runs on 2026-10-24 succeeded.
- On #301, Bob answered `NO ISSUES` and the automated review `APPROVE`. Codex Cloud's review showed "running" for over two hours and was waived for #301 only.
- `python scripts/check_reports.py` reports 0 problems.
- The two old Windows worktree copies on the backup drive (`v4-registration-wt`, `v4-step5-wt`) equal `main` apart from CRLF line endings, so they hold no unpushed work. The old main repository on `C:` is gone, so commits that existed only there cannot be checked.
- V4 step 5 had started: data run 40122823348 succeeded at `c45f284`, and step 2 had not started. The freeze held; `main` had not moved.
- The owner confirmed that the other disks were formatted on purpose, so `F:`'s copies are gone.

## Linux notes

- `.bob/hooks/check_github_tasks.py` runs `python`, which Kali only provides inside the project's virtual environment (`.venv`).
- `scripts/claims.py` read `GITHUB_TOKEN` from the Windows registry. On Linux it needs the `GITHUB_TOKEN` environment variable.
- Python here is 3.14; the project targets 3.12. A single-core run reached about 75% of the tests with no failure before it was stopped for heat; the rest is unchecked.

## The loop test, at head `f6852e3`

- Bob answered `NO ISSUES`, Codex Cloud completed with no findings, the automated review posted `APPROVE`, and `claim-guard` was green.
- `test-and-audit` failed only on `pip-audit` (CVE-2026-114613 in `msgpack` 1.2.2); pytest passed, with 8710 passed and 4 skipped. PR #303 fixed it. The owner gave the go to merge and repeat the checks.
- Not tested: Codex Desktop on Kali and the separate local reviewer.

## A corrupted file on the PC

The first clone's pack file failed `git verify-pack` (`inflate returned -3`), and its content no longer matched the checksum in its own trailer. The bytes read back the same each time, so the damage was stored on disk. The kernel logged no I/O error and the system disk's SMART check passed. A new clone verified clean, the pack was replaced from it, `git fsck --full` then passed, and every working file matched. The cause is unknown; the RAM is untested. The registered run does not depend on this PC, but the copies of its results do, so the plan now says to check each copy after writing it.

## The runs repeated on the final code, 2026-11-09

PR #304 (100 USDT, v4-d30, and the runner pin) merged at `5e3ed10`. On that commit, rehearsal 42581586528 and timing run 42583987899 both succeeded on the pinned `ubuntu-24.04` machines, and every timing number is inside its limit. Both are archived on the BACKUPS disk: each zip equals GitHub's digest and `sha256sum -c SHA256SUMS.txt` passed after writing. The 221 copied artifacts were then deleted from GitHub, under the owner's decision of 2026-11-08. The timing run's other 133 artifacts are synthetic, were not copied, and expire by themselves on 2026-11-10.

A first artifact count of the rehearsal, 390 MB, read only GitHub's first page of 100. The real total is 578 MB. The status board was corrected, and the numbers in this PR come from the full listing.

## Bob's review of `3579448`, and what changed

Bob flagged six points, all text fixes that leave the pass rule and the verdict alone. All six are fixed:

1. Step 2's `sizes` said two capitals. It now says `[100, 1000, 10000]`.
2. Step 2's `sources` named the old rehearsal and timing run. It now names 42581586528 and 42583987899.
3. Step 12b said about 102 artifacts. A registered run uploads 150: 1 data, 1 v3-pack, 1 picks, 66 cells, 6 v3 cells, 72 summaries, and the verdict, analysis and status artifacts.
4. The plan said only that `gh` means "the same call". It now has a table of the REST calls, with the bodies of the dispatch and the merge. The downloader's text is below, because it can't be in `scripts/`. It also says which Python step 5's checks use, and that CI's check on 3.12 governs.
5. The check of the only copy could read from memory rather than the disk. Step 12c now unmounts and mounts first. This session's own checks of the two archives had that same weakness, and GitHub's copies were deleted after them. The checks were repeated after a remount and passed, and these archives hold only synthetic data.
6. The run archive still offered to delete the timing run's uncopied artifacts. It now says they expire.

The automated review's optional note on step 0's F: backup line is fixed too.

## Bob's review of `b917221`, and what changed

Bob confirmed the six fixes and the downloader, and flagged five more points. All five are fixed:

1. The REST table had no call for a data run's state or for reading the pins from a job's log. It has both now, and the "sent once" paragraph says to wait before reading the run list.
2. Step 12f deleted the data runs' artifacts under conditions that covered only the registered run's, while step 1 still "offered" that deletion. Both now say the data runs' artifacts are not downloaded, because the pack is kept as the registered run's `v4-data`.
3. Nothing compared the archive with GitHub's listing, or said where the ids to delete come from or when the download starts. Steps 12b, 12c and 12f now do, and a re-run's late artifacts get a second folder.
4. "About 60 MB more for the six v3 cells" in the analysis was wrong: the analysis downloads only `v4-cell-*`, the 66 non-v3 cells. The sentence is gone.
5. Step 6 had no path for a new security advisory during the freeze. It now has one: the PR stops and goes to the owner.

## Owner decisions of 2026-11-09

- **v4-d31:** a V4 pass approves nothing at EUR 100. Moving forward at that size takes a separate owner decision, made on the reported 100 USDT numbers.
- Codex Desktop and the local reviewer are not set up on Kali for now. The cloud reviewers carry the work.

## What this PR changes

Documents only, before the new B: this note, the step-5 plan's amendment and its counts and times, the run archive's Kali section and the new runs, v4-d31 in the V4 spec, and short corrections in `START_HERE`, `AGENT_HANDOFF` and `LOCAL_WORKER`. Nothing under `src/`, `scripts/`, `tests/`, `.github/` or `config/` changes. The spec is pinned at the new B, so v4-d31 has to land here.

## The downloader

`/mnt/backups/v4-run-42581586528/scripts/fetch_v4_cells.py`, the REST-API variant of the earlier archives' script. Its SHA-256 is `01d0225588836b0967d81544a6eeac2c7860a99eb9d6607686932435d3d01f4c`. It downloaded both archives above. Its full text:

```text
"""Download the artifacts of a v4-run to a new folder, verify each zip against GitHub's digest,
unpack it, and seal the folder.

Usage: GITHUB_TOKEN=... python -I fetch_v4_cells.py RUN_ID DEST [NAME_PREFIX]

The REST-API variant of the rehearsal's fetch_v4_cells.py, for a PC without `gh`. With NAME_PREFIX,
only the artifacts whose name starts with it are taken (a timing download: v4-timing-).

DEST must not exist. It receives:
- zips/<artifact>.zip, each checked against the artifact's GitHub digest (sha256:...);
- <artifact>/, each zip unpacked (members with an absolute path or ".." are refused);
- meta/artifacts.json: per artifact its id, size, GitHub digest and the zip's SHA-256;
- scripts/: a copy of this script;
- SHA256SUMS.txt: every file's SHA-256 (verify with `sha256sum -c SHA256SUMS.txt`).

It prints names, counts and sizes only, never a result, and never the token.
"""

import hashlib
import json
import os
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = "mgalic01/adaptive-market-engine"
API = "https://api.github.com"
CHUNK = 1 << 20


class _NoAuthOnRedirect(urllib.request.HTTPRedirectHandler):
    """GitHub redirects a zip download to blob storage, which must not receive the token."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            new.remove_header("Authorization")
        return new


OPENER = urllib.request.build_opener(_NoAuthOnRedirect)


def request(path: str) -> urllib.request.Request:
    return urllib.request.Request(
        f"{API}/{path}",
        headers={
            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "v4-archive",
        },
    )


def api_json(path: str) -> dict:
    with OPENER.open(request(path), timeout=120) as response:
        return json.load(response)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def artifacts(run: str) -> list[dict]:
    found: list[dict] = []
    page = 1
    while True:
        listing = api_json(f"repos/{REPO}/actions/runs/{run}/artifacts?per_page=100&page={page}")
        found += listing["artifacts"]
        if len(found) >= listing["total_count"] or not listing["artifacts"]:
            return found
        page += 1


def main() -> None:
    run, dest = sys.argv[1], Path(sys.argv[2])
    prefix = sys.argv[3] if len(sys.argv) > 3 else ""
    if not run.isdigit():
        sys.exit("RUN_ID must be digits")
    listed = [a for a in artifacts(run) if a["name"].startswith(prefix)]
    if not listed:
        sys.exit("no artifact matches")
    expired = [a["name"] for a in listed if a["expired"]]
    if expired:
        sys.exit(f"{len(expired)} artifacts have expired: {', '.join(sorted(expired))}")
    dest.mkdir(parents=False, exist_ok=False)
    (dest / "zips").mkdir()
    (dest / "meta").mkdir()
    (dest / "scripts").mkdir()
    record = {}
    for art in sorted(listed, key=lambda a: a["name"]):
        name = art["name"]
        if "/" in name or "\\" in name or name.startswith("."):
            sys.exit(f"unsafe artifact name {name!r}")
        zip_path = dest / "zips" / f"{name}.zip"
        with OPENER.open(
            request(f"repos/{REPO}/actions/artifacts/{art['id']}/zip"), timeout=600
        ) as response, zip_path.open("xb") as out:
            shutil.copyfileobj(response, out, CHUNK)
        got = sha256_file(zip_path)
        if "sha256:" + got != art["digest"]:
            sys.exit(f"{name}: the zip's SHA-256 is not GitHub's digest")
        target = dest / name
        target.mkdir()
        with zipfile.ZipFile(zip_path) as archive:
            members = archive.namelist()
            for member in members:
                if member.startswith(("/", "\\")) or ".." in Path(member).parts or ":" in member:
                    sys.exit(f"{name}: unsafe member in the zip")
            archive.extractall(target)
        record[name] = {
            "id": art["id"],
            "size_in_bytes": art["size_in_bytes"],
            "github_digest": art["digest"],
            "zip_sha256": got,
            "files": len(members),
        }
        print(f"{name}: {art['size_in_bytes']} bytes, digest verified, {len(members)} files", flush=True)
    with (dest / "meta" / "artifacts.json").open("x", encoding="utf-8") as out:
        json.dump({"run": run, "prefix": prefix, "artifacts": record}, out, indent=2, sort_keys=True)
    shutil.copy2(Path(__file__), dest / "scripts" / Path(__file__).name)
    lines = []
    for path in sorted(p for p in dest.rglob("*") if p.is_file() and p.name != "SHA256SUMS.txt"):
        lines.append(f"{sha256_file(path)}  {path.relative_to(dest).as_posix()}")
    with (dest / "SHA256SUMS.txt").open("x", encoding="utf-8", newline="\n") as out:
        out.write("\n".join(lines) + "\n")
    print(f"{len(record)} artifacts; SHA256SUMS.txt: {len(lines)} files", flush=True)


if __name__ == "__main__":
    main()
```
