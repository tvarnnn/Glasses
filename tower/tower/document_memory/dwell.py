"""Has this page been held in view long enough to be worth reading?

The expensive path costs ~1.2 s of OCR per page, so the whole design
depends on this stage being both cheap and stingy. A single frame
containing a page-shaped object is not a reading event; it is a glance, a
reflection, or a poster on a wall the wearer walked past.

**Both a frame count and a wall-clock duration are required.** Frame rate
is not fixed here -- at the delivered ~3.3 fps, "six frames" is nearly two
seconds; at 12 fps it is half of one. A policy expressed only in frames
would silently mean something different every time the transport changed.

None of this measures attention. It measures a page-like region being
present and steady. `07-PLATFORM-CONSTRAINTS.md` Limitation 8 is explicit
that the camera cannot establish that the wearer looked at, noticed or
read anything, and no threshold in this file changes that.
"""

from dataclasses import dataclass, field, replace

import numpy as np

from tower.document_memory.detect import PageCandidate
from tower.document_memory.records import (
    END_REASON_LOST,
    END_REASON_MAX_DURATION,
    END_REASON_STOPPED,
)


@dataclass(frozen=True)
class DwellPolicy:
    """Every threshold, in one place, each with a reason.

    Deliberately a value object rather than module constants: the
    benchmark sweeps these, and a threshold that cannot be swept cannot be
    chosen from data.
    """

    # A glance is not a reading event. Both must be satisfied.
    min_frames: int = 4
    min_seconds: float = 1.0
    # A page turn, a blink of occlusion or one bad frame must not end a
    # dwell; walking away must.
    max_missing_frames: int = 3
    # Rule 15: nothing unbounded. A page left on a desk in view all
    # afternoon becomes one bounded observation, not an ever-growing one.
    max_seconds: float = 180.0
    # A gap this large between two detections is not one continuous
    # reading. Timestamps come from the capture journal and are WALL
    # CLOCK, so this also contains the damage when a clock jumps: an
    # adversarial review produced a document claiming 92 days of reading
    # from a single bad timestamp.
    max_frame_gap_s: float = 5.0
    # How much the region may move between frames and still be "the same
    # page", as a fraction of the frame diagonal. A person holding a page
    # is not a tripod.
    max_centre_shift_fraction: float = 0.18
    # And how much it may change size. Leaning in is the same page.
    min_area_ratio: float = 0.5
    max_area_ratio: float = 2.0
    # How many frames get the expensive path, per dwell.
    best_frames: int = 2
    # A frame this blurry is not worth OCR even if it is the best one seen.
    min_sharpness: float = 60.0


@dataclass
class ScoredFrame:
    """A candidate frame, kept only if it might earn the expensive path."""

    source_seq: int | None
    at: float
    candidate: PageCandidate
    gray: np.ndarray

    @property
    def score(self) -> float:
        """Sharpness first, squareness as the tie-break.

        Both matter and they are not interchangeable: a razor-sharp page
        seen at 60 degrees warps into something OCR reads badly, and a
        perfectly square page that is out of focus reads worse still.
        Multiplying lets one veto the other.
        """
        return self.candidate.sharpness * max(self.candidate.squareness, 0.05)


@dataclass
class Dwell:
    """One sustained observation in progress, or just finished."""

    started_at: float
    last_seen_at: float
    frames_seen: int = 0
    frames_considered: int = 0
    missing_frames: int = 0
    best: list[ScoredFrame] = field(default_factory=list)
    end_reason: str = END_REASON_LOST
    reference: PageCandidate | None = None
    # Whatever the caller said the frames belonged to when this dwell
    # STARTED, kept opaque so this module stays free of any notion of a
    # capture. Set once, in `_start`, and never touched by `_extend`.
    #
    # Set once is the entire point. Document Memory stamps a capture id
    # onto the record a dwell produces, and it used to read that id at
    # RECORD time -- so a `stream_start` arriving mid-dwell (a phone
    # reconnect re-arms the recorder) moved every frame of that reading
    # onto a capture it did not come from, and a `stream_stop` erased it
    # entirely. Both were measured. A pointer that resolves to the wrong
    # frame is worse than no pointer at all.
    lineage: object | None = None
    # Accumulated FORWARD-ONLY, one inter-frame delta at a time.
    elapsed_seconds: float = 0.0
    clock_regressions: int = 0

    @property
    def seconds(self) -> float:
        """How long the page was observed, immune to a clock that moves back.

        Accumulated from positive inter-frame deltas rather than computed
        as `last_seen_at - started_at`. The difference is not academic:
        timestamps are wall-clock from the capture journal, so an NTP
        correction on the LAST frame of an otherwise perfect dwell used to
        clamp this to zero, fail `qualifies()`, and discard the whole
        document with no error and no trace.
        """
        return self.elapsed_seconds

    def qualifies(self, policy: DwellPolicy) -> bool:
        return (
            self.frames_seen >= policy.min_frames
            and self.seconds >= policy.min_seconds
            and bool(self.best)
        )


class DwellTracker:
    """The state machine. Cheap, and the only thing that opens the wallet.

    Returns a completed `Dwell` from `observe()` on the frame where it
    ends -- so a caller never has to poll, and a dwell that never
    qualifies is simply dropped without the caller learning about it.
    """

    def __init__(self, policy: DwellPolicy | None = None) -> None:
        self._policy = policy or DwellPolicy()
        self._current: Dwell | None = None

    @property
    def policy(self) -> DwellPolicy:
        return self._policy

    @property
    def in_dwell(self) -> bool:
        return self._current is not None

    @property
    def current(self) -> Dwell | None:
        return self._current

    def observe(
        self,
        candidate: PageCandidate | None,
        *,
        at: float,
        gray: np.ndarray | None = None,
        source_seq: int | None = None,
        frame_diagonal: float | None = None,
        lineage: object | None = None,
    ) -> Dwell | None:
        """Feed one frame. Returns a completed dwell, or None."""
        if candidate is None:
            return self._miss(at)

        if self._current is None:
            self._start(candidate, at, gray, source_seq, lineage)
            return None

        if lineage != self._current.lineage:
            # The frames stopped belonging to the recording this dwell
            # started in. A reconnect re-arms the recorder, mints a new
            # capture id, and `source_seq` restarts with it.
            #
            # Ending the dwell is the only honest answer. Keeping it open
            # froze `capture_id` at the old capture while letting frames
            # from the new one win the OCR slots -- so the published
            # `page_source_seqs` resolved into the OLD journal and named
            # completely different frames. Silent, plausible and wrong,
            # which is worse than no pointer at all. Same reasoning
            # `_is_same_region` applies to a different page.
            finished = self._finish(END_REASON_LOST)
            self._start(candidate, at, gray, source_seq, lineage)
            return finished

        if at - self._current.last_seen_at > self._policy.max_frame_gap_s:
            # Too long since the last detection for this to be one
            # continuous reading -- a stalled stream, or a clock jump.
            # Ending the dwell contains the damage either way.
            finished = self._finish(END_REASON_LOST)
            self._start(candidate, at, gray, source_seq, lineage)
            return finished

        if not self._is_same_region(candidate, frame_diagonal):
            # A different page is a NEW dwell, not a continuation. Without
            # this, turning from one document to another would merge two
            # documents into one record with interleaved text.
            finished = self._finish(END_REASON_LOST)
            self._start(candidate, at, gray, source_seq, lineage)
            return finished

        self._extend(candidate, at, gray, source_seq)

        if self._current.seconds >= self._policy.max_seconds:
            return self._finish(END_REASON_MAX_DURATION)
        return None

    def flush(self, reason: str = END_REASON_STOPPED) -> Dwell | None:
        """End an open dwell because the stream did, not because the page did."""
        if self._current is None:
            return None
        return self._finish(reason)

    # -- internals -----------------------------------------------------

    def _start(self, candidate, at, gray, source_seq, lineage=None) -> None:
        self._current = Dwell(
            started_at=at,
            last_seen_at=at,
            reference=candidate,
            lineage=lineage,
        )
        self._extend(candidate, at, gray, source_seq)

    def _extend(self, candidate, at, gray, source_seq) -> None:
        dwell = self._current
        delta = at - dwell.last_seen_at
        if delta < 0:
            # The clock moved back. Contribute nothing rather than
            # subtracting, and record that it happened so a short
            # observation is explainable.
            dwell.clock_regressions += 1
        else:
            dwell.elapsed_seconds += delta
        dwell.frames_seen += 1
        dwell.frames_considered += 1
        dwell.last_seen_at = at
        dwell.missing_frames = 0
        # The reference tracks the latest accepted region rather than the
        # first: a wearer drifting slowly across a page would otherwise
        # eventually fail the same-region test against where they started.
        dwell.reference = candidate

        if gray is None or candidate.sharpness < self._policy.min_sharpness:
            return
        scored = ScoredFrame(
            source_seq=source_seq, at=at, candidate=candidate, gray=gray
        )
        dwell.best.append(scored)
        dwell.best.sort(key=lambda frame: frame.score, reverse=True)
        # Bounded: only the frames that will actually be OCR'd are
        # retained, so a long dwell cannot accumulate imagery.
        del dwell.best[self._policy.best_frames :]

    def _miss(self, at: float) -> Dwell | None:
        if self._current is None:
            return None
        self._current.missing_frames += 1
        self._current.frames_considered += 1
        if self._current.missing_frames > self._policy.max_missing_frames:
            return self._finish(END_REASON_LOST)
        return None

    def _finish(self, reason: str) -> Dwell | None:
        dwell = self._current
        self._current = None
        if dwell is None:
            return None
        dwell = replace(dwell, end_reason=reason)
        return dwell if dwell.qualifies(self._policy) else None

    def _is_same_region(
        self, candidate: PageCandidate, frame_diagonal: float | None
    ) -> bool:
        reference = self._current.reference
        if reference is None:
            return True

        if frame_diagonal:
            shift = float(
                np.linalg.norm(
                    np.asarray(candidate.centre) - np.asarray(reference.centre)
                )
            )
            if shift / frame_diagonal > self._policy.max_centre_shift_fraction:
                return False

        if reference.area_fraction <= 0:
            return True
        ratio = candidate.area_fraction / reference.area_fraction
        return self._policy.min_area_ratio <= ratio <= self._policy.max_area_ratio
