"""This cartridge's detector: the shared one, narrowed and re-shaped.

The seam, the fake, the 0.4 threshold and the twenty lines around
`ssdlite320_mobilenet_v3_large` used to live here in full, duplicated
almost verbatim in Object Memory. They now live in `tower/detection.py`,
promoted once a third consumer of the same weights appeared. What is left
here is the part that is genuinely about Scene Understanding: which
classes it cares about, and the detection type it reports.

**The seam still exists, for the reasons it always did.** The real
detector costs ~32 ms and a model download, which a default test suite
should pay neither of; and the choice should follow measurement rather
than be welded into the pipeline.

**Still not the Experimental CV Lab**, and a test still enforces it. The
Lab measured this exact model -- 35.3 ms at 640x360, and notably
resolution-independent because it resizes to 320 internally -- but its
`ExperimentResult` is scalars and a `name -> number` bag; it cannot carry
a box. Depending on a platform module is a different thing from
depending on a sandbox: shared code is maintained, a sandbox may be
thrown away, and nothing that may be thrown away belongs upstream of a
production consumer.

**Why this cartridge still owns a detection type.** `records.Detection`
carries a `BoundingBox`, which has IoU on it because the tracker
associates by overlap, and `to_json_dict` because a scene state is
rendered. Shared code reports a plain 4-tuple, which is the narrowest
shape that carries a box; the conversion is one function below and it
belongs on this side of the boundary.

Everything here is **model inference, not measured fact**
(`07-PLATFORM-CONSTRAINTS.md` Core Principle 2). A detection is evidence
that something scored above a threshold.
"""

from tower.detection import SCORE_THRESHOLD, Detector, FixedDetector, SSDLite320Detector
from tower.scene.records import BoundingBox, Detection

# Re-exported so this cartridge's callers keep importing from this
# cartridge, and so a driver never has to know which names came from the
# platform and which were written here.
__all__ = [
    "SCORE_THRESHOLD",
    "CLASSES_OF_INTEREST",
    "Detector",
    "FixedDetector",
    "TorchvisionDetector",
    "to_scene_detection",
]

# The classes this cartridge reports. Not all 91: the brief's questions
# are about people and furniture, and a scene state cluttered with every
# COCO class would bury them. Adding one is a one-line change.
#
# Narrowing HERE, at the detector, rather than downstream: this cartridge
# answers "what is around me now" and everything it keeps is tracked and
# rendered immediately. Object Memory does the opposite and keeps every
# class, because a memory cannot pre-judge what will matter later. That
# is why the shared detector takes a class list instead of owning one.
CLASSES_OF_INTEREST = (
    "person",
    "chair",
    "couch",
    "bed",
    "dining table",
    "tv",
    "laptop",
    "book",
    "bottle",
    "cup",
    "keyboard",
    "mouse",
    "cell phone",
)


def to_scene_detection(detection) -> Detection:
    """A platform detection, in this cartridge's vocabulary.

    A free function so the conversion is testable on its own, without
    weights: it is the only thing the adapter below actually does, and an
    untested conversion between two box conventions is exactly where an
    x/y transposition hides.
    """
    return Detection(
        label=detection.label,
        score=detection.score,
        box=BoundingBox(*detection.box),
    )


class TorchvisionDetector:
    """The shared SSDLite detector, reporting this cartridge's Detection.

    Composition rather than a subclass, deliberately: `detect` returns a
    different type from the one the shared class returns, and a subclass
    that changes its parent's return type is a substitution bug waiting
    for the first caller who holds the base type. Wrapping says what is
    true -- this is a scene-shaped view of a platform detector.

    Its own weights, like every other caller's. See `tower/detection.py`
    on why residency was not promoted along with the code.
    """

    name = "ssdlite320"

    def __init__(
        self,
        score_threshold: float = SCORE_THRESHOLD,
        classes=CLASSES_OF_INTEREST,
        device: str = "cpu",
    ) -> None:
        self._inner = SSDLite320Detector(
            score_threshold=score_threshold,
            classes=classes,
            device=device,
            owner="Scene",
        )

    def load(self) -> None:
        self._inner.load()

    def detect(self, frame_bgr) -> list[Detection]:
        return [
            to_scene_detection(detection)
            for detection in self._inner.detect(frame_bgr)
        ]

    def release(self) -> None:
        self._inner.release()
