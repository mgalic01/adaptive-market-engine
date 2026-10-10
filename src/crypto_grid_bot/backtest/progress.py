"""Progress lines for a long backtest: what stage it is at and how far it has got.

A full-range run takes hours, and the CLI prints its results only at the end. These lines
tell a reader of the log where it is. Each goes to stderr, flushed, behind a fixed prefix so
that a log is easy to filter (``grep '^progress: '``)::

    progress: [1:12:03] replay 3/8 done BTCUSDT high_first MS in 0:41:10

The bracket is the time since the command began and ``in`` the job's own time, both as
``H:MM:SS``. They come from ``time.monotonic`` and are read nowhere else in the package: no
result, no written file, no line of stdout and no return value ever holds one. Nothing here
changes what a run decides or writes, and a stderr that cannot be written to does not stop it.

A phase is a span of the run (``Progress.phase``): it reports its start and its end, "done in"
or, when it raises, "failed after". A phase made of jobs (``Stage``) reports each job twice,
"k/N start" as it is submitted and "k/N done" (or "failed", when it raised or was cancelled) as
it finishes, ``k`` counting submissions for the first and completions for the second. The job
is submitted to the executor the CLI chose. Through the in-process executor (``--jobs 1``) it
runs inside ``submit``, so its two lines enclose its work; if it raises, ``submit`` raises
before there is a future, so the stage reports the failure itself and re-raises the exception
unchanged. Through a process pool every job of a phase is submitted at once and a done line
follows each future as the pool finishes it, in the pool's own order, so a pool job's time runs
from its submission and includes any wait for a free worker.

A future wakes the threads waiting in ``result()`` before it runs its done callbacks, so a
caller can reach the end of a phase before the last job's line is printed. A phase that ends
without raising therefore waits, with no time limit, until every job submitted through its
stage has been reported (a cancelled or failed one is reported too, so an error cannot hang
it). A phase that raises does not wait: it reports its failure at once and re-raises, and a
job still running in the pool reports itself if it ever ends.
"""

from __future__ import annotations

import contextlib
import sys
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future
from contextlib import contextmanager
from functools import partial
from typing import Any, Protocol

PREFIX = "progress: "


def elapsed_text(seconds: float) -> str:
    """``seconds`` as ``H:MM:SS`` (the hours not limited to a day, none ever negative)."""
    hours, rest = divmod(int(max(seconds, 0)), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


class Submitter(Protocol):
    """What a stage needs of an executor: the CLI's in-process one or a process pool."""

    def submit(self, fn: Callable[..., Any], /, *args: Any) -> Future[Any]: ...


class Progress:
    """The progress lines of one command, timed from when it was created."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.began = clock()
        # Lines come from the main thread and from the pool's thread that finishes futures.
        self.lock = threading.RLock()

    def since(self, moment: float) -> str:
        """The time from ``moment`` (a reading of the clock) to now, as ``H:MM:SS``."""
        return elapsed_text(self.clock() - moment)

    def note(self, text: str) -> None:
        """One progress line, with the time since the command began. A stderr that is
        missing, closed or broken drops it: progress is never a reason to stop a run, and
        a missing stderr must not send it to stdout (``print(file=None)`` would)."""
        stream = sys.stderr
        if stream is None:
            return
        with self.lock, contextlib.suppress(OSError, ValueError):
            print(f"{PREFIX}[{self.since(self.began)}] {text}", file=stream, flush=True)

    @contextmanager
    def phase(self, name: str, total: int = 0) -> Iterator[Stage]:
        """Report the start and the end of a phase ``name`` made of ``total`` jobs (none:
        it is a step, not a set of jobs). The ``Stage`` it yields submits and reports the
        phase's jobs. At the end the phase waits, with no time limit, for every job's line
        to be printed, so that "done" is never ahead of one (a future wakes ``result()``
        before it runs its callbacks). If the phase raises it writes "failed after" instead,
        without waiting for jobs that are still running, and re-raises the exception."""
        began = self.clock()
        self.note(f"{name} start" + (f" ({total} job{'' if total == 1 else 's'})" if total else ""))
        stage = Stage(self, name, total)
        try:
            yield stage
        except BaseException:
            self.note(f"{name} failed after {self.since(began)}")
            raise
        stage.wait()
        self.note(f"{name} done in {self.since(began)}")


class Stage:
    """The ``total`` jobs of one phase."""

    def __init__(self, progress: Progress, name: str, total: int) -> None:
        self.progress, self.name, self.total = progress, name, total
        self.submitted = 0
        self.finished = 0
        # Signalled, under the progress lock, as each job's line is written.
        self.reported = threading.Condition(progress.lock)

    def submit(
        self, pool: Submitter, label: str, fn: Callable[..., Any], /, *args: Any
    ) -> Future[Any]:
        """``pool.submit(fn, *args)`` for the job named ``label``, reporting it as submitted
        now and as finished when its future is. The future is returned as the pool gave it,
        so the caller awaits it as before; a callback that raises is logged and ignored by
        ``concurrent.futures``, never raised. A pool that raises from ``submit`` itself, as
        the in-process executor does when the job raises, has the job reported failed, and
        the exception goes on unchanged."""
        self.submitted += 1
        self.progress.note(f"{self.name} {self.submitted}/{self.total} start {label}")
        began = self.progress.clock()
        try:
            future = pool.submit(fn, *args)
        except BaseException:
            self._report(label, began, failed=True)
            raise
        future.add_done_callback(partial(self._finish, label, began))
        return future

    def wait(self) -> None:
        """Block, with no time limit, until every job submitted has been reported."""
        with self.reported:
            self.reported.wait_for(lambda: self.finished >= self.submitted)

    def _finish(self, label: str, began: float, future: Future[Any]) -> None:
        failed = future.cancelled() or future.exception() is not None
        self._report(label, began, failed=failed)

    def _report(self, label: str, began: float, *, failed: bool) -> None:
        """Count a job as finished and write its line, together under the lock, so that the
        lines stay in order and a waiter that sees the count sees the line."""
        with self.reported:
            self.finished += 1
            try:
                verb, joint = ("failed", "after") if failed else ("done", "in")
                self.progress.note(
                    f"{self.name} {self.finished}/{self.total} {verb} {label} "
                    f"{joint} {self.progress.since(began)}"
                )
            finally:
                self.reported.notify_all()
