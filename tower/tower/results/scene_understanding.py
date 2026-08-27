"""Live-scene transport adapter for Scene Understanding.

Named after its cartridge, for the reason `world_builder.py` and
`object_memory.py` are: an adapter named after one cartridge cannot leak
that cartridge's assumptions into the next, because the next one gets its
own file.

THIS FILE PROJECTS. IT DOES NOT DRIVE.

It is handed a `SceneState` that a worker thread already produced and
turns it into JSON. It never calls `SceneEngine.observe`, never decodes a
frame and never starts anything -- `test_the_result_channel_never_writes`
forbids a call named `observe` or `build` anywhere under `tower/results/`,
and that prohibition is doing real work here rather than being an
inconvenience: a results module that could drive an engine would be a
second, unsynchronised frame path.

WHAT THIS PAYLOAD MAY NOT SAY, AND WHY THE REASONING IS NOT THE OBVIOUS ONE

The reflex is "minimise disclosure". That reflex is wrong here and the
correct analysis is narrower:

    Tower -> phone is inside the local-first boundary. THE PHONE SENT THE
    PIXELS. A count therefore discloses strictly LESS than the frame the
    phone already holds, and withholding it while shipping frames is
    theatre.

What is genuinely new is **joinability**. A stable `track_id` plus a
timestamp lets a recipient assemble the per-person dwell timeline this
cartridge refuses to keep -- persists-nothing laundered onto the consumer.
The cartridge's best property would be defeated not by what it says but
by what someone could accumulate from it.

So, for people: no `track_id`, no bounding box, no `normalised_x` or
`view_offset`, no per-person facing state, and no `visible_eyes` /
`visible_ears`. Facial-landmark evidence does not cross this boundary at
all. Facing is an aggregate count or an explicit `null` with a reason --
never zero, because zero is an answer and "never measured" is not.

`where` therefore excludes `person` and carries SIDE COUNTS rather than a
side. One side per label cannot describe a chair on the left and a chair
on the right, and picking one of them would be a wrong answer where a
refusal was available.

REFUSED RELATIONS ARE UNEXPRESSIBLE, NOT MERELY UNPOPULATED

`relations` is `None` and there is no schema slot anywhere below that
could hold `in_front_of`. A refusal that depends on remembering not to
fill a field is not a refusal. `refused_relations` names them so a client
can say WHY rather than showing an empty list that looks like "nothing is
near anything".

EVERY COUNT IS AN UNDERCOUNT AND MUST SAY SO

Measured against a `fasterrcnn_resnet50_fpn_v2` oracle over 14,128 real
frames (`docs/superpowers/research/2026-08-26-detector-oracle-and-the-
size-floor.md`), the shipped detector's recall is 0.306 for `person`,
0.497 for `cell phone`, 0.209 for `tv`, and it is effectively blind below
~2% of frame area (recall 0.000 under 1%). Because the oracle shares COCO
training data with the shipped model, 0.306 is an UPPER BOUND.

An undercount published without that disclosure looks exactly like a quiet
room, which is why `count_is_lower_bound` and `count_limitations` are
required fields rather than documentation.

EVERY BOOLEAN IS WRAPPED IN `bool()`

`bool` subclasses `int` in Python. A `registered: 1` already shipped once
in this repository and would fail every Swift `as? Bool` decode.
"""

from tower.results.contracts import SCENE_LIVE_CONTRACT, TIME_BASIS
from tower.scene.detect import CLASSES_OF_INTEREST
from tower.scene.live import (
    STATE_FAILED,
    STATE_PAUSED,
    STATE_RUNNING,
    STATE_STARTING,
    STATE_STOPPED,
)
from tower.scene.records import FACING_UNKNOWN
from tower.scene.state import REFUSED_RELATIONSHIPS, describe_position

# The three sentences above, as values a decoder can switch on.
SCENE_CLAIM = "visible-now-not-a-record"
IDENTITY_SCOPE = "anonymous-and-unpublished"
ABSENCE_MEANING = "not-visible-to-this-cartridge"
PERSISTENCE = "none"
FRAME_OF_REFERENCE = "camera"
COUNT_BASIS = "confirmed-tracks"

# Fixed arity. The universe of labels that can ever appear in `counts` --
# which is what keeps the payload bounded without a truncation rule, and
# what lets a client tell "looked for and not seen" from "never looked
# for". Sorted so the payload is stable and its revision hash does not
# move because a set iterated differently.
REPORTED_CLASSES = tuple(sorted(CLASSES_OF_INTEREST))

# `person` is excluded from `where`, and the exclusion is the point.
POSITION_EXCLUDED_LABELS = ("person",)

COUNT_LIMITATIONS = (
    {
        "limitation": "size-floor",
        "detail": (
            "the detector is effectively blind below ~2% of frame area: "
            "recall 0.000 under 1% and 0.009 at 1-2%, measured over 14,128 "
            "real frames against a fasterrcnn_resnet50_fpn_v2 oracle"
        ),
    },
    {
        "limitation": "recall",
        "detail": (
            "class recall against the same oracle is 0.306 for person, "
            "0.497 for cell phone and 0.209 for tv. The oracle shares COCO "
            "training data with the shipped model, so these are upper "
            "bounds, not estimates"
        ),
    },
    {
        "limitation": "field-of-view",
        "detail": (
            "a count is about the camera's forward cone at this instant, "
            "never about the room. Most of a room is behind the wearer"
        ),
    },
)

# Why `relations` is null, as a value rather than a silence.
RELATIONS_ABSENT_REASON = (
    "this cartridge asserts no relations on the wire. The two it can "
    "compute from 2-D boxes -- left_of and higher_in_view -- are camera-"
    "relative and change when the wearer turns their head, and every "
    "relation worth having needs depth that survives motion, which was "
    "measured and refused. See refused_relations"
)

# The lifecycle vocabulary, published so a client can pin it. A value
# outside this set is a value the phone decodes into nothing.
LIFECYCLE_STATES = (
    STATE_STOPPED,
    STATE_STARTING,
    STATE_RUNNING,
    STATE_PAUSED,
    STATE_FAILED,
)

# Fields whose value advances without anything having happened, or whose
# advance is not news about the SCENE. Excluded from the change revision
# so a client can tell new data from repeated data -- the same rule
# `world_builder.py: VOLATILE_PATHS` applies to `mapping_seconds`.
#
# `frames_observed` is in here and that deserves a sentence: a frame
# having been processed is not the same event as the scene having changed,
# and including it would make every single poll look like news and defeat
# coalescing entirely -- which is the one thing `IOS-to-Tower.md` 4.8 asks
# this cartridge for by name.
VOLATILE_PATHS = (
    "observed_at",
    "staleness_seconds",
    "frames_offered",
    "frames_observed",
    "frames_skipped",
    "frames_dropped_not_running",
    "decode_failures",
    "lifecycle.started_at",
    "lifecycle.ready_at",
    "lifecycle.loading_seconds",
    "people.oldest_estimate_seconds",
)

# The states in which the scene below is being refreshed. `paused` is
# deliberately not one of them: a paused session's counts are the last
# thing it saw, not what is there now.
_CURRENT_STATES = (STATE_RUNNING,)


def _side_counts(state) -> dict:
    """Per-label side counts, for everything that is not a person.

    Three fixed keys per label, so the block is bounded by the class list
    and cannot grow with what is in the room.

    `describe_position` returns `side: "unknown"` when the frame size was
    never learned, and that lands in its own bucket rather than being
    folded into `centre` -- a scene whose frame size is unknown has not
    placed anything in the middle of the view, it has placed nothing.
    """
    where: dict = {}
    for track in state.tracks:
        if track.label in POSITION_EXCLUDED_LABELS:
            continue
        side = describe_position(track, state.frame_width, state.frame_height)["side"]
        bucket = where.setdefault(
            track.label, {"left": 0, "centre": 0, "right": 0, "unknown": 0}
        )
        bucket[side] = bucket.get(side, 0) + 1
    return where


def _people_block(state) -> dict:
    """People, as a count and an aggregate -- never as a list.

    `may_include_wearer` and `validated` are not hedging. Every `person`
    box in this platform's only real corpus is the wearer's own torso
    (median box bottom edge 0.981, 59% touching the frame edge), and no
    bystander footage exists on this host. An unqualified count would
    overclaim, and the overclaim would be invisible.

    `facing_wearer` is `null` -- with a reason -- whenever orientation
    never produced an estimate. It is never 0. Zero is an answer and
    "never measured" is not, and this is the one field on this payload
    where the difference is most likely to be mistaken.
    """
    people = state.of_class("person")
    if state.orientation_enabled:
        facing = len(state.facing_wearer())
        reason = None
        ages = [
            track.facing.age_seconds
            for track in people
            if track.facing.age_seconds is not None
        ]
        oldest = max(ages) if ages else None
        unknown = sum(1 for track in people if track.facing.state == FACING_UNKNOWN)
    else:
        facing = None
        reason = (
            "coarse orientation has never produced an estimate on this "
            "session -- either no pose estimator is configured, or the "
            "model has not once succeeded. Reporting 0 would be an "
            "observation gap presented as an observation of absence"
        )
        oldest = None
        unknown = None
    return {
        "count": len(people),
        # A category, never an identity. There is no list here, no handle,
        # and nothing a client could join across two of these payloads.
        "may_include_wearer": True,
        "validated": False,
        "facing_wearer": facing,
        "facing_answered": bool(facing is not None),
        "facing_unavailable_reason": reason,
        "facing_unknown": unknown,
        "oldest_estimate_seconds": oldest,
        # The wording is part of the contract. `IOS-to-Tower.md` 4.2: this
        # is body/head orientation relative to the camera, it is NOT gaze,
        # and there is no eye tracking on the target glasses.
        "facing_note": (
            "coarse head and body orientation relative to the camera. "
            "Render as 'facing your direction'; there is no eye tracking "
            "on this platform, so it cannot establish what anyone was "
            "looking at or whether they noticed the wearer"
        ),
    }


def _lifecycle_block(status: dict) -> dict:
    state = status["state"]
    return {
        "state": state,
        "states": list(LIFECYCLE_STATES),
        # Session-scoped and meaningless afterwards, exactly like the
        # track ids it stands in for. Published so a client can tell that
        # two payloads came from two different tracking sessions and must
        # not be compared -- which is the ONLY joining this cartridge
        # wants a client to be able to do.
        "session_id": status["session_id"],
        "scene_is_current": bool(state in _CURRENT_STATES),
        "failure_reason": status["failure_reason"],
        "started_at": status["started_at"],
        "ready_at": status["ready_at"],
        "loading_seconds": status["loading_seconds"],
        "load_overdue": bool(status["load_overdue"]),
        "load_overdue_after_seconds": status["load_overdue_after_seconds"],
    }


def _empty_scene_reason(status: dict) -> str:
    """Why there are no counts, in the client's own vocabulary.

    Four different silences, and a client that flattened them would show
    an empty room for all four. Only one of them means an empty room, and
    it is not in this function -- a running session that has observed a
    frame and found nothing returns counts, all zero.
    """
    state = status["state"]
    if state == STATE_STOPPED:
        return (
            "this session is stopped. Nothing is being observed, and the "
            "last scene was discarded rather than kept: a scene held past "
            "the end of a session is a claim about a room the wearer has "
            "left"
        )
    if state == STATE_STARTING:
        return (
            "the detector is still loading. This is not an empty room; it "
            "is a Tower that has not looked yet"
        )
    if state == STATE_FAILED:
        return status["failure_reason"] or "the session failed"
    return (
        "the session is running but has not finished observing a frame "
        "yet. No frame has been offered, or the first is still in flight"
    )


def live_payload(status: dict, state) -> dict:
    """The whole payload, from a session status and its latest scene.

    `state` may be None, and the four ways that happens are kept apart by
    `scene_unavailable_reason` rather than collapsed into an empty room.

    Every block is present in both cases with the SAME KEYS, because a
    strict decoder that saw `counts` appear and disappear would have to
    treat the field as optional and would lose the ability to distinguish
    "zero of these" from "this Tower did not say".
    """
    lifecycle = _lifecycle_block(status)
    payload = {
        "claim": SCENE_CLAIM,
        "identity": IDENTITY_SCOPE,
        "absence_means": ABSENCE_MEANING,
        "persistence": PERSISTENCE,
        "frame_of_reference": FRAME_OF_REFERENCE,
        "time_basis": TIME_BASIS,
        "lifecycle": lifecycle,
        "observed_at": status["observed_at"],
        "staleness_seconds": status["staleness_seconds"],
        "frames_offered": status["frames_offered"],
        "frames_observed": status["frames_observed"],
        "frames_skipped": status["frames_skipped"],
        "frames_dropped_not_running": status["frames_dropped_not_running"],
        "decode_failures": status["decode_failures"],
        "detector": status["detector"],
        "reported_classes": list(REPORTED_CLASSES),
        "count_basis": COUNT_BASIS,
        "count_is_lower_bound": True,
        "count_limitations": [dict(entry) for entry in COUNT_LIMITATIONS],
        # Null and unexpressible. There is no key below this one that
        # could hold a relation, which is what makes the refusal a
        # refusal rather than an omission somebody has to keep making.
        "relations": None,
        "relations_absent_reason": RELATIONS_ABSENT_REASON,
        "refused_relations": [
            {"relation": name, "reason": reason}
            for name, reason in sorted(REFUSED_RELATIONSHIPS.items())
        ],
        "where_excludes": list(POSITION_EXCLUDED_LABELS),
        "where_excludes_reason": (
            "a per-person position, sampled repeatedly, is a movement "
            "trace. This cartridge keeps none and will not hand a client "
            "the parts to assemble one"
        ),
    }

    if state is None:
        payload["scene_available"] = False
        payload["scene_unavailable_reason"] = _empty_scene_reason(status)
        payload["score_threshold"] = None
        payload["counts"] = None
        payload["where"] = None
        payload["people"] = None
        return payload

    payload["scene_available"] = True
    payload["scene_unavailable_reason"] = None
    payload["score_threshold"] = state.score_threshold
    # Fixed arity: every reported class, present with 0 rather than
    # omitted. An absent key is a version skew; a zero is an answer -- and
    # `absence_means` at the top of the payload says what that zero is an
    # answer to.
    payload["counts"] = {
        label: int(state.counts.get(label, 0)) for label in REPORTED_CLASSES
    }
    payload["where"] = _side_counts(state)
    payload["people"] = _people_block(state)
    return payload
