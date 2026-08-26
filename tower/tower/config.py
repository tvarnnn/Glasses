import os
from dataclasses import dataclass


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
    # Where object_memory_session.py wrote its observations. Read-only to
    # the web process, and read by one HTTP route that cannot delete and
    # cannot widen the retention window it was written under.
    #
    # None means the route answers 404 -- "this Tower serves no object
    # memory", which is a claim about configuration and not about what
    # was ever observed. Unset by default and deliberately so: a memory of
    # what a wearer's camera saw does not go on the network because a
    # process happened to start in a directory that has one.
    observation_root: str | None = None
    # Keyframes between mid-walk rebuilds in the attached builder.
    #
    # NOT the script's own default, which is 0 -- "build once, at the
    # end". That default is correct for a batch reprocess and wrong for a
    # live walk: it is why the 2026-08-24 test showed a climbing keyframe
    # count with no geometry at all until the capture closed, and then
    # every figure appearing at once.
    world_rebuild_every: int = 4


def get_settings() -> Settings:
    return Settings(
        host=os.environ.get("TOWER_HOST", "0.0.0.0"),
        port=int(os.environ.get("TOWER_PORT", "8000")),
        dev_mode=os.environ.get("TOWER_DEV_MODE", "true").lower() in ("1", "true", "yes"),
        cv_experiment=os.environ.get("TOWER_CV_EXPERIMENT", "baseline"),
        cv_device=os.environ.get("TOWER_CV_DEVICE", "auto"),
        capture_root=_optional_path(os.environ.get("TOWER_CAPTURE_ROOT")),
        world_root=_optional_path(os.environ.get("TOWER_WORLD_ROOT")),
        observation_root=_optional_path(
            os.environ.get("TOWER_OBSERVATION_ROOT")
        ),
        world_autobuild=os.environ.get("TOWER_WORLD_AUTOBUILD", "true").lower()
        in ("1", "true", "yes"),
        world_rebuild_every=_non_negative_int(
            os.environ.get("TOWER_WORLD_REBUILD_EVERY"), default=4
        ),
    )


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
