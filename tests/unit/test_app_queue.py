import asyncio
import threading

import pytest

from bylaw.app.queue import Job, Outcome, ReviewQueue


def _job(sha: str, number: int = 5, repo: str = "acme/app") -> Job:
    return Job(installation_id=7, repo=repo, number=number, head_sha=sha)


class Recorder:
    """A review that records what it ran and can be held until the test lets it finish."""

    def __init__(self, fail: frozenset[str] = frozenset()) -> None:
        self.ran: list[str] = []
        self.release = threading.Event()
        self.release.set()
        self.started = threading.Event()
        self.fail = fail
        self.concurrent = 0
        self.most_concurrent = 0
        self._lock = threading.Lock()
        # The head the pull request is at when a review reads it, by the head the event named.
        self.live: dict[str, str] = {}

    def __call__(self, job: Job) -> str:
        with self._lock:
            self.concurrent += 1
            self.most_concurrent = max(self.most_concurrent, self.concurrent)
        self.started.set()
        self.release.wait(5)
        with self._lock:
            self.concurrent -= 1
        self.ran.append(f"{job.number}@{job.head_sha}")
        if job.head_sha in self.fail:
            raise RuntimeError("GitHub was down")
        return self.live.get(job.head_sha, job.head_sha)


async def _wait_started(recorder: Recorder) -> None:
    await asyncio.to_thread(recorder.started.wait, 5)


def test_a_head_already_reviewed_is_not_reviewed_again() -> None:
    async def scenario() -> tuple[list[Outcome], list[str]]:
        recorder = Recorder()
        queue = ReviewQueue(recorder)
        async with queue.running():
            first = queue.offer(_job("a"))
            await queue.join()
            again = queue.offer(_job("a"))
            await queue.join()
        return [first, again], recorder.ran

    outcomes, ran = asyncio.run(scenario())

    assert outcomes == [Outcome.QUEUED, Outcome.DUPLICATE]
    assert ran == ["5@a"]


def test_a_duplicate_of_a_queued_or_running_head_does_nothing() -> None:
    async def scenario() -> tuple[list[Outcome], list[str]]:
        recorder = Recorder()
        recorder.release.clear()
        queue = ReviewQueue(recorder, workers=1)
        async with queue.running():
            outcomes = [queue.offer(_job("a"))]
            await _wait_started(recorder)
            outcomes.append(queue.offer(_job("a")))  # running
            outcomes.append(queue.offer(_job("b", number=6)))
            outcomes.append(queue.offer(_job("b", number=6)))  # queued
            recorder.release.set()
            await queue.join()
        return outcomes, recorder.ran

    outcomes, ran = asyncio.run(scenario())

    assert outcomes == [Outcome.QUEUED, Outcome.DUPLICATE, Outcome.QUEUED, Outcome.DUPLICATE]
    assert ran == ["5@a", "6@b"]


def test_a_newer_head_supersedes_an_older_one_still_queued() -> None:
    async def scenario() -> tuple[list[Outcome], list[str]]:
        recorder = Recorder()
        recorder.release.clear()
        queue = ReviewQueue(recorder, workers=1)
        async with queue.running():
            outcomes = [queue.offer(_job("x", number=9))]  # keeps the only worker busy
            await _wait_started(recorder)
            outcomes += [queue.offer(_job("a")), queue.offer(_job("b")), queue.offer(_job("c"))]
            recorder.release.set()
            await queue.join()
        return outcomes, recorder.ran

    outcomes, ran = asyncio.run(scenario())

    assert outcomes == [Outcome.QUEUED, Outcome.QUEUED, Outcome.SUPERSEDED, Outcome.SUPERSEDED]
    assert ran == ["9@x", "5@c"]


def test_a_push_during_a_review_runs_after_it_and_never_alongside_it() -> None:
    async def scenario() -> tuple[Outcome, list[str], int]:
        recorder = Recorder()
        recorder.release.clear()
        queue = ReviewQueue(recorder, workers=4)
        async with queue.running():
            queue.offer(_job("a"))
            await _wait_started(recorder)
            outcome = queue.offer(_job("b"))
            await asyncio.sleep(0.05)  # four workers are free; none may take the same pull request
            recorder.release.set()
            await queue.join()
        return outcome, recorder.ran, recorder.most_concurrent

    outcome, ran, most = asyncio.run(scenario())

    assert (outcome, ran, most) == (Outcome.QUEUED, ["5@a", "5@b"], 1)


def test_different_pull_requests_are_reviewed_in_parallel_up_to_the_worker_count() -> None:
    async def scenario() -> int:
        recorder = Recorder()
        recorder.release.clear()
        queue = ReviewQueue(recorder, workers=2)
        async with queue.running():
            for number in range(1, 5):
                queue.offer(_job("a", number=number))
            await asyncio.sleep(0.1)
            recorder.release.set()
            await queue.join()
        return recorder.most_concurrent

    assert asyncio.run(scenario()) == 2


def test_a_full_queue_turns_new_work_away() -> None:
    async def scenario() -> list[Outcome]:
        recorder = Recorder()
        recorder.release.clear()
        queue = ReviewQueue(recorder, workers=1, max_pending=2)
        async with queue.running():
            outcomes = [queue.offer(_job("x", number=9))]
            await _wait_started(recorder)
            outcomes += [queue.offer(_job("a", number=n)) for n in (1, 2, 3)]
            outcomes.append(queue.offer(_job("b", number=1)))  # a newer head still fits in its slot
            recorder.release.set()
            await queue.join()
        return outcomes

    assert asyncio.run(scenario()) == [
        Outcome.QUEUED,
        Outcome.QUEUED,
        Outcome.QUEUED,
        Outcome.BUSY,
        Outcome.SUPERSEDED,
    ]


def test_a_failed_review_is_not_remembered_so_a_redelivery_retries_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def scenario() -> tuple[Outcome, list[str]]:
        recorder = Recorder(fail=frozenset({"a"}))
        queue = ReviewQueue(recorder)
        async with queue.running():
            queue.offer(_job("a"))
            await queue.join()
            retry = queue.offer(_job("a"))
            await queue.join()
        return retry, recorder.ran

    retry, ran = asyncio.run(scenario())

    assert (retry, ran) == (Outcome.QUEUED, ["5@a", "5@a"])
    assert "acme/app#5 at a failed: RuntimeError: GitHub was down" in caplog.text


def test_the_same_number_in_another_repository_is_another_pull_request() -> None:
    async def scenario() -> list[str]:
        recorder = Recorder()
        queue = ReviewQueue(recorder)
        async with queue.running():
            queue.offer(_job("a"))
            queue.offer(_job("a", repo="acme/other"))
            await queue.join()
        return recorder.ran

    assert asyncio.run(scenario()) == ["5@a", "5@a"]


def test_only_so_many_reviewed_heads_are_remembered() -> None:
    async def scenario() -> Outcome:
        queue = ReviewQueue(Recorder(), remembered=2)
        async with queue.running():
            for sha in ("a", "b", "c"):
                queue.offer(_job(sha))
                await queue.join()
        return queue.offer(_job("a"))

    assert asyncio.run(scenario()) == Outcome.QUEUED


def test_an_error_message_from_a_repository_is_logged_on_one_line(caplog: pytest.LogCaptureFixture) -> None:
    def fail(_: Job) -> None:
        # A quoted TOML key can hold a line break, and it reaches ConfigError's message.
        raise ValueError('.bylaw.toml is invalid: "x\nERROR bylaw.app: forged line"')

    async def scenario() -> None:
        queue = ReviewQueue(fail)
        async with queue.running():
            queue.offer(_job("a"))
            await queue.join()

    asyncio.run(scenario())

    [record] = [r for r in caplog.records if "failed" in r.getMessage()]
    assert "\n" not in record.getMessage()
    assert "forged line" in record.getMessage()


def test_the_head_a_review_read_counts_as_reviewed_even_when_the_event_named_an_older_one() -> None:
    async def scenario() -> tuple[Outcome, list[str]]:
        recorder = Recorder()
        recorder.live = {"a": "b"}  # pushed again before the review started
        queue = ReviewQueue(recorder)
        async with queue.running():
            queue.offer(_job("a"))
            await queue.join()
            newer = queue.offer(_job("b"))
            await queue.join()
        return newer, recorder.ran

    newer, ran = asyncio.run(scenario())

    assert (newer, ran) == (Outcome.DUPLICATE, ["5@a"])


def test_a_redelivered_older_event_that_replaced_a_newer_one_still_reviews_the_newer_head() -> None:
    async def scenario() -> tuple[list[Outcome], list[str]]:
        recorder = Recorder()
        recorder.release.clear()
        queue = ReviewQueue(recorder, workers=1)
        async with queue.running():
            queue.offer(_job("x", number=9))  # keeps the only worker busy
            await _wait_started(recorder)
            outcomes = [queue.offer(_job("b")), queue.offer(_job("a"))]  # a redelivery of an older push
            recorder.live = {"a": "b"}  # the pull request is at b whatever the event said
            recorder.release.set()
            await queue.join()
            outcomes.append(queue.offer(_job("b")))
            await queue.join()
        return outcomes, recorder.ran

    outcomes, ran = asyncio.run(scenario())

    assert outcomes == [Outcome.QUEUED, Outcome.SUPERSEDED, Outcome.DUPLICATE]
    assert ran == ["9@x", "5@a"]
