"""The failures an adversarial review found, each pinned by a test.

Every case here was REPRODUCED against the running code before it was
fixed, and every one fails without its fix. They share a theme: the
routes are declared sync `def` on purpose, so FastAPI runs them
concurrently in its threadpool, and three pieces of state that looked
single-threaded were not.

All three failed OPEN — an unfiltered frame served with a label saying it
had been filtered, a `stopped` session with a producer still recording,
and two producers appending to one store. Failing open is what makes
these worth a file of their own.
"""

import threading
import time

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from tower.capture_workers import CaptureWorkerSupervisor, WorkerSpec
from tower.cartridge_session import ACTIVE, STOPPED, CartridgeSession
from tower.main import OBJECT_MEMORY_WORKER
from tower.object_memory.imagery import FaceFilter
from tower.object_memory.records import ObjectObservation, privacy_tags_for
from tower.object_memory.store import ObservationStore
from tower.confidence import Confidence
from tower.results.contracts import CARTRIDGE_OBJECT_MEMORY

SESSION_URL = f"/cartridges/{CARTRIDGE_OBJECT_MEMORY}/session"
WIDTH, HEIGHT = 360, 640
CAPTURE_ID = "cap-1"


def _face_frame():
    """A real photograph of a person, at the resolution the glasses send."""
    from skimage import data

    return cv2.resize(
        cv2.cvtColor(data.astronaut(), cv2.COLOR_RGB2BGR), (WIDTH, HEIGHT)
    )


@pytest.fixture
def world(tmp_path):
    capture_root = tmp_path / "data"
    frames = capture_root / "captures" / CAPTURE_ID / "frames"
    frames.mkdir(parents=True)
    cv2.imwrite(str(frames / "00000042.jpg"), _face_frame())

    store_root = tmp_path / "memory"
    store = ObservationStore(store_root, retention_seconds=None)
    observation = ObjectObservation(
        object_class="laptop",
        detector_score=0.81,
        confidence=Confidence.HIGH,
        observed_at=1000.0,
        time_basis="tower-receipt",
        recorded_at=1000.0,
        source="glasses-camera",
        module_id="object-memory",
        session_id=CAPTURE_ID,
        frame_seq=42,
        bounding_box=(0.05, 0.05, 0.95, 0.95),
        retention_tag="default",
        privacy_tags=privacy_tags_for(CAPTURE_ID, 42),
        spatial_ref=None,
        external_refs=(),
        best_score=0.9,
        best_relpath="frames/00000042.jpg",
        best_frame_seq=42,
        best_bounding_box=(0.05, 0.05, 0.95, 0.95),
        tier="remembered",
    )
    store.append(observation)
    return capture_root, store_root, observation.observation_id


@pytest.fixture
def client(world, monkeypatch):
    from tower.main import create_app

    captures, store_root, _ = world
    monkeypatch.setenv("TOWER_CAPTURE_ROOT", str(captures))
    monkeypatch.setenv("TOWER_OBSERVATION_ROOT", str(store_root))
    monkeypatch.delenv("TOWER_WORLD_ROOT", raising=False)
    return TestClient(create_app())


# -- CRITICAL: the shared face filter ----------------------------------


class TestTheFilterUnderLoad:
    def test_the_filter_actually_runs_on_the_route(self, world, client):
        """The test that was missing, and its absence hid everything else.

        Fifteen route tests passed with `FaceFilter.apply` replaced by a
        no-op, because none of them served a frame with a face in it.
        This one does, and it asserts against the PIXELS: the served
        image must differ from the stored file in the region the filter
        reports filling.
        """
        captures, _, observation_id = world
        stored = cv2.imread(
            str(captures / "captures" / CAPTURE_ID / "frames" / "00000042.jpg")
        )

        view = client.get(
            f"/object-memory/observations/{observation_id}/imagery"
        ).json()
        served = cv2.imdecode(
            np.frombuffer(
                client.get(
                    f"/object-memory/observations/{observation_id}/frame"
                ).content,
                np.uint8,
            ),
            cv2.IMREAD_COLOR,
        )

        assert view["regions_filled"] == 1
        # A filled region is solid black. Somewhere in the served image
        # there is a run of zeros that is not in the stored one.
        assert (served == 0).sum() > (stored == 0).sum() + 1000

    def test_concurrent_requests_do_not_serve_an_unfiltered_frame(
        self, world, client
    ):
        """The critical one, reproduced before it was fixed.

        Eight clients, 200 requests, against ONE `FaceFilter` on
        `app.state` whose `cv2.FaceDetectorYN` holds mutable inference
        state. Unlocked, 171 of 200 came back 200 OK reporting
        `regions_filled: 0` on a frame that serially always yields one --
        an unfiltered first-person frame with a label saying it had been
        filtered. Others reported 106, 24 and 23 regions: another
        request's detections painted onto this one's image.

        Nothing raised. It failed open.
        """
        _, _, observation_id = world
        url = f"/object-memory/observations/{observation_id}/imagery"
        results = []
        lock = threading.Lock()

        def hammer():
            for _ in range(25):
                body = client.get(url).json()
                with lock:
                    results.append(body["regions_filled"])

        threads = [threading.Thread(target=hammer) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)

        assert len(results) == 200
        assert set(results) == {1}, sorted(set(results))

    def test_a_blank_path_means_no_model_rather_than_the_current_directory(
        self,
    ):
        """`Path("")` is `Path(".")`, and `Path(".").exists()` is True.

        A filter constructed to be deliberately unavailable therefore
        reported itself AVAILABLE, and refused only because
        `cv2.FaceDetectorYN.create(".")` happened to raise. Every test
        that asserted a refusal through it was passing for that reason
        rather than for the intended one.
        """
        assert FaceFilter(path="").available is False
        assert FaceFilter(path="   ").available is False
        assert FaceFilter().available is True


# -- CRITICAL: Stop racing Start ---------------------------------------


class FakeProcess:
    _pids = iter(range(90000, 900000))

    def __init__(self, argv, **kwargs):
        self.args = list(argv)
        self.pid = next(FakeProcess._pids)
        self._returncode = None
        self.terminated = False

    def poll(self):
        return self._returncode

    def wait(self, timeout=None):
        if self._returncode is None:
            raise TimeoutError(timeout)
        return self._returncode

    def terminate(self):
        self.terminated = True
        self._returncode = -15


class SlowSupervisor:
    """A supervisor whose attach takes long enough for a race to open."""

    def __init__(self, delay=0.05):
        self._delay = delay
        self.following_ids = []

    def worker_names(self):
        return ("worker",)

    def attach(self, name, capture_id, capture_dir):
        time.sleep(self._delay)
        self.following_ids.append(capture_id)
        return True

    def detach(self, name, grace_seconds=0.0):
        count = len(self.following_ids)
        self.following_ids = []
        return count

    def following(self, name):
        return list(self.following_ids)


class TestStopRacingStart:
    def _session(self, supervisor):
        return CartridgeSession(
            cartridge="a_cartridge",
            worker="worker",
            supervisor=supervisor,
            open_capture=lambda: ("cap-1", "/tmp/cap-1"),
            clock=time.time,
        )

    def test_a_stop_during_a_start_does_not_leave_a_producer_running(self):
        """The one control a wearer has over being remembered, failing open.

        `_go_active` sets ACTIVE and then attaches. Unserialised, a Stop
        arriving between those two detached nothing, set STOPPED, and
        then the Start's attach spawned a producer into a stopped
        session. Reproduced: `state=stopped`, `following=['cap-1']`.
        """
        supervisor = SlowSupervisor()
        session = self._session(supervisor)

        starter = threading.Thread(target=session.start)
        starter.start()
        time.sleep(0.01)
        session.stop()
        starter.join(timeout=10)

        snapshot = session.snapshot()
        assert not (
            snapshot["state"] == STOPPED and snapshot["following"]
        ), snapshot

    def test_stop_from_stopped_still_detaches(self):
        """The line that made the bad state unrecoverable.

        `stop()` returned early when the state was already `stopped`, on
        the reasonable view that there was nothing to do -- so a session
        that HAD reached stopped-with-a-producer could not be rescued by
        pressing Stop again.
        """
        supervisor = SlowSupervisor()
        session = self._session(supervisor)
        supervisor.following_ids.append("cap-1")

        result = session.stop()

        assert result["state"] == STOPPED
        assert supervisor.following("worker") == []

    def test_a_start_and_a_stop_never_disagree_under_load(self):
        """Fifty rounds of the race, asserting the invariant each time."""
        supervisor = SlowSupervisor(delay=0.002)
        session = self._session(supervisor)

        for _ in range(50):
            starter = threading.Thread(target=session.start)
            stopper = threading.Thread(target=session.stop)
            starter.start()
            stopper.start()
            starter.join(timeout=10)
            stopper.join(timeout=10)
            snapshot = session.snapshot()
            if snapshot["state"] == STOPPED:
                assert snapshot["following"] == [], snapshot
            else:
                assert snapshot["state"] == ACTIVE, snapshot
            session.stop()


# -- CRITICAL: two attaches, two producers -----------------------------


class TestConcurrentAttach:
    def test_a_capture_opening_as_start_is_pressed_spawns_one_producer(
        self, tmp_path
    ):
        """`capture_opened` runs on the event loop; `attach` on the threadpool.

        Unserialised, both ran the "is anything already following this
        lineage" check, both saw nothing, and both spawned. The second
        overwrote the first in the registry, so the orphan was invisible
        to `reap`, `detach`, `shutdown` and `/health` -- and two
        producers appending to one JSONL store lose each other's writes.
        """
        spawned = []
        lock = threading.Lock()

        def spawn(argv, **kwargs):
            # Long enough for the other thread to get past its own check
            # if nothing is serialising them.
            time.sleep(0.02)
            process = FakeProcess(argv, **kwargs)
            with lock:
                spawned.append(process)
            return process

        supervisor = CaptureWorkerSupervisor(
            [WorkerSpec(argv=("python", "p.py"), name="memory")], spawn=spawn
        )
        directory = tmp_path / "captures" / "cap-1"
        directory.mkdir(parents=True)

        threads = [
            threading.Thread(
                target=supervisor.capture_opened, args=("cap-1", directory)
            ),
            threading.Thread(
                target=supervisor.attach, args=("memory", "cap-1", directory)
            ),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        assert len(spawned) == 1, [p.args for p in spawned]
        assert len(supervisor.status()) == 1

    def test_every_spawned_worker_is_reachable_by_detach(self, tmp_path):
        """No orphans. A worker the registry lost cannot be stopped."""
        spawned = []

        def spawn(argv, **kwargs):
            time.sleep(0.01)
            process = FakeProcess(argv, **kwargs)
            spawned.append(process)
            return process

        supervisor = CaptureWorkerSupervisor(
            [WorkerSpec(argv=("python", "p.py"), name="memory")], spawn=spawn
        )
        directory = tmp_path / "captures" / "cap-1"
        directory.mkdir(parents=True)

        threads = [
            threading.Thread(
                target=supervisor.attach, args=("memory", "cap-1", directory)
            )
            for _ in range(6)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        supervisor.detach("memory", grace_seconds=0.0)

        assert all(process.terminated for process in spawned), [
            (p.pid, p.terminated) for p in spawned
        ]


# -- MAJOR: a Pause that takes five seconds ----------------------------


class TestPauseIsPrompt:
    def test_detaching_does_not_wait_on_a_process_nobody_asked_to_stop(
        self, tmp_path
    ):
        """It measured 5.01 s every time, and then terminated it anyway.

        Nothing signals the producer: it is a follower tailing a journal
        that is still being written, so it has no reason to exit. The
        grace bought nothing and cost a wearer five seconds of a control
        whose whole purpose is to stop recording now.
        """
        supervisor = CaptureWorkerSupervisor(
            [WorkerSpec(argv=("python", "p.py"), name="memory")],
            spawn=lambda argv, **kwargs: FakeProcess(argv, **kwargs),
        )
        directory = tmp_path / "captures" / "cap-1"
        directory.mkdir(parents=True)
        supervisor.capture_opened("cap-1", directory)

        session = CartridgeSession(
            cartridge="a_cartridge",
            worker="memory",
            supervisor=supervisor,
            open_capture=lambda: None,
            clock=time.time,
        )
        session.start()

        began = time.perf_counter()
        session.pause()
        elapsed = time.perf_counter() - began

        assert elapsed < 1.0, f"pause took {elapsed:.2f}s"
        assert supervisor.following("memory") == []


# -- MAJOR: the two verifier-name vocabularies -------------------------


class TestVerifierNames:
    def test_the_settings_and_the_producer_agree_about_verifier_names(self):
        """Two validation rules for one value is a Tower that lies.

        `config.py` accepted any string and read "not none" as "a
        verifier exists", so `TOWER_OBSERVATION_VERIFIER=owvl2` told the
        read routes that fourteen classes were recordable AND handed the
        producer a name it refuses, killing it at spawn.
        """
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path("scripts").resolve()))
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_session_script", "scripts/object_memory_session.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        from tower.config import KNOWN_VERIFIERS

        assert set(module.VERIFIERS) == set(KNOWN_VERIFIERS)

    def test_an_unknown_name_narrows_rather_than_widens(self, monkeypatch):
        from tower.config import get_settings
        from tower.results.object_memory import recorded_classes_for

        monkeypatch.setenv("TOWER_OBSERVATION_VERIFIER", "owvl2")

        settings = get_settings()

        assert settings.observation_verifier == "none"
        assert recorded_classes_for(settings.observation_verifier) == (
            "laptop",
            "cell phone",
        )
