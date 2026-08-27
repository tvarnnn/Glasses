"""A second opinion on a label, bought once per sighting and never per frame.

WHY THIS EXISTS AT ALL.

Reading the crops the shipped detector produced over the real corpus
found that its labels are unreliable for exactly the classes this
cartridge is FOR. A ceiling fan is `airplane` at 0.99 and `scissors` at
0.93. A laptop keyboard is `remote` at 0.87 -- the three highest-scoring
`remote` sightings in 18,821 frames are all keyboards, and the three that
appear to be a real remote all score below 0.68, so the score orders them
exactly wrong. Widening the class whitelist over that detector alone
would fill a wearer's memory with ceiling fans.

So a class the tables consider worth finding, but the detector cannot be
trusted to name, is only written if something else agrees. That is the
whole of this module.

THE RATE, WHICH IS THE POINT.

The physical run produced 4,287 detections in 150 seconds. Nothing here
runs on any of them. Verification is asked ONCE PER SIGHTING, when the
sighting matures -- and the corpus contains 763 sightings across 18,821
frames, of which the `verify`-tier classes account for about 60. That is
roughly **one call per 300 frames**, or one every 25 seconds of delivered
video, against a detector that runs 12 times a second. A semantic model
at 300 ms is then 0.1% of the frame budget, and it is not on the frame
path at all.

Every one of those numbers is counted at runtime rather than assumed:
`VerificationQueue` reports submissions, completions, refusals, drops and
the deepest the backlog ever got, and the producer prints them. A funnel
whose narrowing is not measured is a funnel that has quietly stopped
narrowing.

WHAT A VERIFIER MAY AND MAY NOT DO.

It may say "no". It may say "yes, and here is what I think it is". It may
not introduce a class: `RelevanceFilter` consults it only for classes the
deterministic tables have already admitted, and a verdict naming anything
else is recorded as evidence and changes nothing. The privacy policy is
not a model's to overturn, and `person` is not reachable from here by any
path.

ASYNCHRONOUS, AND BOUNDED.

The queue holds a fixed number of pending crops and DROPS THE OLDEST when
it is full. Dropping is the correct failure: an unverified sighting is
simply not written, which is the same outcome as a Tower with no verifier
at all, whereas an unbounded queue on a fifteen-minute walk is a memory
leak with a semantic model attached to it.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# How many sightings may be waiting for a verdict at once.
#
# Small on purpose. At the measured rate -- roughly one `verify`-tier
# sighting every 25 seconds of walking -- a backlog of eight means the
# verifier has fallen more than three minutes behind, and at that point
# the honest thing is to drop rather than to keep a queue that will never
# catch up. If this is ever seen to fill in the field, the finding is
# that the model is too slow for this host, not that the queue is too
# small.
DEFAULT_MAX_PENDING = 8

# How long a worker waits for a job before checking whether it should
# stop. Short enough that shutdown is prompt, long enough that an idle
# verifier is not a busy loop.
_POLL_SECONDS = 0.2


@dataclass(frozen=True)
class Verdict:
    """What a verifier concluded about one proposed label.

    `agrees` is the only field the policy reads. Everything else is
    provenance, and it is carried onto the persisted record so that a
    memory admitted by a model says WHICH model and HOW STRONGLY -- a
    record that merely said "verified" would be a claim with no way to
    audit it and no way to re-evaluate it when the model changes.

    `label` is what the verifier would have called it, which may differ
    from `proposed` even when it agrees closely enough. It is recorded
    and NOT used to relabel the observation: relabelling would let a
    model move a record between classes the tables gate separately.
    """

    agrees: bool
    proposed: str
    label: str | None
    score: float | None
    model: str
    reason: str

    def to_json_dict(self) -> dict:
        return {
            "agrees": bool(self.agrees),
            "proposed": self.proposed,
            "label": self.label,
            "score": self.score,
            "model": self.model,
            "reason": self.reason,
        }


@runtime_checkable
class Verifier(Protocol):
    """Anything that can second-guess a label on a crop.

    The same load/act/release shape as `tower/detection.py`'s `Detector`,
    for the same reason: whatever holds a model has to be loadable late
    and releasable early, and a protocol says so without anybody
    inheriting anything.
    """

    name: str

    def load(self) -> None: ...

    def verify(self, crop_bgr, proposed_class: str) -> Verdict: ...

    def release(self) -> None: ...


class RefusingVerifier:
    """Agrees with nothing. The default, and not a stub.

    A Tower with no semantic model genuinely cannot tell a remote from a
    laptop keyboard, and this is what saying so looks like. It makes the
    no-verifier configuration a real, tested path rather than a `None`
    check scattered through the producer -- and it means the behaviour of
    a Tower without a model is exercised by the same tests as one with.
    """

    name = "none"

    def load(self) -> None:
        return None

    def verify(self, crop_bgr, proposed_class: str) -> Verdict:
        return Verdict(
            agrees=False,
            proposed=proposed_class,
            label=None,
            score=None,
            model=self.name,
            reason="no-verifier-configured",
        )

    def release(self) -> None:
        return None


class ScriptedVerifier:
    """Returns verdicts a test wrote down. Not a mock of any real model.

    The same argument `FixedDetector` makes: it lets a producer test
    assert against INDEPENDENT truth, because the answers are ones the
    test chose, and it keeps the default suite from downloading 692 MB
    of weights.
    """

    name = "scripted"

    def __init__(self, agrees_with=(), *, delay_seconds: float = 0.0) -> None:
        self._agrees = frozenset(agrees_with)
        self._delay_seconds = delay_seconds
        self.calls: list[str] = []

    def load(self) -> None:
        return None

    def verify(self, crop_bgr, proposed_class: str) -> Verdict:
        if self._delay_seconds:
            time.sleep(self._delay_seconds)
        self.calls.append(proposed_class)
        agrees = proposed_class in self._agrees
        return Verdict(
            agrees=agrees,
            proposed=proposed_class,
            label=proposed_class if agrees else None,
            score=1.0 if agrees else 0.0,
            model=self.name,
            reason="scripted",
        )

    def release(self) -> None:
        return None


@dataclass
class _Job:
    sighting: object
    crop: object
    submitted_at: float


class VerificationQueue:
    """Runs a verifier off the frame path, with a bounded backlog.

    One worker thread, not a pool. The models this is for hold weights,
    and two threads through one model on one device is contention rather
    than throughput; if the rate ever justifies more, the finding will be
    a measured backlog, and the backlog is counted here.

    A synchronous mode exists (`workers=0`) and it is not a debug flag:
    a replay of a recorded capture has no reason to be asynchronous, and
    a test that had to wait for a thread would be a test that sometimes
    does not.
    """

    def __init__(
        self,
        verifier,
        *,
        max_pending: int = DEFAULT_MAX_PENDING,
        workers: int = 1,
        clock=time.monotonic,
    ) -> None:
        self._verifier = verifier
        self._max_pending = max_pending
        self._clock = clock
        self._synchronous = workers < 1

        self._pending: queue.Queue = queue.Queue()
        self._done: queue.Queue = queue.Queue()
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        self._in_flight = 0
        self._lock = threading.Lock()

        self.submitted = 0
        self.completed = 0
        self.agreed = 0
        self.refused = 0
        self.dropped_backlog = 0
        self.failed = 0
        self.peak_pending = 0
        self.verify_seconds = 0.0

    # -- lifecycle ----------------------------------------------------

    def start(self) -> None:
        self._verifier.load()
        if self._synchronous:
            return
        self._thread = threading.Thread(
            target=self._run, name="object-memory-verify", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 30.0) -> None:
        """Stop accepting work and wait for what is in flight.

        Waits rather than abandoning, because a verdict that arrives
        after the producer has exited is a sighting silently not written.
        Bounded, because a model that has hung must not hold a session
        open forever -- and the bound is generous relative to any
        per-crop cost this is meant to run.
        """
        self._stopping.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logger.warning(
                    "[Tower][ObjectMemory] the verifier did not finish within "
                    "%.0fs; %s sightings will not be verified",
                    timeout,
                    self._in_flight + self._pending.qsize(),
                )
        self._verifier.release()

    # -- work ---------------------------------------------------------

    def submit(self, sighting, crop) -> bool:
        """Queue one sighting for a verdict. False if it was dropped.

        Dropping the OLDEST is deliberate. A backlog means the verifier
        is behind the walk, and the sighting most likely to still be
        worth verifying is the newest one -- the wearer is looking at it
        now. Dropping the newest would make the queue a device for
        remembering only the beginning of a walk.
        """
        if self._stopping.is_set():
            return False
        if self._synchronous:
            self.submitted += 1
            self._run_one(_Job(sighting, crop, self._clock()))
            return True

        while self._pending.qsize() >= self._max_pending:
            try:
                self._pending.get_nowait()
            except queue.Empty:
                break
            self.dropped_backlog += 1
            logger.warning(
                "[Tower][ObjectMemory] verification backlog full (%s); the "
                "oldest waiting sighting was dropped and will not be "
                "remembered",
                self._max_pending,
            )
        self.submitted += 1
        self._pending.put(_Job(sighting, crop, self._clock()))
        self.peak_pending = max(self.peak_pending, self._pending.qsize())
        return True

    def drain(self) -> list:
        """Every sighting whose verdict has arrived since the last call.

        Pulled by the producer on the frame path rather than pushed by
        the worker, so nothing mutates a sighting from another thread.
        The producer owns its sightings; the queue owns only the crop it
        was handed and the verdict it produces.
        """
        finished = []
        while True:
            try:
                finished.append(self._done.get_nowait())
            except queue.Empty:
                return finished

    def wait_idle(self, timeout: float = 30.0) -> bool:
        """Block until nothing is queued or in flight. Returns whether it is.

        For the end of a session and for tests. A producer that exited
        without waiting would discard verdicts it had already paid for.
        """
        deadline = self._clock() + timeout
        while self._clock() < deadline:
            with self._lock:
                busy = self._in_flight
            if self._pending.empty() and busy == 0:
                return True
            time.sleep(0.01)
        return False

    def counters(self) -> dict:
        return {
            "verifier": self._verifier.name,
            "submitted": self.submitted,
            "completed": self.completed,
            "agreed": self.agreed,
            "refused": self.refused,
            "failed": self.failed,
            # The measurement that says whether the funnel is holding.
            # Non-zero means the semantic stage could not keep up with a
            # walk, and sightings went unremembered because of it.
            "dropped_backlog": self.dropped_backlog,
            "peak_pending": self.peak_pending,
            "seconds": round(self.verify_seconds, 3),
            "ms_per_call": (
                round(self.verify_seconds * 1000 / self.completed, 1)
                if self.completed
                else None
            ),
        }

    # -- internals ----------------------------------------------------

    def _run(self) -> None:
        while True:
            try:
                job = self._pending.get(timeout=_POLL_SECONDS)
            except queue.Empty:
                if self._stopping.is_set():
                    return
                continue
            self._run_one(job)

    def _run_one(self, job: _Job) -> None:
        with self._lock:
            self._in_flight += 1
        started = self._clock()
        try:
            verdict = self._verifier.verify(job.crop, job.sighting.object_class)
        except Exception:
            # Counted, not swallowed, and NOT treated as agreement. A
            # verifier that raised has said nothing, and "said nothing"
            # must resolve the same way as "said no" -- otherwise a
            # broken model becomes a way to widen the policy.
            self.failed += 1
            logger.exception(
                "[Tower][ObjectMemory] the verifier raised on a %s sighting; "
                "it will not be remembered",
                job.sighting.object_class,
            )
            verdict = Verdict(
                agrees=False,
                proposed=job.sighting.object_class,
                label=None,
                score=None,
                model=getattr(self._verifier, "name", "unknown"),
                reason="verifier-failed",
            )
        finally:
            elapsed = self._clock() - started
            with self._lock:
                self._in_flight -= 1
            self.verify_seconds += elapsed

        self.completed += 1
        if verdict.agrees:
            self.agreed += 1
        else:
            self.refused += 1
        self._done.put((job.sighting, verdict))
