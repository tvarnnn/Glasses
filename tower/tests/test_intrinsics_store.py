"""The resolution-keyed calibration store.

The behaviour under test is mostly REFUSAL. A calibration that loads and
is wrong by a crop factor produces a plausible trajectory that is wrong,
which is the worst failure mode available -- so almost every case here
asserts that the store declines to answer rather than that it answers.

Nothing here says anything about the real Ray-Ban camera. Every
calibration in this file is fabricated.
"""

import json
import logging

import pytest

from tower.world_builder.intrinsics_store import IntrinsicsStore
from tower.world_builder.records import CameraIntrinsics
from tower.world_builder.schema import (
    INTRINSICS_SOURCE_SELF_CALIBRATED,
    INTRINSICS_SOURCE_UNKNOWN,
)


def _calibration(width=360, height=640, **overrides) -> CameraIntrinsics:
    """A fabricated but structurally valid calibration."""
    fields = dict(
        source=INTRINSICS_SOURCE_SELF_CALIBRATED,
        model="pinhole_radtan",
        fx=301.5,
        fy=302.25,
        cx=width / 2 - 1.0,
        cy=height / 2 + 2.0,
        dist_coeffs=(0.01, -0.02, 0.0, 0.0, 0.0),
        calibrated_width=width,
        calibrated_height=height,
        reprojection_rms_px=0.31,
        view_count=14,
        calibrated_at=1787548811.0,
        scales_linearly_across_resolutions=None,
    )
    fields.update(overrides)
    return CameraIntrinsics(**fields)


@pytest.fixture
def store(tmp_path):
    return IntrinsicsStore(tmp_path)


class TestDefaultLocation:
    def test_calibrations_sit_beside_worlds_not_inside_one(self, store, tmp_path):
        """A calibration describes the camera, not any single world.

        Filing it inside a world would lose it to the next world, and to
        a privacy purge of the world that happened to be recording.
        """
        assert store.directory == tmp_path / "intrinsics"

    def test_the_resolution_is_the_filename(self, store, tmp_path):
        assert store.path_for(360, 640) == tmp_path / "intrinsics" / "360x640.json"

    def test_a_path_exists_for_a_resolution_with_no_calibration(self, store):
        """The miss log has to name where it looked."""
        assert store.path_for(1280, 720).name == "1280x720.json"


class TestSaveThenLookup:
    def test_a_saved_calibration_is_found_at_its_own_resolution(self, store):
        store.save(_calibration(360, 640))

        found = store.lookup(360, 640)

        assert found.is_known
        assert found.fx == pytest.approx(301.5)
        assert found.calibrated_width == 360
        assert found.calibrated_height == 640

    def test_save_keys_on_the_records_own_resolution(self, store):
        path = store.save(_calibration(480, 360))

        assert path.name == "480x360.json"

    def test_the_round_trip_preserves_every_field(self, store):
        original = _calibration(360, 640)

        store.save(original)

        assert store.lookup(360, 640) == original

    def test_saving_twice_replaces_rather_than_accumulates(self, store):
        store.save(_calibration(360, 640, fx=300.0))
        store.save(_calibration(360, 640, fx=311.0))

        assert store.lookup(360, 640).fx == pytest.approx(311.0)
        assert store.list_resolutions() == ((360, 640),)

    def test_several_resolutions_coexist(self, store):
        store.save(_calibration(360, 640))
        store.save(_calibration(480, 360))

        assert store.list_resolutions() == ((360, 640), (480, 360))
        assert store.lookup(360, 640).calibrated_height == 640
        assert store.lookup(480, 360).calibrated_height == 360


class TestAMissIsNormal:
    def test_an_empty_store_returns_unknown_rather_than_raising(self, store):
        found = store.lookup(360, 640)

        assert found == CameraIntrinsics.unknown()
        assert not found.is_known
        assert found.source == INTRINSICS_SOURCE_UNKNOWN

    def test_a_miss_is_logged_with_the_resolution_and_the_path(
        self, store, caplog
    ):
        """This log line is the answer to "why is there no geometry?"."""
        with caplog.at_level(logging.INFO):
            store.lookup(360, 640)

        message = caplog.text
        assert "360x640" in message
        assert "360x640.json" in message

    def test_a_miss_leaves_the_unposed_backend_selected(self, store):
        from tower.world_builder.backends import (
            BACKEND_AUTO,
            UnposedBackend,
            select_backend,
        )

        selection = select_backend(BACKEND_AUTO, store.lookup(360, 640))

        assert isinstance(selection.backend, UnposedBackend)

    def test_listing_an_absent_directory_is_empty_not_an_error(self, store):
        assert store.list_resolutions() == ()


class TestResolutionMismatchIsRefused:
    def test_another_resolutions_calibration_does_not_satisfy_a_lookup(
        self, store
    ):
        """The 2026-08-24 trap, exactly.

        That session recorded declared 480x360 while every one of its 155
        keyframes was 360x640.
        """
        store.save(_calibration(480, 360))

        assert not store.lookup(360, 640).is_known

    def test_a_record_filed_under_the_wrong_resolution_is_refused(
        self, store, caplog
    ):
        """A file copied or renamed by hand.

        Filename and record disagree; neither is trusted.
        """
        store.path_for(360, 640).parent.mkdir(parents=True, exist_ok=True)
        store.path_for(360, 640).write_text(
            json.dumps(_calibration(480, 360).to_json_dict()), encoding="utf-8"
        )

        with caplog.at_level(logging.WARNING):
            found = store.lookup(360, 640)

        assert not found.is_known
        assert "refusing to use it" in caplog.text

    def test_the_store_never_rescales(self, store):
        """`records.scaled_to` already refuses; the store must not route around it.

        Whether DAT resizes or crops between its three modes has never
        been established.
        """
        store.save(_calibration(180, 320))

        found = store.lookup(360, 640)

        assert not found.is_known
        assert found.fx is None


class TestCorruptRecordsDegradeRatherThanRaise:
    def test_unparseable_json_becomes_unknown_with_a_warning(
        self, store, caplog
    ):
        path = store.path_for(360, 640)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")

        with caplog.at_level(logging.WARNING):
            found = store.lookup(360, 640)

        assert found == CameraIntrinsics.unknown()
        assert "unreadable" in caplog.text

    def test_a_truncated_record_becomes_unknown_with_a_warning(
        self, store, caplog
    ):
        payload = _calibration(360, 640).to_json_dict()
        del payload["cx"]
        path = store.path_for(360, 640)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

        with caplog.at_level(logging.WARNING):
            found = store.lookup(360, 640)

        assert found == CameraIntrinsics.unknown()
        assert "not a usable" in caplog.text

    def test_a_self_calibrated_record_with_no_focal_length_is_refused(
        self, store, caplog
    ):
        """`camera_intrinsics_from_json_dict` raises; the store absorbs it."""
        payload = _calibration(360, 640).to_json_dict()
        payload["fx"] = None
        path = store.path_for(360, 640)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

        with caplog.at_level(logging.WARNING):
            found = store.lookup(360, 640)

        assert found == CameraIntrinsics.unknown()

    def test_an_empty_file_becomes_unknown(self, store):
        path = store.path_for(360, 640)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

        assert store.lookup(360, 640) == CameraIntrinsics.unknown()

    def test_a_physically_impossible_camera_is_refused(self, store, caplog):
        """fx=0 satisfies "is not None" and routes to the classical backend."""
        payload = _calibration(360, 640, fx=0.0).to_json_dict()
        path = store.path_for(360, 640)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

        with caplog.at_level(logging.WARNING):
            found = store.lookup(360, 640)

        assert found == CameraIntrinsics.unknown()
        assert "usable camera" in caplog.text

    def test_a_directory_where_a_file_belongs_becomes_unknown(self, store):
        store.path_for(360, 640).mkdir(parents=True, exist_ok=True)

        assert store.lookup(360, 640) == CameraIntrinsics.unknown()

    def test_a_non_resolution_filename_is_skipped_by_listing(self, store):
        store.save(_calibration(360, 640))
        (store.directory / "notes.json").write_text("{}", encoding="utf-8")

        assert store.list_resolutions() == ((360, 640),)


class TestSaveRefuses:
    def test_unknown_intrinsics_are_not_storable(self, store):
        with pytest.raises(ValueError, match="usable camera"):
            store.save(CameraIntrinsics.unknown())

        assert store.list_resolutions() == ()

    def test_a_calibration_with_no_resolution_is_not_storable(self, store):
        headless = _calibration(360, 640, calibrated_width=None, calibrated_height=None)

        with pytest.raises(ValueError, match="no recorded resolution"):
            store.save(headless)

    def test_an_impossible_focal_length_is_not_storable(self, store):
        with pytest.raises(ValueError, match="usable camera"):
            store.save(_calibration(360, 640, fx=-500.0))


class TestAHitIsAnnounced:
    def test_finding_a_calibration_logs_its_source_resolution_and_rms(
        self, store, caplog
    ):
        """Silence here is what made 2026-08-24 unexplainable."""
        store.save(_calibration(360, 640))
        caplog.clear()

        with caplog.at_level(logging.INFO):
            store.lookup(360, 640)

        message = caplog.text
        assert INTRINSICS_SOURCE_SELF_CALIBRATED in message
        assert "360x640" in message
        assert "0.3100" in message

    def test_a_hit_selects_the_classical_backend(self, store):
        from tower.world_builder.backends import (
            BACKEND_AUTO,
            ClassicalTwoViewBackend,
            select_backend,
        )

        store.save(_calibration(360, 640))

        selection = select_backend(BACKEND_AUTO, store.lookup(360, 640))

        assert isinstance(selection.backend, ClassicalTwoViewBackend)
        assert not selection.was_downgraded


class TestTheDriverDiscoversByObservedResolution:
    """The other half of the closed loop.

    `world_build_session.py` must consult the store with the resolution
    the frames MEASURE at. The 2026-08-24 session declared 480x360 while
    every one of its 155 keyframes was 360x640 -- so anything keyed off a
    declaration would have looked in the wrong place, or worse, found a
    480x360 calibration and used it.
    """

    @staticmethod
    def _driver():
        from scripts import world_build_session

        return world_build_session

    def _write_capture(self, directory, records):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "frames.jsonl").write_text(
            "".join(json.dumps(record) + "\n" for record in records),
            encoding="utf-8",
        )

    def test_a_capture_journals_observed_size_is_read_from_its_first_record(
        self, tmp_path
    ):
        self._write_capture(
            tmp_path / "cap",
            [
                {"relpath": "frames/1.jpg", "width": 360, "height": 640},
                {"relpath": "frames/2.jpg", "width": 360, "height": 640},
            ],
        )

        assert self._driver().observed_size_from_capture(tmp_path / "cap") == (
            360,
            640,
        )

    def test_a_capture_with_no_frames_yet_reports_unobserved(self, tmp_path):
        """A real state on the live path: the builder can attach first."""
        self._write_capture(tmp_path / "cap", [])

        assert self._driver().observed_size_from_capture(tmp_path / "cap") is None

    def test_a_capture_with_no_journal_reports_unobserved(self, tmp_path):
        (tmp_path / "cap").mkdir()

        assert self._driver().observed_size_from_capture(tmp_path / "cap") is None

    def test_a_torn_journal_line_reports_unobserved_rather_than_raising(
        self, tmp_path
    ):
        (tmp_path / "cap").mkdir()
        (tmp_path / "cap" / "frames.jsonl").write_text(
            '{"relpath": "frames/1.jpg", "wid', encoding="utf-8"
        )

        assert self._driver().observed_size_from_capture(tmp_path / "cap") is None

    def test_a_frames_directory_is_measured_from_the_first_jpeg(self, tmp_path):
        from PIL import Image

        directory = tmp_path / "frames"
        directory.mkdir()
        Image.new("RGB", (360, 640)).save(directory / "0001.jpg")
        Image.new("RGB", (360, 640)).save(directory / "0002.jpg")

        assert self._driver().observed_size_from_frames(directory) == (360, 640)

    def test_an_empty_frames_directory_reports_unobserved(self, tmp_path):
        (tmp_path / "frames").mkdir()

        assert self._driver().observed_size_from_frames(tmp_path / "frames") is None

    def test_an_undecodable_jpeg_reports_unobserved(self, tmp_path):
        directory = tmp_path / "frames"
        directory.mkdir()
        (directory / "0001.jpg").write_bytes(b"not a jpeg")

        assert self._driver().observed_size_from_frames(directory) is None


class TestResolveIntrinsics:
    """The driver's miss must be indistinguishable in BEHAVIOUR from today.

    Only the logging changes. An uncalibrated Tower keeps mapping.
    """

    @staticmethod
    def _resolve(store, size):
        from scripts.world_build_session import resolve_intrinsics

        return resolve_intrinsics(store, size, frame_source="recorded-capture")

    def test_a_hit_at_the_observed_resolution_is_returned(self, store):
        store.save(_calibration(360, 640))

        assert self._resolve(store, (360, 640)).is_known

    def test_a_miss_returns_unknown_and_names_the_resolution_and_the_fix(
        self, store, caplog
    ):
        with caplog.at_level(logging.WARNING):
            found = self._resolve(store, (360, 640))

        assert found == CameraIntrinsics.unknown()
        assert "NO CALIBRATION" in caplog.text
        assert "360x640" in caplog.text
        assert "0 poses and 0 points" in caplog.text
        assert "docs/CALIBRATION.md" in caplog.text

    def test_a_miss_lists_the_calibrations_that_DO_exist(self, store, caplog):
        """"You have 480x360, you are streaming 360x640" is actionable."""
        store.save(_calibration(480, 360))

        with caplog.at_level(logging.WARNING):
            found = self._resolve(store, (360, 640))

        assert not found.is_known
        assert "480x360" in caplog.text

    def test_an_unobservable_resolution_returns_unknown_with_a_warning(
        self, store, caplog
    ):
        with caplog.at_level(logging.WARNING):
            found = self._resolve(store, None)

        assert found == CameraIntrinsics.unknown()
        assert "could not observe the frame resolution" in caplog.text

    def test_a_miss_still_selects_the_unposed_backend(self, store):
        from tower.world_builder.backends import (
            BACKEND_AUTO,
            UnposedBackend,
            select_backend,
        )

        selection = select_backend(BACKEND_AUTO, self._resolve(store, (360, 640)))

        assert isinstance(selection.backend, UnposedBackend)
        assert selection.was_downgraded
