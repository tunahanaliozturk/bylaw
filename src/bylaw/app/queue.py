"""An in-process review queue, idempotent by repository, pull request and head commit (ADR 0017).

Everything here runs on the event loop's thread except the review itself, which runs in a worker thread,
so the bookkeeping needs no locks. Nothing survives a restart: a review missed then runs on the next push,
or when the delivery is redelivered from the app's settings.
"""

import asyncio
import logging
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from enum import StrEnum

log = logging.getLogger("bylaw.app")

type Key = tuple[str, int]


def flat(text: str) -> str:
    """One line. Text from a repository or a model must not be able to forge a log line."""
    return " ".join(text.splitlines())


@dataclass(frozen=True, slots=True)
class Job:
    installation_id: int
    repo: str
    number: int
    head_sha: str
    # The label a `labeled` event added; a label can unlock the model review, so it reviews again once.
    label: str | None = None

    @property
    def key(self) -> Key:
        return self.repo.lower(), self.number

    @property
    def mark(self) -> str:
        """What makes two jobs for one pull request the same review."""
        return self.head_sha if self.label is None else f"{self.head_sha}+{self.label}"


class Outcome(StrEnum):
    QUEUED = "queued"
    # Another head replaced one that had not started yet; the review reads whatever the head is then.
    SUPERSEDED = "superseded"
    # This head is queued, under review or already reviewed.
    DUPLICATE = "duplicate"
    # Too many pull requests are waiting; GitHub marks the delivery failed and it can be redelivered.
    BUSY = "busy"


class ReviewQueue:
    def __init__(
        self,
        # Reviews a job and returns the head commit it read, which may be newer than the job's.
        run: Callable[[Job], str | None],
        *,
        workers: int = 2,
        max_pending: int = 100,
        max_pending_per_installation: int = 20,
        remembered: int = 10_000,
    ) -> None:
        self._run = run
        self._workers = workers
        self._max_pending = max_pending
        # So that one organisation, or a flood of pull requests into one, cannot turn every other away.
        self._max_per_installation = max_pending_per_installation
        self._remembered = remembered
        self._pending: dict[Key, Job] = {}
        self._running: dict[Key, Job] = {}
        # ponytail: reviewed heads are kept in memory, the oldest forgotten first; a durable store would
        # also stop the one repeat review a restart allows, which incremental review makes cheap (ADR 0012).
        self._done: OrderedDict[tuple[Key, str], None] = OrderedDict()
        self._ready: asyncio.Queue[Key] = asyncio.Queue()

    def offer(self, job: Job) -> Outcome:
        key = job.key
        running = self._running.get(key)
        if (key, job.mark) in self._done or (running is not None and running.mark == job.mark):
            return Outcome.DUPLICATE
        if (queued := self._pending.get(key)) is not None:
            if queued.mark == job.mark:
                return Outcome.DUPLICATE
            # The review reads the pull request as it is when it starts, so one waiting job is enough, even
            # when a redelivered older event replaces a newer one: the head the review reads is remembered.
            self._pending[key] = job
            return Outcome.SUPERSEDED
        mine = sum(1 for waiting in self._pending.values() if waiting.installation_id == job.installation_id)
        if len(self._pending) >= self._max_pending or mine >= self._max_per_installation:
            return Outcome.BUSY
        self._pending[key] = job
        if running is None:
            # One review per pull request at a time: a key under review is queued again when it finishes.
            self._ready.put_nowait(key)
        return Outcome.QUEUED

    def stats(self) -> dict[str, int]:
        return {"pending": len(self._pending), "running": len(self._running)}

    async def join(self) -> None:
        """Wait until nothing is queued or under review."""
        await self._ready.join()

    @asynccontextmanager
    async def running(self) -> AsyncIterator[None]:
        tasks = [asyncio.create_task(self._work()) for _ in range(self._workers)]
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError):
                    await task

    async def _work(self) -> None:
        while True:
            key = await self._ready.get()
            try:
                job = self._pending.pop(key)
                self._running[key] = job
                try:
                    read = await asyncio.to_thread(self._run, job)
                except Exception as error:  # one failed review must not stop the worker
                    # Not remembered, so a redelivery of the same event retries it.
                    log.error(
                        "review of %s#%d at %s failed: %s: %s",
                        job.repo,
                        job.number,
                        job.head_sha,
                        type(error).__name__,
                        flat(str(error)),
                    )
                else:
                    # The head the review read is reviewed too, whatever older head the event named.
                    self._remember((key, job.head_sha))
                    self._remember((key, job.mark))
                    if read is not None:
                        self._remember((key, read))
                finally:
                    del self._running[key]
                    if key in self._pending:
                        self._ready.put_nowait(key)
            finally:
                self._ready.task_done()

    def _remember(self, done: tuple[Key, str]) -> None:
        self._done[done] = None
        while len(self._done) > self._remembered:
            self._done.popitem(last=False)
