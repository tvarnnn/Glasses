import os
from dataclasses import dataclass
from pathlib import Path

# The tower project root -- the directory holding `scripts/`, `models/`
# and, by default, `data/`. Resolved from this file rather than from the
# working directory: a process started with the wrong CWD would otherwise
# resolve a relative default somewhere nobody chose, and the failure that
# produces is silent. `main.py` imports this rather than computing its
# own, because two copies of a resolved root are two answers to the same
# question.
TOWER_ROOT = Path(__file__).resolve().parent.parent

# Where a producer writes its observations and where the read routes look
# for them, when nobody says otherwise. ONE constant, because the
# alternative shipped and was measured: on 2026-08-26 the producer
# defaulted to `data/object_memory`, the web process defaulted to nothing
# at all, and a real 2,203-frame walk was remembered into a store that
# every HTTP request answered 404 about until an operator set an
# environment variable by hand. Two defaults for one directory is not a
# configuration choice; it is a bug with a settings file in front of it.
#
# Absolute, unlike `capture_root`'s relative default: this value is
# handed to a CHILD PROCESS as an argv, and a relative path that resolves
# differently in the parent and the child is the same disagreement in a
# harder-to-see form.
DEFAULT_OBSERVATION_ROOT = str(TOWER_ROOT / "data" / "object_memory")


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    dev_mode: bool
    cv_experiment: str
    cv_device: str
    # None means the dataset recorder is not armed at all. A path arms
    # it -- which still records nothing until a stream_start arrives.
    # Defaulted, unlike its neighbours: "off" is the only safe value for a
    # raw-imagery recorder, so a caller that forgets it gets no recording
    # rather than an unconfigured one.
    capture_root: str | None = None
    # Where world_build_session.py writes its worlds. Read-only to the web
    # process: it never builds, it only reports what another process has
    # already persisted. None means the result channel declares World
    # Builder's contract but reports it unavailable, which is a different
    # claim from "this Tower has no such cartridge".
    world_root: str | None = None
    # Whether a capture automatically gets a builder process attached to
    # it. On by default WHEN a world root is set, because the alternative
    # is what the first physical test did: record ten captures and build
    # a world from the one a human attached a follower to by hand.
    #
    # Off is a real configuration, not a debug flag. Reprocessing a
    # recorded capture offline wants the result channel reporting worlds
    # while nothing new is being built, and this is the escape hatch if
    # auto-attach ever misbehaves in the field.
    world_autobuild: bool = True
    # Where the observation producer writes and the read routes look.
    # Read-only to the web process, which cannot delete and cannot widen
    # the retention window the records were written under.
    #
    # None means the route answers 404 -- "this Tower serves no object
    # memory", a claim about configuration and not about what was ever
    # observed. It is now reachable ONLY by switching the cartridge off,
    # never by forgetting to set a path.
    #
    # THE DEFAULT REVERSED, AND THE REASON MATTERS.
    #
    # This used to default to None on the grounds that "a memory of what
    # a wearer's camera saw does not go on the network because a process
    # happened to start in a directory that has one". The physical test
    # on 2026-08-26 showed what that actually bought: the producer wrote
    # 64 observations to `data/object_memory` regardless, and the only
    # thing the unset default prevented was the WEARER reading their own
    # memory back. Data existed, nothing served it, and no log line said
    # why. A default that hides data from its owner while still storing
    # it protects nobody.
    #
    # So the switch moved to where the decision actually is:
    # `observation_enabled` governs whether this Tower produces or serves
    # object memory AT ALL, and when it is off, nothing is written and
    # nothing is served. Producing without serving is no longer
    # reachable by accident.
    observation_root: str | None = None
    # Whether this Tower runs the object-memory cartridge at all.
    #
    # On by default, and that is a smaller claim than it looks: an armed
    # cartridge records nothing until a wearer starts a session, exactly
    # as an armed capture recorder writes no byte until `stream_start`.
    # Off means no producer can be attached, no route answers, and
    # `observation_root` is None.
    observation_enabled: bool = True
    # Which device the attached observation producer runs its detector on.
    #
    # "cpu" by default, and the reason is CONTENTION rather than speed --
    # a correction, because the first version of this comment claimed
    # CUDA was slower and cited a figure that was not a measurement.
    #
    # It said "a CUDA pass over the whole corpus measured a WORSE 75
    # ms/frame mean". 75.0 was the running average printed at frame
    # 10,000 of a run competing with a test suite; the run's actual mean
    # was 87.8, and neither number describes a quiet host.
    #
    # Re-measured with no other work of ours running, replaying the same
    # 2,203-frame capture: CPU **40.6, 43.4, 45.1 and 46.9 ms/frame**
    # across four consecutive runs, against CUDA at 48.8. An independent
    # audit on the same host measured the ordering the OTHER WAY (CUDA
    # 43.9 against CPU 51.0). The spread within one device exceeds the
    # gap between them, so the honest statement is that this detector
    # costs about the same either way -- the work is single-frame
    # preprocessing and transfer, not the 320x320 forward pass, and
    # neither device is doing much of it.
    #
    # THIS HOST IS NOT QUIET. It carries several autonomous agent lanes
    # at once, and two more appeared in `git worktree list` while these
    # numbers were being taken. Read every latency figure in this
    # cartridge as a range.
    #
    # What is NOT within noise is what else wants the GPU. Object Memory
    # does not own this Tower: World Builder runs on it, the depth
    # experiment runs on it, and this cartridge's own verifier takes
    # 620 MB of VRAM when it is enabled. A producer that follows a
    # capture has no latency requirement at all -- it may fall behind and
    # catch up -- so it is the one stage that should stay off the
    # contended device.
    observation_device: str = "cpu"
    # The retention window the producer WRITES UNDER, recorded in the
    # store manifest at first append. Every later read clamps to
    # min(persisted, requested), so this is the promise and a reader can
    # only ever narrow it.
    observation_retention_days: float = 30.0
    # What, if anything, may second-guess a detector label before a class
    # the detector cannot be trusted to name is written.
    #
    # "none" is the default and is a measurement rather than caution.
    # Reading the crops the shipped detector produced over the real
    # corpus found a ceiling fan detected as `airplane` at 0.99 and a
    # laptop keyboard as `remote` at 0.87, so a Tower with nothing to
    # check those labels records neither -- which is exactly the
    # behaviour that was physically validated.
    #
    # A NAME rather than a boolean, because the answer will eventually be
    # a model identifier and a boolean cannot become one. It is handed to
    # the producer's argv AND used by the read routes to say which
    # classes this Tower records, so the two cannot disagree about it.
    observation_verifier: str = "none"
    # Where the verifier runs, when there is one.
    #
    # CUDA by default even though the DETECTOR defaults to CPU, and the
    # asymmetry is the measurement: the detector costs about the same on
    # either device (within noise, see above), while the verifier
    # measured 126 ms a crop on this GPU against 2,473 ms on this CPU --
    # a factor of nineteen. Splitting the two stages across devices is
    # what keeps a 2.5-second burst off the cores the detector is using,
    # and it costs 620 MB of VRAM on a card that has twelve.
    #
    # A host with no CUDA does not need this set: the verifier reports
    # the downgrade and runs on CPU rather than failing.
    observation_verifier_device: str = "cuda"
    # Keyframes between mid-walk rebuilds in the attached builder.
    #
    # NOT the script's own default, which is 0 -- "build once, at the
    # end". That default is correct for a batch reprocess and wrong for a
    # live walk: it is why the 2026-08-24 test showed a climbing keyframe
    # count with no geometry at all until the capture closed, and then
    # every figure appearing at once.
    world_rebuild_every: int = 4


def get_settings() -> Settings:
    observation_enabled = _flag("TOWER_OBSERVATION_ENABLED", default=True)
    return Settings(
        host=os.environ.get("TOWER_HOST", "0.0.0.0"),
        port=int(os.environ.get("TOWER_PORT", "8000")),
        dev_mode=os.environ.get("TOWER_DEV_MODE", "true").lower() in ("1", "true", "yes"),
        cv_experiment=os.environ.get("TOWER_CV_EXPERIMENT", "baseline"),
        cv_device=os.environ.get("TOWER_CV_DEVICE", "auto"),
        capture_root=_optional_path(os.environ.get("TOWER_CAPTURE_ROOT")),
        world_root=_optional_path(os.environ.get("TOWER_WORLD_ROOT")),
        observation_root=_observation_root(observation_enabled),
        observation_enabled=observation_enabled,
        observation_device=_device(
            os.environ.get("TOWER_OBSERVATION_DEVICE"), default="cpu"
        ),
        observation_retention_days=_non_negative_float(
            os.environ.get("TOWER_OBSERVATION_RETENTION_DAYS"), default=30.0
        ),
        observation_verifier=_verifier(
            os.environ.get("TOWER_OBSERVATION_VERIFIER")
        ),
        observation_verifier_device=_device(
            os.environ.get("TOWER_OBSERVATION_VERIFIER_DEVICE"), default="cuda"
        ),
        world_autobuild=os.environ.get("TOWER_WORLD_AUTOBUILD", "true").lower()
        in ("1", "true", "yes"),
        world_rebuild_every=_non_negative_int(
            os.environ.get("TOWER_WORLD_REBUILD_EVERY"), default=4
        ),
    )


def _observation_root(enabled: bool) -> str | None:
    """The one path both the producer and the read routes will use.

    An explicit `TOWER_OBSERVATION_ROOT` still wins, because an operator
    who chose a directory has said something the default cannot know. The
    difference from before is that NOT choosing one is no longer a way to
    end up with two different answers.

    Switching the cartridge off wins over both: a Tower told not to run
    object memory does not get a root because somebody left a variable
    set from last week.
    """
    if not enabled:
        return None
    return _optional_path(os.environ.get("TOWER_OBSERVATION_ROOT")) or (
        DEFAULT_OBSERVATION_ROOT
    )


# Every verifier this build can construct.
#
# Named HERE, in settings, rather than only in the producer script, and
# that duplication is deliberate -- it is the smaller of two evils. The
# alternative was for shared config to import the cartridge, which the
# boundary forbids. What must not happen is what did: `config.py`
# accepted any string and treated "not none" as "a verifier exists", so
# `TOWER_OBSERVATION_VERIFIER=owvl2` (a transposition) told the read
# routes that fourteen classes were recordable AND handed the producer a
# name it refuses, killing it at spawn. A Tower advertising twelve
# classes it had just made unrecordable.
#
# `scripts/object_memory_session.py` still validates its own argument;
# these two lists agreeing is checked by
# `test_the_settings_and_the_producer_agree_about_verifier_names`.
KNOWN_VERIFIERS = ("none", "owlv2")


def _verifier(value: str | None) -> str:
    """Which verifier to run, or "none". An unknown name falls back.

    Falls back rather than raising, for the same reason
    `_non_negative_int` does: a typo in an optional variable must not
    take a Tower down for a cartridge it may not even be running. It is
    logged at startup, so the typo is visible rather than silent -- and
    the fallback is the SAFE direction, because "none" narrows what the
    routes claim rather than widening it.
    """
    if value is None or not value.strip():
        return "none"
    name = value.strip().lower()
    return name if name in KNOWN_VERIFIERS else "none"


def _device(value: str | None, *, default: str = "cpu") -> str:
    """"cpu" or "cuda". Anything else falls back rather than failing late.

    A typo here would otherwise reach a child process as an argv, be
    rejected by `torch.device`, and surface as a producer that exits
    immediately -- visible only as a warning in the Tower log, hours into
    a walk that remembered nothing. The fallback is the measured default.
    """
    if value is None:
        return default
    normalised = value.strip().lower()
    if normalised in ("cpu", "cuda"):
        return normalised
    return default


def _non_negative_float(value: str | None, *, default: float) -> float:
    """A retention window, or the default. Never negative.

    `ObservationStore` raises on a negative window, and it is right to:
    a negative retention has no meaning. But raising at STARTUP over a
    typo in an optional variable would take a Tower down for a cartridge
    it may not even be running, so a bad value falls back and the
    effective figure is logged.
    """
    if value is None or not value.strip():
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return parsed if parsed >= 0 else default


def _flag(name: str, *, default: bool) -> bool:
    """A boolean environment variable, with a default that survives a blank.

    `TOWER_DEV_MODE` and `TOWER_WORLD_AUTOBUILD` spell a similar test
    inline and are deliberately left alone: both default to true through
    `os.environ.get(name, "true")`, which makes an EXPLICITLY BLANK value
    false. That is the opposite of what a blank means everywhere else in
    this file -- `_optional_path` reads a blank as "unset, use the
    default" -- and quietly changing two existing settings to fix an
    inconsistency is not this change's business. New flags get the
    consistent reading; the old two keep theirs until somebody decides.
    """
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in ("1", "true", "yes")


def _non_negative_int(value: str | None, *, default: int) -> int:
    """A malformed cadence falls back rather than taking the Tower down.

    Unlike TOWER_PORT, which raises at import on garbage, this one has a
    safe answer: the default. A typo in a rebuild interval must not stop
    a Tower from serving frames, and the value is reported at startup so
    the typo is still visible.
    """
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed >= 0 else default


def _optional_path(value: str | None) -> str | None:
    """Blank means unset. A shell exporting an empty variable is saying
    "no", and treating that as the current working directory would arm a
    raw-imagery recorder somewhere nobody chose.
    """
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
