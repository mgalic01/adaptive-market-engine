"""Adaptive crypto grid bot decision core."""

import hashlib
import sys
from collections.abc import Sequence
from importlib.abc import MetaPathFinder
from importlib.machinery import ModuleSpec, PathFinder, SourceFileLoader
from pathlib import Path
from types import CodeType, ModuleType

# The SHA-256 of the exact source each module of this package was compiled from, by
# module name: the backtest's code identity is of the code that runs, whatever the disk
# holds later (Codex review of #160). Every module below compiles from its source, never
# from a cached .pyc, whose timestamp check can accept old bytecode for a rewritten file.
SOURCE_HASHES: dict[str, str] = {}


class _SourceLoader(SourceFileLoader):
    def get_code(self, fullname: str) -> CodeType:
        source = self.get_data(self.path)
        SOURCE_HASHES[fullname] = hashlib.sha256(source).hexdigest()
        return self.source_to_code(source, self.path)


class _SourceFinder(MetaPathFinder):
    def find_spec(
        self, fullname: str, path: Sequence[str] | None, target: ModuleType | None = None
    ) -> ModuleSpec | None:
        if not fullname.startswith(__name__ + "."):
            return None
        spec = PathFinder.find_spec(fullname, path, target)
        if spec is not None and isinstance(spec.loader, SourceFileLoader):
            spec.loader = _SourceLoader(fullname, spec.loader.path)
        return spec


sys.meta_path.insert(0, _SourceFinder())

# This file was read before the finder existed, perhaps from a cached .pyc: its source
# counts only if it compiles to the code now running.
_source = Path(__file__).read_bytes()
if compile(_source, __file__, "exec", dont_inherit=True) != sys._getframe().f_code:
    raise ImportError(f"{__file__} is not the code that ran (a stale .pyc): rerun")
SOURCE_HASHES[__name__] = hashlib.sha256(_source).hexdigest()
del _source

__version__ = "0.8.0"
