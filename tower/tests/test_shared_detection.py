"""The shared detector surface, tested without either cartridge.

The point of this file is the one property that makes a promotion safe:
`tower/detection.py` must be usable, and breakable, on its own. If the
only way to exercise it were through Object Memory or Scene
Understanding, it would not be shared infrastructure -- it would be one
cartridge's code that another borrows.

Nothing here imports torch, and nothing here imports a cartridge.
"""

import subprocess
import sys

import pytest

from tower.detection import (
    SCORE_THRESHOLD,
    Detection,
    Detector,
    FixedDetector,
    SSDLite320Detector,
    detections_from_prediction,
)


def test_the_threshold_is_the_one_both_cartridges_already_used():
    """0.4, unchanged. A promotion that moves a number is not a promotion."""
    assert SCORE_THRESHOLD == 0.4


def test_a_detection_is_pixels_and_immutable():
    detection = Detection(label="cup", score=0.9, box=(1.0, 2.0, 3.0, 4.0))

    assert detection.box == (1.0, 2.0, 3.0, 4.0)
    with pytest.raises(Exception):
        detection.score = 0.1


def test_the_protocol_accepts_anything_with_the_four_members():
    assert isinstance(FixedDetector(), Detector)

    class HalfADetector:
        name = "half"

        def load(self):
            return None

    assert not isinstance(HalfADetector(), Detector)


def test_the_fixed_detector_replays_a_script_and_repeats_its_last_frame():
    first = [Detection("cup", 0.9, (0.0, 0.0, 1.0, 1.0))]
    second = [Detection("book", 0.8, (1.0, 1.0, 2.0, 2.0))]
    detector = FixedDetector([first, second])
    detector.load()

    assert detector.detect(None) == first
    assert detector.detect(None) == second
    assert detector.detect(None) == second
    assert detector.calls == 3
    detector.release()


def test_the_fixed_detector_with_no_script_finds_nothing():
    detector = FixedDetector()

    assert detector.detect(None) == []
    assert detector.detect(None) == []


def test_the_fixed_detector_snapshots_what_it_was_given():
    """A test that mutates its own fixture must not retune the detector."""
    frame = [Detection("cup", 0.9, (0.0, 0.0, 1.0, 1.0))]
    frames = [frame]
    detector = FixedDetector(frames)

    frame.append(Detection("book", 0.8, (0.0, 0.0, 1.0, 1.0)))
    frames.append([])

    assert len(detector.detect(None)) == 1


def test_the_fixed_detector_hands_out_copies():
    detector = FixedDetector([[Detection("cup", 0.9, (0.0, 0.0, 1.0, 1.0))]])

    got = detector.detect(None)
    got.clear()

    assert len(detector.detect(None)) == 1


# The mapping from a torchvision prediction to detections is the half of
# the shared code with any decisions in it -- a threshold and a class
# filter -- so it is a free function, tested against lists rather than
# against 13.4 MB of weights.
_CATEGORIES = ["__background__", "person", "cup", "book"]


def test_the_mapping_drops_everything_under_the_threshold():
    detections = detections_from_prediction(
        boxes=[(0, 0, 1, 1), (0, 0, 2, 2)],
        scores=[0.39, 0.41],
        labels=[1, 2],
        categories=_CATEGORIES,
        score_threshold=0.4,
        classes=None,
    )

    assert [d.label for d in detections] == ["cup"]


def test_the_mapping_keeps_every_class_when_no_filter_is_given():
    """Object Memory passes no class list, and must get all of them."""
    detections = detections_from_prediction(
        boxes=[(0, 0, 1, 1), (0, 0, 2, 2), (0, 0, 3, 3)],
        scores=[0.9, 0.9, 0.9],
        labels=[1, 2, 3],
        categories=_CATEGORIES,
        score_threshold=0.4,
        classes=None,
    )

    assert [d.label for d in detections] == ["person", "cup", "book"]


def test_the_mapping_applies_a_class_filter_when_one_is_given():
    """Scene Understanding passes one, and must get only those."""
    detections = detections_from_prediction(
        boxes=[(0, 0, 1, 1), (0, 0, 2, 2), (0, 0, 3, 3)],
        scores=[0.9, 0.9, 0.9],
        labels=[1, 2, 3],
        categories=_CATEGORIES,
        score_threshold=0.4,
        classes={"cup", "book"},
    )

    assert [d.label for d in detections] == ["cup", "book"]


def test_the_mapping_reports_plain_floats_and_a_four_tuple():
    """Whatever numpy handed over, a record must not carry a numpy scalar."""
    detections = detections_from_prediction(
        boxes=[(0, 1, 2, 3)],
        scores=[0.75],
        labels=[2],
        categories=_CATEGORIES,
        score_threshold=0.4,
        classes=None,
    )

    detection = detections[0]
    assert type(detection.score) is float
    assert detection.box == (0.0, 1.0, 2.0, 3.0)
    assert all(type(value) is float for value in detection.box)


# --- the property that matters most: this cannot become a single point
# --- of failure for the platform.


def test_releasing_before_loading_is_safe():
    """A cartridge whose load failed still runs its finally."""
    SSDLite320Detector().release()


def test_two_detectors_share_no_state():
    """No registry, no cache, no residency. Each caller owns its weights.

    The promotion is of CODE. If two cartridges ever shared a loaded
    model, one releasing it would empty the other's -- and a crash in one
    cartridge would take the other's detector with it.
    """
    first = SSDLite320Detector()
    second = SSDLite320Detector()

    first._model = object()

    assert second._model is None


def test_the_module_holds_no_mutable_global():
    """The tripwire for a cache or a registry appearing here later.

    A model manager is a different wave and needs its own evidence. If
    this ever fails, the thing that was added has to justify itself
    before it becomes something every cartridge depends on.
    """
    import tower.detection as module

    offenders = [
        name
        for name, value in vars(module).items()
        if not name.startswith("__")
        and isinstance(value, (dict, list, set))
    ]

    assert offenders == []


def test_importing_the_shared_detector_does_not_import_torch():
    """The optional [ml] extra stays optional, for everyone.

    Shared code is imported by more things than a cartridge is, so a
    module-level torch import here would be the widest possible blast
    radius: the Tower would stop starting on a machine that never
    installed it. Checked in a subprocess -- an in-process assertion
    would pass merely because an earlier test had already imported torch.
    """
    probe = (
        "import sys, tower.detection; "
        "print([m for m in ('torch','torchvision') if m in sys.modules])"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("[]"), result.stdout


def test_a_broken_detector_reaches_only_the_caller_that_asked_for_one():
    """Degrade the cartridge that asked, and nothing else.

    A detector that cannot load raises to its own caller. It does not
    poison the module, so a second cartridge constructing its own
    detector afterwards is unaffected -- which is what lets Object Memory
    keep reporting refusals honestly instead of inheriting somebody
    else's failure.
    """

    class BrokenDetector(SSDLite320Detector):
        def load(self):
            raise RuntimeError("no weights")

    with pytest.raises(RuntimeError):
        BrokenDetector().load()

    survivor = SSDLite320Detector()
    assert survivor._model is None
    assert isinstance(FixedDetector(), Detector)
