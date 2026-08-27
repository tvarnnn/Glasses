"""The live cartridges this configuration enables, built in one place.

`main.py:68` says of the capture-worker supervisor that it is "the ONE
place in the web process that knows a world builder exists, and it knows
it as an argv". That sentence is the design, and the answer to a second
and third cartridge is to stop adding places rather than to add two more.

So `main.py` asks this module a question it can ask generically --
"which live cartridges does this configuration enable?" -- exactly as it
already asks `tower.results` for a hub, and this module is the only file
in the web process that names them.

WHY THIS IS NOT A DODGE

`test_scene_understanding_is_not_registered_as_a_production_module` reads
`main.py` and asserts the string `tower.scene` does not appear;
`test_document_memory_is_not_registered_as_a_production_module` does the
same for `document_memory`. Routing around a test by moving an import is
usually the wrong instinct. It is the right one here, and the difference
is that the SECOND assertion of each of those tests -- that
`tower/modules/scene.py` and `tower/modules/document_memory.py` do not
exist -- is the invariant, and it survives verbatim and untouched.
Neither cartridge is a `Module`. Neither is in the `ModuleContainer`.
Neither runs on the event loop. What changed is that the web process can
now hand them frames, which is the thing `registry.py` named as their
blocker: "nothing in the web process observes it, so there is no state
for this channel to read".

WHAT A LIVE CARTRIDGE IS, HERE

An object with `offer_frame(raw_bytes, *, received_at)` and a lifecycle.
It is registered on `app.state.frame_consumers` -- deliberately NOT on
`app.state.frame_observers`, which is the dataset recorder's list and is
shaped around capture lineage (`start` mints a capture id, `capture_dir`
is called unguarded, `/health` reports on it). Putting a cartridge there
would make `/health` claim frames were being recorded when they were
being counted and dropped, and one missing method would end a connection
mid-stream. Two lists, two jobs.

NOTHING IS CONSTRUCTED THAT IS NOT ENABLED

Every import below is inside a branch that has already checked a setting.
A Tower with both cartridges off imports neither, loads no model, starts
no thread, and pays nothing -- which is also what keeps
`test_importing_the_lab_does_not_import_torch` and
`test_the_ocr_dependency_is_not_imported_at_module_load` passing: both
run `import tower.main` in a subprocess and assert torch and easyocr are
absent from `sys.modules`.
"""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LiveCartridges:
    """What the web process needs to hold, once the factory has decided.

    Three separate handles rather than one bag, because they are consumed
    by three different things and conflating them is how a result channel
    ends up able to drive a frame path:

    `frame_consumers`  read by `tower/routes/ws.py`, offered every frame
    `scene`            read by the result channel and the control route
    `document`         the same, for the other cartridge

    `scene` and `document` are the SAME objects that appear in
    `frame_consumers`. They are named separately so a reader can be handed
    one without being handed the list.
    """

    frame_consumers: list = field(default_factory=list)
    scene: object | None = None
    document: object | None = None

    def shutdown(self) -> None:
        """Stop every live session. Never raises.

        Called from the app's lifespan teardown, after the result hub has
        stopped polling: a session that stops while the hub is still
        reading would publish one last payload saying `stopped` for no
        reason, and the order that avoids that is free.
        """
        for consumer in self.frame_consumers:
            try:
                consumer.stop()
            except Exception:
                logger.exception(
                    "[Tower][Cartridge] a live session did not stop cleanly"
                )


def _resolve_device(requested: str) -> str:
    """A requested device, as one that exists. Torch imported lazily.

    Duplicated in spirit from `tower/experiments/depth.py: resolve_device`
    and deliberately not imported from it. That function lives in the Lab,
    and `test_scene_understanding_does_not_import_another_cartridge`
    forbids `tower.scene` importing `tower.experiments` -- for the good
    reason that the Lab is a sandbox that may be thrown away. Reaching
    through this module to borrow it would couple the two by a longer
    path and honour the letter of that rule while breaking it.

    The behaviour is the same and the reason is the same: an unnoticed
    downgrade from cuda to cpu turns a GPU deployment into a CPU one with
    a GPU label on it, which is worse than a failure. "auto" downgrades;
    "cuda" does not.
    """
    if requested == "cpu":
        return "cpu"

    import torch

    available = torch.cuda.is_available()
    if requested == "auto":
        return "cuda" if available else "cpu"
    if requested == "cuda" and not available:
        raise RuntimeError("cuda requested but torch reports it is unavailable")
    return requested


def _cap_torch_threads(settings) -> None:
    """Bound torch's thread pool, or say why it was not bounded.

    PROCESS-GLOBAL, and that is why it is opt-in rather than a default:
    `torch.set_num_threads` has no per-model scope, so a value chosen for
    the scene detector also applies to the Experimental CV Lab.

    Silence would be the wrong default here. Measured over 829 real
    corpus frames at the delivered 12.0 fps
    (`scripts/cartridge_live_benchmark.py`), torch's own default cost
    **4.12 cores** and capping it at 2 cost **1.03**, with throughput
    identical to within 0.3%. An operator who never learns that is paying
    three cores for nothing, and a log line is the cheapest way to tell
    them.
    """
    if settings.scene_torch_threads <= 0:
        logger.info(
            "[Tower][Config] TOWER_SCENE_TORCH_THREADS is unset: torch will "
            "use one thread per core. Measured at 4.12 cores for one scene "
            "session against 1.03 when capped at 2, with the same "
            "throughput -- set it if this Tower shares its CPU"
        )
        return
    try:
        import torch

        torch.set_num_threads(settings.scene_torch_threads)
    except Exception:
        logger.exception(
            "[Tower][Config] TOWER_SCENE_TORCH_THREADS could not be applied"
        )
        return
    logger.info(
        "[Tower][Config] torch intra-op threads capped at %s. This is "
        "PROCESS-GLOBAL and applies to every torch consumer here, not only "
        "Scene Understanding",
        settings.scene_torch_threads,
    )


def _scene_session(settings):
    """A Scene Understanding session, not yet started.

    Constructed but STOPPED. Starting it is an explicit act -- a POST to
    the control route, or a client subscribing -- because a Tower that
    began detecting the moment it booted would be recording nothing and
    computing constantly, which is the posture `_build_frame_observers`
    already rejects for the recorder ("arming is not recording").

    The factory closes over the device rather than resolving it per
    session, so a `cuda` that has gone missing fails at startup where an
    operator sees it, not on the first frame of a physical test.
    """
    from tower.scene.detect import TorchvisionDetector
    from tower.scene.engine import SceneEngine
    from tower.scene.live import SceneLive

    device = _resolve_device(settings.scene_device)
    _cap_torch_threads(settings)

    def make_engine():
        pose = None
        if settings.scene_orientation:
            from tower.scene.orientation import TorchvisionPoseEstimator

            pose = TorchvisionPoseEstimator(device=device)
        return SceneEngine(
            TorchvisionDetector(device=device), pose_estimator=pose
        )

    logger.info(
        "[Tower][Config] Scene Understanding enabled on %s (orientation %s); "
        "no session is running until one is started",
        device,
        "on" if settings.scene_orientation else "off",
    )
    return SceneLive(make_engine)


def _document_session(settings):
    """A Document Memory capture session, not yet started.

    Requires BOTH a root and the capture flag, and the conjunction is not
    redundant. A root with capture off is a Tower that serves a library
    recorded elsewhere and records nothing itself, which is the correct
    posture for a machine reprocessing captures offline.
    """
    from tower.document_memory.live import DocumentLive

    logger.info(
        "[Tower][Config] document capture enabled, writing to %s; no "
        "session is running until one is started",
        settings.document_root,
    )
    return DocumentLive(settings.document_root)


def build_live_cartridges(settings) -> LiveCartridges:
    """Everything this configuration turns on. Often nothing.

    A failure to construct one cartridge must not cost the other, and
    must not stop the Tower: a missing weight file or a `cuda` that
    vanished is a reason to run without that cartridge and say so
    loudly, not a reason for a Tower to refuse to serve frames. The
    cartridge then reports itself unavailable through the normal path,
    which is the same answer a client would get if it had never been
    enabled -- and the log line is how an operator tells those apart.
    """
    consumers: list = []
    scene = None
    document = None

    if settings.scene_understanding:
        try:
            scene = _scene_session(settings)
            consumers.append(scene)
        except Exception:
            logger.exception(
                "[Tower][Config] Scene Understanding is enabled but could "
                "not be constructed; this Tower will report it unavailable"
            )
            scene = None

    if settings.document_capture and settings.document_root is not None:
        try:
            document = _document_session(settings)
            consumers.append(document)
        except Exception:
            logger.exception(
                "[Tower][Config] document capture is enabled but could not "
                "be constructed; this Tower will record no documents"
            )
            document = None
    elif settings.document_capture:
        logger.warning(
            "[Tower][Config] TOWER_DOCUMENT_CAPTURE is on but "
            "TOWER_DOCUMENT_ROOT is unset: nothing will be recorded, "
            "because there is nowhere to record it"
        )

    return LiveCartridges(frame_consumers=consumers, scene=scene, document=document)
