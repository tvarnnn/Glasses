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
    # Whether Scene Understanding may run at all on this Tower.
    #
    # OFF by default, and the default is a resource decision rather than
    # caution -- MEASURED, and the measurement is worse than the estimate
    # that first stood here.
    #
    # `scripts/cartridge_live_benchmark.py`, 829 real corpus frames fed at
    # the delivered 12.0 fps, CPU: the session consumed **4.1 cores'
    # worth of CPU** and still skipped 17.6% of frames. The 32.9 ms
    # per-detection figure in `tower/scene/detect.py` is not wrong; it
    # excludes JPEG decode, and it was taken on an idle host. A live
    # session on a busy one is a different number and this is it.
    #
    # See `scene_torch_threads` below: capping torch's pool to 2 cut that
    # to 1.03 cores at IDENTICAL throughput, which is the single most
    # valuable thing an operator can do here.
    #
    # Off means `/cartridges` declares the contract and reports it
    # unavailable, naming this variable. It never means the Tower is
    # silent about the cartridge.
    scene_understanding: bool = False
    # Which device the scene detector loads onto.
    #
    # "cpu" by default, unlike TOWER_CV_DEVICE's "auto", and measured
    # rather than assumed: ssdlite320 is 30.4 ms on CUDA against 32.9 ms
    # on CPU -- an 8% gain, because MobileNetV3 at an internal 320 px is
    # bound by kernel-launch overhead and not arithmetic. Taking a GPU
    # for 2.5 ms a frame while World Builder wants it would be a bad
    # trade made silently.
    scene_device: str = "cpu"
    # Whether the session estimates coarse facing.
    #
    # OFF by default, and this one is not close. The pose model is 956.4
    # ms per call on CPU -- 11.5x the delivered frame interval -- against
    # 43.4 ms on CUDA. It is also entirely unvalidated: no ground truth
    # for facing exists on this host. Enabling it on a CPU Tower would
    # convert the cartridge from "cheap and honest" into "wrong and
    # slow".
    scene_orientation: bool = False
    # Cap torch's intra-op thread pool, or 0 to leave its default.
    #
    # PROCESS-GLOBAL. `torch.set_num_threads` has no per-model scope, so
    # this affects the Experimental CV Lab too. That is the only reason
    # it is not on by default, because the measurement is one-sided:
    #
    #   torch default (20 threads on this host)   4.12 cores, 9.85 fps
    #   capped at 2                               1.03 cores, 9.88 fps
    #
    # Four times the CPU for no throughput at all, which is exactly what
    # `docs/superpowers/research/2026-08-26-scene-understanding-
    # measurements.md` predicts: ssdlite320 at an internal 320 px is
    # bound by kernel-launch overhead, not arithmetic, so more threads
    # buy nothing and cost a core each.
    #
    # An operator on a machine that is not a 20-core workstation should
    # set this. A startup log line says so when it is unset.
    scene_torch_threads: int = 0
    # Whether `stream_start` starts a scene session and `stream_stop`
    # ends it.
    #
    # ON by default, and the default is what makes this cartridge
    # reachable from a phone at all. `IOS-to-Tower.md` 6.2: opening a
    # cartridge on the phone sends NOTHING, and a test asserts the wire
    # stays silent -- so a session that only an HTTP POST could start is
    # a contract a phone can subscribe to and will watch report "not
    # observing" forever. That is not a safety property; it is a dead
    # product path, and an adversarial review found it as one.
    #
    # Enabling the cartridge is already the opt-in. This does not widen
    # what a Tower may do, only when it does it.
    scene_autostart: bool = True
    # Where a document session writes what it read, and where the
    # document routes read it back.
    #
    # Named `document_root`, not `document_memory_root`, and the name is
    # load-bearing rather than a preference:
    # `test_document_memory_is_not_registered_as_a_production_module`
    # asserts the substring "document_memory" appears nowhere in the raw
    # text of `main.py`, which this value has to reach. Object Memory
    # solved the same problem the same way with `observation_root`.
    #
    # None means the document routes answer 404 and `/cartridges` reports
    # the cartridge unavailable -- a claim about configuration, never
    # about what was ever read.
    document_root: str | None = None
    # Whether a live document session may attach to the stream.
    #
    # OFF by default and separately from the root, because the two
    # answer different questions. A root with capture off is a Tower that
    # will serve a library recorded elsewhere and record nothing itself,
    # which is the right posture for a machine reprocessing captures
    # offline -- and the same escape hatch `world_autobuild` provides.
    document_capture: bool = False
    # Whether `stream_start` starts a DOCUMENT session.
    #
    # OFF by default, unlike Scene Understanding's, and the asymmetry is
    # the difference between the two cartridges: this one WRITES. A
    # session that persists what a wearer read gets an explicit start,
    # which is the standard 06-PRIVACY-DATA.md holds the dataset recorder
    # to -- "arming is not recording".
    #
    # The cost is smaller than it looks: the half of this cartridge a
    # phone reaches is the library, over HTTP, and that works whether or
    # not anything is currently recording.
    document_autostart: bool = False
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
        scene_understanding=_flag("TOWER_SCENE_UNDERSTANDING", default=False),
        scene_device=os.environ.get("TOWER_SCENE_DEVICE", "cpu"),
        scene_orientation=_flag("TOWER_SCENE_ORIENTATION", default=False),
        scene_torch_threads=_non_negative_int(
            os.environ.get("TOWER_SCENE_TORCH_THREADS"), default=0
        ),
        scene_autostart=_flag("TOWER_SCENE_AUTOSTART", default=True),
        document_root=_optional_path(os.environ.get("TOWER_DOCUMENT_ROOT")),
        document_capture=_flag("TOWER_DOCUMENT_CAPTURE", default=False),
        document_autostart=_flag("TOWER_DOCUMENT_AUTOSTART", default=False),
    )


def _flag(name: str, *, default: bool) -> bool:
    """An on/off environment variable, read the same way every time.

    `world_autobuild` parses its own inline and defaults ON; these three
    default OFF, and each says why at its field. The shared helper exists
    so a fourth flag cannot arrive with a fifth spelling of "true" -- the
    accepted set is one list, here.
    """
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


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
