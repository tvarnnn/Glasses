"""Identifiers, states and refusal reasons for the CV Lab wire surface.

Kept in one file for the same reason `tower/results/contracts.py` is:
these are the strings a phone switches on, and a string a phone switches
on is not a detail of the module that happens to emit it.

Every identifier here is **opaque and compared for equality only**, the
rule `IOS-to-Tower.md` 0.1 sets for the whole platform. Dated rather than
numbered so that two of them are visibly different without inviting
anyone to compute which is greater. Changing one is a WIRE BREAK: iOS
will report "update the app" and stop decoding, which is the intended
behaviour. Change one only when a payload's MEANING changes in a way an
existing decoder would get wrong -- adding an optional field an older
decoder ignores is not that.
"""

# The cartridge name. Must equal `tower.results.contracts
# .CARTRIDGE_EXPERIMENTAL_CV`; a test asserts it rather than importing it,
# because the result channel core is deliberately cartridge-blind and this
# module must not become the thing that makes it otherwise.
CARTRIDGE = "experimental_cv"

# The one result type. The Lab publishes one document that answers every
# question about it -- what can run, what is running, and what it found --
# rather than a `catalog` type and a `run` type that could disagree.
RESULT_TYPE_STATUS = "status"

# The status document, on the result channel, over `GET /cv-lab`, and as
# the reply to `cv_lab_status`. All three are the same bytes.
STATUS_CONTRACT = "experimental_cv.status/2026-08-27"

# The provenance block added to every `frame_result`. Versioned SEPARATELY
# from the status document because it travels on a different transport at
# a different rate, and a change to one has no bearing on the other.
FRAME_RESULT_CONTRACT = "experimental_cv.frame_result/2026-08-27"

# The command vocabulary: start/pause/resume/stop and their replies.
# Versioned separately again -- a client may implement the read-only half
# and never send a command, which is exactly what a Release iOS build with
# no camera should do.
CONTROL_CONTRACT = "experimental_cv.control/2026-08-27"

# Every timestamp the Lab emits. There is no capture timestamp anywhere on
# the wire (`tower/frames.py` carries no time field), so a Tower timestamp
# is when the TOWER saw something, never when the glasses did.
TIME_BASIS = "tower-receipt"


# -- lifecycle ---------------------------------------------------------
#
# Seven states, and the mapping onto iOS's `ExperimentalCVState` is in
# docs/contracts/EXPERIMENTAL-CV-LAB.md. They are NOT the module's states:
# `ModuleState` describes the one Lab slot in the container, and these
# describe what is in it. A module can be ACTIVE while the Lab is idle,
# and that is the normal state of a Tower nobody has asked for an
# experiment yet.

# The Lab cannot run anything at all -- the module failed, or nothing is
# registered. A Tower limitation, not a "wait a moment".
STATE_UNAVAILABLE = "unavailable"
# Nothing armed. A catalog is available and a start would be accepted.
STATE_IDLE = "idle"
# A start was accepted and the experiment is loading. Frames arriving now
# are refused, and counted.
STATE_STARTING = "starting"
# Processing frames.
STATE_RUNNING = "running"
# Armed and deliberately not processing. The experiment stays loaded, so
# a resume costs nothing -- which is the whole difference from `stopped`.
STATE_PAUSED = "paused"
# The last run ended. Its figures are final and still readable.
#
# Deliberately not "completed": a bench run does not complete, it is
# stopped by a person. iOS renders it as `.completed` because that is the
# case its state machine has; the Tower says what actually happened.
STATE_STOPPED = "stopped"
# The last start failed. `reason` says how, and another start may be
# sent -- which is the difference between a Lab failure and a module
# failure.
#
# Reached ONLY from a failed arm. A run that dies mid-frame -- an
# experiment raising something that is not a `FrameProcessingError` --
# does not land here: `ModuleContainer` marks the MODULE failed, which is
# terminal by design, and the Lab reports `unavailable` until the Tower
# restarts. That is a limitation of the shared module lifecycle rather
# than of the Lab, it is stated in the contract's Known Limitations, and
# an earlier version of this comment claimed the opposite.
STATE_FAILED = "failed"

LIFECYCLE_STATES = (
    STATE_UNAVAILABLE,
    STATE_IDLE,
    STATE_STARTING,
    STATE_RUNNING,
    STATE_PAUSED,
    STATE_STOPPED,
    STATE_FAILED,
)


# -- where a run came from ---------------------------------------------

# The Tower started this run itself at boot, from `TOWER_CV_EXPERIMENT`
# or its default. Reported so that "the Lab is running" never reads as
# "somebody asked for this".
ORIGIN_STARTUP_DEFAULT = "startup_default"
# A client sent `cv_lab_start`.
ORIGIN_CLIENT_REQUEST = "client_request"


# -- refusal reasons ---------------------------------------------------
#
# A closed set. A client switches on these, so adding one is a contract
# change. Every one of them means the request did NOT take effect --
# there is no partial application, and the reply carries the unchanged
# status so a client never has to guess what state it is now in.

# The request was not shaped like a request.
ERR_MALFORMED = "malformed_request"
# No experiment with that id is registered on this Tower. The reply
# carries `available` so the client can correct itself.
ERR_UNKNOWN_EXPERIMENT = "unknown_experiment"
# The experiment exists but this Tower cannot run it -- most often the
# optional [ml] extra is not installed.
ERR_EXPERIMENT_UNAVAILABLE = "experiment_unavailable"
# A start or stop is already in flight. Refused rather than queued: a
# queue would let two clients each believe they chose what is running.
ERR_LAB_BUSY = "lab_busy"
# The command does not apply from the current state (resume when idle,
# pause when stopped).
ERR_INVALID_STATE = "invalid_state"
# The command named a `run_id` that is not the current one. The run it
# meant to act on is already gone, and acting on the current one instead
# would be the wrong run stopped by the wrong person.
ERR_STALE_RUN = "stale_run"
# The Lab itself cannot serve anything -- see STATE_UNAVAILABLE.
# TERMINAL from a client's point of view: iOS renders it as
# `.unsupported`, which tells a person this Tower cannot do this rather
# than inviting them to try again.
ERR_LAB_UNAVAILABLE = "lab_unavailable"
# The Tower failed while answering, and the request did not take effect.
# Deliberately NOT `lab_unavailable`: a handler bug is transient and
# retryable, and reporting it as the terminal condition would tell a
# person to give up on a Tower that is working. The Tower does not know
# what went wrong -- if it did, this would be a different reason.
ERR_INTERNAL = "internal_error"
# There is deliberately NO `start_failed` refusal. An arm is
# asynchronous -- that is the whole reason a start returns immediately --
# so by the time a load fails the command has already been answered
# `accepted`, and a second reply to a reply is not a thing the wire has.
# The outcome arrives as STATE: `lifecycle.state` goes `failed` with a
# reason, pushed on the result channel or read with `cv_lab_status`. That
# is the shape iOS's own `run(_:)` already has, and the constant that
# used to sit here was declared, imported, and never emitted.

REFUSAL_REASONS = (
    ERR_MALFORMED,
    ERR_UNKNOWN_EXPERIMENT,
    ERR_EXPERIMENT_UNAVAILABLE,
    ERR_LAB_BUSY,
    ERR_INVALID_STATE,
    ERR_STALE_RUN,
    ERR_LAB_UNAVAILABLE,
    ERR_INTERNAL,
)


# -- why a frame was not processed -------------------------------------
#
# These reach the client as `frame_error.reason`, alongside the transport's
# own `invalid_frame` / `frame_skipped` / `module_unavailable`. They exist
# because "the Lab is paused" and "that frame was undecodable" are
# different facts and a person acts on them differently.

FRAME_REFUSED_IDLE = "cv_lab_idle"
FRAME_REFUSED_STARTING = "cv_lab_starting"
FRAME_REFUSED_PAUSED = "cv_lab_paused"
FRAME_REFUSED_STOPPED = "cv_lab_stopped"
FRAME_REFUSED_FAILED = "cv_lab_failed"
# A defensive default rather than a state a client will normally see:
# when the Lab is `unavailable` the module behind it is FAILED or
# UNLOADED, so `ModuleContainer.process` refuses the frame with
# `module_unavailable` before the Lab is reached at all. It stays because
# `process()` falls back to it for any state not in the map below, and a
# fallback that names the wrong thing is worse than one that names this.
FRAME_REFUSED_UNAVAILABLE = "cv_lab_unavailable"

FRAME_REFUSAL_REASONS = {
    STATE_IDLE: FRAME_REFUSED_IDLE,
    STATE_STARTING: FRAME_REFUSED_STARTING,
    STATE_PAUSED: FRAME_REFUSED_PAUSED,
    STATE_STOPPED: FRAME_REFUSED_STOPPED,
    STATE_FAILED: FRAME_REFUSED_FAILED,
    STATE_UNAVAILABLE: FRAME_REFUSED_UNAVAILABLE,
}


# -- bounds ------------------------------------------------------------

# How long after the last frame the Lab stops claiming it is receiving
# any. The current iOS sender forwards roughly 1-in-30 of a ~24 fps
# capture, which `tower/metrics.py` records as ~0.8 frames per second
# observed. Five seconds is therefore about four missed frames -- long
# enough never to flicker during normal streaming, short enough that
# "Start was pressed and nothing is arriving" shows up while a person is
# still standing there.
STREAM_IDLE_AFTER_S = 5.0

# The most metrics one run reports. Every registered experiment emits far
# fewer (the largest, `redaction_impact`, emits twelve), so this bounds a
# future experiment rather than truncating a present one -- and when it
# does truncate it says how many it dropped rather than quietly showing a
# shorter list.
MAX_REPORTED_METRICS = 16

# There is deliberately NO cap on how many metric names a run
# accumulates, because one is unreachable and an unreachable guard reads
# as care while providing none. A name enters the accumulator only if
# `classify_metric` recognises it, and that means only if the experiment
# DECLARED it in its own `METRIC_KINDS` -- a compile-time set, twelve
# entries at its largest. A name the experiment never declared is
# excluded and counted below instead. The bound is the declaration, and
# `test_the_accumulator_is_bounded_by_the_declared_metric_set` is what
# says so.

# The most distinct STAGE names one run will accumulate. Unlike the
# metric accumulator -- bounded by the experiment's own `METRIC_KINDS`
# declaration -- a stage name is whatever an experiment passed to
# `StageTimer.stage()`, with nothing declaring it in advance. An
# experiment naming a stage per frame grew this to 926,280 entries over
# 15,438 frames in a probe, which is exactly the unbounded store a run
# open "for as long as the Tower is up" must not have. Sixteen, because
# the most stages any registered experiment uses is four.
MAX_TRACKED_STAGES = 16

# The most unclassified metric names reported. An experiment emitting a
# metric it never classified is a bug caught by
# `test_every_metric_the_experiment_emits_is_classified`; this is what
# happens if one reaches production anyway, and it must not become an
# unbounded list of names a remote producer chose.
MAX_UNCLASSIFIED_REPORTED = 8
