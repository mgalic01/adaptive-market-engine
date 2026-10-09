"""Offline checkout/import drift checks, not authorization or a security sandbox.

Trusted future launcher: start fresh with Python -I -S -B; load this module with
importlib.util.spec_from_file_location, registering it in sys.modules under
v3_runtime_preflight before exec_module. Do not add any checkout path to sys.path
before preflight. Then call preflight, import project dependencies,
then recheck before any separately authorized data access/dispatch/publication.
The interpreter and this checker are trusted; memory mutation and TOCTOU remain.
"""

import hashlib
import importlib
import importlib.machinery
import os
import re
import subprocess  # nosec B404
import sys
from dataclasses import dataclass
from pathlib import Path

_METADATA = {"pyproject.toml", "requirements.txt", "requirements-dev.lock"}
_CHECKOUT_TEXT = _METADATA | {"scripts/byte_identity_baseline.json"}
_ROOTS = ("scripts", "src")


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    root: Path
    revision: str
    trial_id: str
    code_sha256: str
    # Relative path, raw Git blob SHA-256, observed checkout SHA-256.
    files: tuple[tuple[str, str, str], ...]


def _git(root: Path, *args: str) -> bytes:
    result = subprocess.run(  # nosec B603, B607
        ["git", "-C", str(root), *args], capture_output=True, check=False
    )
    if result.returncode:
        raise ValueError("runtime Git check failed")
    return result.stdout


def _identity(root: Path, revision: str) -> None:
    if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise ValueError("runtime revision must be a full commit SHA")
    if Path(os.fsdecode(_git(root, "rev-parse", "--show-toplevel").strip())).resolve() != root:
        raise ValueError("runtime checkout root mismatch")
    if _git(root, "rev-parse", "HEAD").decode().strip() != revision:
        raise ValueError("runtime HEAD mismatch")
    if _git(root, "diff", "--cached", "--name-only", revision, "--", *_ROOTS, *sorted(_METADATA)):
        raise ValueError("runtime staged implementation mismatch")


def _local(root: Path, relative: str) -> Path:
    path = root / relative
    current = path
    while current != root:
        if current.is_symlink() or current.is_junction():
            raise ValueError(f"runtime redirected path: {relative}")
        current = current.parent
    if not path.resolve().is_relative_to(root):
        raise ValueError(f"runtime path outside checkout: {relative}")
    return path


def _inventory(root: Path, revision: str) -> dict[str, bytes]:
    blobs = {}
    for record in _git(root, "ls-tree", "-rz", revision).split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        name = raw_path.decode("utf-8")
        if not (name.startswith(("scripts/", "src/")) or name in _METADATA):
            continue
        mode, kind, _ = metadata.split()
        if kind != b"blob" or mode not in (b"100644", b"100755"):
            raise ValueError(f"runtime unsupported implementation mode: {name}")
        blobs[name] = _git(root, "show", f"{revision}:{name}")
    for required in ("scripts/v3_runtime_preflight.py", "scripts/trial_register.py"):
        if required not in blobs:
            raise ValueError(f"runtime checker missing from implementation: {required}")
    return blobs


def _scan(root: Path, expected: set[str]) -> None:
    for directory in _ROOTS:
        base = _local(root, directory)
        if not base.is_dir():
            raise ValueError(f"runtime missing import root: {directory}")
        for parent, directories, files in os.walk(base, followlinks=False):
            for name in directories + files:
                path = Path(parent) / name
                relative = path.relative_to(root).as_posix()
                _local(root, relative)
                if name == "__pycache__" or path.suffix.lower() in (
                    ".pyc",
                    ".pyo",
                    ".pyd",
                    ".so",
                    ".dll",
                ):
                    raise ValueError(f"runtime unsupported bytecode/extension: {relative}")
                if path.suffix.lower() in (".py", ".pyw") and relative not in expected:
                    raise ValueError(f"runtime unregistered import source: {relative}")


def _read(root: Path, relative: str) -> bytes:
    try:
        return _local(root, relative).read_bytes()
    except OSError as exc:
        raise ValueError(f"runtime missing/unreadable file: {relative}") from exc


def preflight_runtime(root: Path, trial_id: str, revision: str) -> RuntimeSnapshot:
    """Check a fresh isolated checkout; reads only code and registration objects.

    Does not authorize data access, attest installed dependencies or make replay
    inputs ready. Changes only this fresh process's project import search prefix.
    """
    if not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode:
        raise ValueError("runtime requires fresh isolated Python -I -S -B")
    root = root.resolve()
    _identity(root, revision)
    if Path(__file__).resolve() != root / "scripts/v3_runtime_preflight.py":
        raise ValueError("runtime checker loaded from wrong checkout")
    blobs = _inventory(root, revision)
    _scan(root, set(blobs))
    files = []
    for name, blob in sorted(blobs.items()):
        raw = _read(root, name)
        text = name.endswith(".py") or name in _CHECKOUT_TEXT
        if raw != blob and not (text and b"\r" not in blob and raw == blob.replace(b"\n", b"\r\n")):
            raise ValueError(f"runtime working file mismatch: {name}")
        files.append((name, hashlib.sha256(blob).hexdigest(), hashlib.sha256(raw).hexdigest()))
    snapshot = RuntimeSnapshot(root, revision, trial_id, "", tuple(files))
    for name in _modules(snapshot):
        if name in sys.modules and name != __name__:
            raise ValueError(f"runtime project module preloaded before preflight: {name}")
    check_import_origins(snapshot)
    prefix = [str(root / directory) for directory in _ROOTS]
    sys.path[:] = prefix + [p for p in sys.path if p not in prefix]
    register = importlib.import_module("trial_register")
    check_import_origins(snapshot)
    done = register.check_ready(root, trial_id, revision)
    snapshot = RuntimeSnapshot(
        root, revision, trial_id, done["payload"]["code_sha256"], tuple(files)
    )
    recheck_runtime(snapshot)
    return snapshot


def _modules(snapshot: RuntimeSnapshot) -> dict[str, Path]:
    expected = {}
    for relative, _, _ in snapshot.files:
        path = Path(relative)
        if path.suffix != ".py" or path.parts[0] not in _ROOTS:
            continue
        parts = list(path.with_suffix("").parts[1:])
        if parts[-1] == "__init__":
            parts.pop()
        if parts:
            name = ".".join(parts)
            if name in expected:
                raise ValueError(f"runtime ambiguous module: {name}")
            expected[name] = snapshot.root / path
    return expected


def check_import_origins(snapshot: RuntimeSnapshot) -> None:
    """Audit loaded local modules; origin checks cannot detect monkey-patching."""
    expected = _modules(snapshot)
    top_names = {name.split(".")[0] for name in expected}
    for name, module in tuple(sys.modules.items()):
        if module is None:
            continue
        filename = getattr(module, "__file__", None)
        local = isinstance(filename, str) and any(
            Path(filename).resolve().is_relative_to(snapshot.root / directory)
            for directory in _ROOTS
        )
        if name.split(".")[0] not in top_names and not local:
            continue
        target = expected.get(name)
        spec = getattr(module, "__spec__", None)
        origin = getattr(spec, "origin", None)
        loader = getattr(spec, "loader", None)
        if (
            target is None
            or not isinstance(filename, str)
            or not isinstance(origin, str)
            or Path(filename).resolve() != target
            or Path(origin).resolve() != target
            or not isinstance(loader, importlib.machinery.SourceFileLoader)
            or loader.name != name
            or Path(loader.path).resolve() != target
            or getattr(module, "__loader__", None) is not loader
        ):
            raise ValueError(f"runtime imported origin mismatch: {name}")
        paths = getattr(module, "__path__", None)
        locations = getattr(spec, "submodule_search_locations", None)
        package = target.name == "__init__.py"
        for value in (paths, locations):
            if package:
                if value is None or [Path(p).resolve() for p in value] != [target.parent]:
                    raise ValueError(f"runtime package path mismatch: {name}")
            elif value is not None:
                raise ValueError(f"runtime unexpected package path: {name}")


def recheck_runtime(snapshot: RuntimeSnapshot) -> None:
    """Detect later drift; no repair/retry/data access, not race-free attestation."""
    _identity(snapshot.root, snapshot.revision)
    _scan(snapshot.root, {name for name, _, _ in snapshot.files})
    for name, _, observed in snapshot.files:
        if hashlib.sha256(_read(snapshot.root, name)).hexdigest() != observed:
            raise ValueError(f"runtime changed since preflight: {name}")
    check_import_origins(snapshot)
