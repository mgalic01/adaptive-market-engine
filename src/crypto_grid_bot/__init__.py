"""Adaptive crypto grid bot decision core."""

from pathlib import Path


def source_stamp() -> tuple[tuple[str, int, int], ...]:
    """Each of this package's Python sources by path, with its size and modification
    time. Rewriting a file gives it a new time even when its content goes back, so an
    unchanged stamp shows that no source was rewritten in between (Codex review of
    #160)."""
    root = Path(__file__).resolve().parent
    return tuple(
        (path.relative_to(root).as_posix(), (stat := path.stat()).st_size, stat.st_mtime_ns)
        for path in sorted(root.rglob("*.py"))
    )


# Taken first, before any other module of this package is read: backtest.jobs compares
# it with a stamp taken once it has hashed the sources.
IMPORT_STAMP = source_stamp()

__version__ = "0.8.0"
