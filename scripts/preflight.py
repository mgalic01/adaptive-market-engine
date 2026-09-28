"""Run offline, read-only checks before publishing changes; required CI still applies."""

from __future__ import annotations

import argparse
import os
import platform
import subprocess  # nosec B404
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# pyproject.toml's requires-python, and the only version CI runs. Evidence produced on
# an older interpreter is invalid; a newer one is useful but is not CI evidence.
FLOOR = (3, 12)


def interpreter_problem(version: tuple[int, ...]) -> str | None:
    """Why this interpreter cannot produce evidence, or None if it can."""
    if version[:2] < FLOOR:
        return (
            f"Python {'.'.join(map(str, version[:3]))} is below the project floor "
            f"{'.'.join(map(str, FLOOR))}; results from it are not evidence."
        )
    return None


def test_files(root: Path, selectors: list[str] | None) -> list[str]:
    """Validate all focused selectors before any check starts; accept test files only."""
    tests = (root / "tests").resolve()
    if not tests.is_relative_to(root):
        raise ValueError("tests directory must be inside this repository")
    if selectors is None:
        return ["tests"]
    if not selectors:
        raise ValueError("focused mode needs at least one test file")
    files = []
    for selector in selectors:
        path = Path(selector)
        if not selector.strip() or ".." in path.parts:
            raise ValueError(f"invalid test file: {selector!r}")
        resolved = (root / path).resolve()
        if (
            not resolved.is_relative_to(tests)
            or not resolved.is_file()
            or not resolved.name.startswith("test_")
            or resolved.suffix != ".py"
        ):
            raise ValueError(f"expected an existing test_*.py file under tests: {selector!r}")
        name = resolved.relative_to(root).as_posix()
        if name not in files:
            files.append(name)
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tests",
        nargs="+",
        metavar="TEST_FILE",
        help="explicit files under tests/; focused tests do not replace the full suite or CI",
    )
    args = parser.parse_args(argv)
    root = ROOT.resolve()
    try:
        selected = test_files(root, args.tests)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    version = tuple(int(part) for part in sys.version_info[:3])
    print(
        f"Interpreter: Python {platform.python_version()} ({sys.executable}) on "
        f"{platform.system()} {platform.release()}",
        flush=True,
    )
    problem = interpreter_problem(version)
    if problem:
        print(problem, file=sys.stderr, flush=True)
        return 2
    if version[:2] > FLOOR:
        print(
            f"Note: CI runs Python {'.'.join(map(str, FLOOR))}; a pass here is not CI evidence.",
            flush=True,
        )
    focused = args.tests is not None
    print(
        "FOCUSED PREFLIGHT: selected test files only; this is NOT the full suite or full CI."
        if focused
        else "Preflight: lint, format, types, security, reports and the full pytest suite.",
        flush=True,
    )
    env = os.environ.copy()
    # Pin this checkout even if the interpreter's editable install points elsewhere.
    env["PYTHONPATH"] = str(root / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    # Inherited pytest overrides could quietly omit tests or load unrelated plugins.
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("PYTEST_PLUGINS", None)
    python = [sys.executable, "-B"]
    steps = [
        ("Lint", [*python, "-m", "ruff", "check", "--no-fix", "--no-cache", "."]),
        ("Format check", [*python, "-m", "ruff", "format", "--check", "--no-cache", "."]),
        # The same type and security checks CI runs, over the same paths.
        ("Type check", [*python, "-m", "mypy", "src", "scripts"]),
        ("Security scan", [*python, "-m", "bandit", "-q", "-r", "src", "scripts"]),
        ("Report checks", [*python, "scripts/check_reports.py"]),
        (
            "Focused pytest" if focused else "Full pytest",
            [*python, "-m", "pytest", "-p", "no:cacheprovider", "--", *selected],
        ),
    ]
    for label, command in steps:
        print(f"\n{label}: {' '.join(command)}", flush=True)
        try:
            # Commands are fixed; user input reaches only validated file arguments.
            result = subprocess.run(  # nosec B603
                command, cwd=root, env=env, check=False, shell=False
            )
        except OSError as exc:
            print(f"{label} could not start: {exc}", file=sys.stderr, flush=True)
            return 1
        if result.returncode:
            print(
                f"{label} FAILED (exit {result.returncode}); stopping.", file=sys.stderr, flush=True
            )
            return result.returncode if result.returncode > 0 else 1
    print(
        "Focused preflight passed; full-suite validation and required CI remain necessary."
        if focused
        else "Preflight passed (full pytest suite); required CI remains necessary.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
