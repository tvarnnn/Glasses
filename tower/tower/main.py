import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from tower.capture import CaptureRecorder
from tower.capture_workers import CaptureWorkerSupervisor, WorkerSpec
from tower.config import Settings, get_settings
from tower.experiments import ExperimentSettings
from tower.logging_config import configure_logging
from tower.modules.base import Module
from tower.modules.container import ModuleContainer
from tower.modules.experimental_cv import ExperimentalCVModule
from tower.results import build_hub
from tower.routes import cartridges, geometry, health, observations, ws
from tower.session import ConnectionTracker

logger = logging.getLogger(__name__)

# The tower project root -- the directory holding `scripts/`, `models/`
# and, by default, `data/`. Resolved from this file rather than from the
# working directory, because a builder started with the wrong CWD finds
# no YuNet weights (`world_builder/redaction.py` resolves them
# relatively) and silently records its redaction as `none`.
TOWER_ROOT = Path(__file__).resolve().parent.parent


def _build_cv_module(settings: Settings) -> Module:
    """The one module slot.

    There used to be a branch here selecting a different Module subclass
    for the depth experiment, because that experiment holds a model.
    Experiment state now lives behind the Experiment protocol, so the
    module is the same one whichever experiment is selected -- which is
    what the module doc always said: one Lab slot, many experiments.
    """
    return ExperimentalCVModule(
        settings.cv_experiment,
        ExperimentSettings(device=settings.cv_device),
    )


def _build_frame_observers(settings: Settings) -> list:
    """Register the dataset recorder, or nothing at all.

    A LIST because ws.py reads a list -- more than one consumer may
    eventually want raw frames, and a singleton would force the second
    one to displace the first.

    Arming is not recording. A configured root creates no directory and
    writes no byte until a `stream_start` arrives, so this stays an
    Explicit Dataset-Recording Session under 06-PRIVACY-DATA.md rather
    than becoming incidental capture. Unset by default, which is why
    every Tower that has ever run recorded nothing.
    """
    if settings.capture_root is None:
        return []
    return [CaptureRecorder(settings.capture_root)]


def _build_capture_worker_supervisor(
    settings: Settings,
) -> CaptureWorkerSupervisor:
    """Decide what, if anything, follows a capture.

    This function is the ONE place in the web process that knows a world
    builder exists, and it knows it as an argv -- a script path and some
    flags -- not as an import. That is deliberate and it is load-bearing:
    `test_shared_code_does_not_import_a_cartridge` forbids transport,
    config and the module system from importing a cartridge, on the
    grounds that "the next cartridge inherits its assumptions". A command
    line inherits nothing, and `CaptureWorkerSupervisor` stays a thing
    that runs processes rather than a thing that builds worlds.

    The web process therefore still does not build. It supervises a child
    that does, which is what keeps an expensive rebuild off the frame
    path.
    """
    if settings.world_root is None or not settings.world_autobuild:
        return CaptureWorkerSupervisor(None)

    return CaptureWorkerSupervisor(
        WorkerSpec(
            argv=(
                sys.executable,
                str(TOWER_ROOT / "scripts" / "world_build_session.py"),
                "--follow-capture",
                "{capture_dir}",
                "--root",
                settings.world_root,
                "--rebuild-every",
                str(settings.world_rebuild_every),
            ),
            cwd=str(TOWER_ROOT),
            name="world-build-session",
        )
    )


def _log_effective_configuration(
    settings: Settings, supervisor: CaptureWorkerSupervisor
) -> None:
    """Say what this Tower will and will not do, at startup, once.

    Both of the settings that decide whether World Builder works at all
    are optional and BOTH fail silently when unset: no capture root means
    no recorder is registered, and no world root means the result channel
    reports the cartridge unavailable. On 2026-08-24 that combination
    produced a Tower that answered every frame, recorded nothing anyone
    could find, and told the phone there was no world -- with nothing in
    the log saying why. Three lines fix that permanently.
    """
    if settings.capture_root is None:
        logger.warning(
            "[Tower][Config] TOWER_CAPTURE_ROOT is unset: NO frames will be "
            "recorded and /health will report capture: null"
        )
    else:
        logger.info(
            "[Tower][Config] capture root %s (armed; records nothing until "
            "stream_start)",
            settings.capture_root,
        )

    if settings.world_root is None:
        logger.warning(
            "[Tower][Config] TOWER_WORLD_ROOT is unset: World Builder is "
            "declared but reported unavailable, and iOS will show it as "
            "unsupported"
        )
    else:
        logger.info("[Tower][Config] world root %s", settings.world_root)

    if settings.observation_root is None:
        logger.info(
            "[Tower][Config] TOWER_OBSERVATION_ROOT is unset: "
            "/object-memory/* will answer 404"
        )
    else:
        logger.info(
            "[Tower][Config] observation root %s (read-only; this process "
            "never writes or deletes observations)",
            settings.observation_root,
        )

    if supervisor.enabled:
        logger.info(
            "[Tower][Config] a builder will be attached to each capture, "
            "rebuilding every %s keyframes",
            settings.world_rebuild_every,
        )
    elif settings.world_root is not None:
        logger.warning(
            "[Tower][Config] TOWER_WORLD_AUTOBUILD is off: captures will be "
            "recorded but NOTHING will build a world from them"
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # The result hub first: it holds a polling task, and stopping it
    # before the module container means no snapshot can be built against
    # an app that is half torn down. Guarded with getattr because most of
    # this repo's tests construct the app without running lifespan at all
    # (see the comment in create_app).
    hub = getattr(app.state, "result_hub", None)
    if hub is not None:
        await hub.shutdown()
    # Workers before the module container, and after the hub: a worker
    # holds a world's writer lock, and the honest order is to let it
    # finish and release before this process stops being able to report
    # what it did.
    supervisor = getattr(app.state, "capture_workers", None)
    if supervisor is not None:
        await asyncio.to_thread(supervisor.shutdown)
    await app.state.module_container.shutdown()


def create_app() -> FastAPI:
    configure_logging(get_settings())

    app = FastAPI(title="Glasses Tower", lifespan=lifespan)
    app.state.session = ConnectionTracker()
    settings = get_settings()
    app.state.module_container = ModuleContainer(_build_cv_module(settings))
    app.state.frame_observers = _build_frame_observers(settings)
    # Read-only, and read by the result channel alone. The web process
    # never builds a world; world_build_session.py does, in its own
    # process, and this is only where to look for what it wrote.
    app.state.world_root = settings.world_root
    # Reads no world and writes no world. It starts the process that
    # does, at the moment a capture id comes into existence -- which is
    # the moment nobody outside this process can know it.
    # Read-only, and read by one HTTP route. The web process never
    # observes and never deletes: the producer is its own script, and
    # deletion is a CLI a human types. Unset means that route answers 404.
    app.state.object_memory_root = settings.observation_root
    app.state.capture_workers = _build_capture_worker_supervisor(settings)
    _log_effective_configuration(settings, app.state.capture_workers)
    # One shared reader for the whole app. It starts no task until a
    # client subscribes and stops again when the last one goes, so a Tower
    # nobody is watching does no polling and no disk IO on its behalf.
    app.state.result_hub = build_hub(settings.world_root)
    # Started here, not in `lifespan` above: TestClient(create_app()) used
    # without `with client:` (every pre-existing test in this repo) never
    # runs ASGI lifespan events, leaving the module UNLOADED forever. See
    # docs/superpowers/specs/2026-08-19-v0.8-module-container-design.md, "Wiring" Amendment.
    asyncio.run(app.state.module_container.load_and_start())
    app.include_router(health.router)
    app.include_router(cartridges.router)
    app.include_router(geometry.router)
    app.include_router(observations.router)
    app.include_router(ws.router)
    return app


app = create_app()
