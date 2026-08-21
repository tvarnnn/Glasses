# Object Memory — First Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

> ## ⛔ THIS PLAN IS NOT AUTHORIZED TO EXECUTE YET
>
> It was written during the 2026-08-20 weekend autonomous run as the
> Master Guide §17 **SHOULD item 5** deliverable ("design/spec review only
> … write an implementation plan for review"). **Task 4 contains a hard
> DECISION GATE that requires an explicit user ruling** before any code in
> Task 4 or later is written — see that task. Tasks 1–3 are
> autonomous-safe, but the Master Guide directs that Object Memory
> implementation not begin until the plan itself has been reviewed.

**Goal:** Build the smallest honest Object Memory that persists
"what object was seen, when, with what confidence" and can answer "when did
I last see X", with a real working purge path — without claiming per-object
identity, spatial position, or presence it cannot support.

**Architecture:** A new `Module` (separate descriptor id from
`experimental-cv`) that runs a COCO-pretrained torchvision detector per
frame, converts detections into append-only observation records under an
explicit relevance filter, and persists them as JSONL in a module-owned
namespace. Retrieval and purge are exposed as plain Python methods plus two
read-only HTTP endpoints. No tracker, no embeddings, no re-identification,
no LLM, no spatial mapping in this slice.

**Tech Stack:** Python 3.12, FastAPI, PyTorch + torchvision (already the
`ml` extra), OpenCV, JSONL on local disk. **No new dependency is
introduced by this plan** — see Global Constraints.

**Spec:** `guidelines/docs/modules/OBJECT-MEMORY.md`
**Supporting research:**
`docs/superpowers/research/2026-08-20-canonical-memory-architecture.md`
(observation-record shape, storage-technology sequencing),
`docs/superpowers/research/2026-08-20-platform-backend-audit.md`
(persistence + purge as a hard prerequisite).

---

## Global Constraints

Every task's requirements implicitly include this section.

- **Python `>=3.12`**; the repo pins nothing else. Match existing style:
  4-space indent, type hints on public functions, no docstring on trivial
  helpers, comments only where they explain *why*.
- **No new third-party dependency.** The detector MUST come from
  `torchvision.models.detection`, which is already installed via the `ml`
  extra (verified 2026-08-20: `torchvision 0.28.0` exposes
  `ssdlite320_mobilenet_v3_large`, `fasterrcnn_mobilenet_v3_large_320_fpn`,
  and others). Adding `ultralytics`/YOLO would introduce a new dependency
  **and** an AGPL-3.0 license obligation for zero measured benefit at this
  stage — rejected per Rule 17.
- **Torch is optional core-wide.** `import torch`/`import torchvision` MUST
  be local to the functions that need them (follow
  `tower/experiments/depth.py`'s pattern exactly), so a Tower running
  `baseline` still starts with no torch installed.
- **Pin the detector weights enum explicitly** (e.g.
  `SSDLite320_MobileNet_V3_Large_Weights.COCO_V1`), never a string alias or
  a default that can float. Direct precedent: the V0.9.1 MiDaS `torch.hub`
  ref pin.
- **Rule 3 / Rule 16 (truthful state):** an observation is evidence, not
  fact. Never record or return "object is at X". Only "object was last
  observed at time T with confidence C". Absence of observation is never
  absence of the object.
- **Rule 6 (modules own their data):** all storage lives under this
  module's own namespace directory. Nothing reads or writes another
  module's data.
- **`06-PRIVACY-DATA.md`:** persist derived/structured data only. **No
  image crops, no raw frames, no embeddings are written to disk in this
  slice.** Retention must be configurable, not hardcoded-forever. Purge
  must be real deletion, not hiding.
- **Every task ends green:** `python -m pytest -q` must pass. Baseline
  before this plan starts: `113 passed, 3 skipped`.
- **Model-dependent tests are opt-in**, gated behind
  `TOWER_RUN_MODEL_TESTS=1`, exactly like
  `tests/test_depth_experiment_integration.py`.

---

## Scope: what this slice deliberately excludes

Named here so an executor does not "helpfully" add them. Each maps to a
spec section that explicitly defers it.

| Excluded | Why |
|---|---|
| Multi-object tracker / `trackId` | Spec's pipeline lists it, but a tracker is only meaningful once "same object across frames" matters for retrieval. Deferred until the relevance filter's measured behavior shows it is needed. Rule 10. |
| Instance re-ID ("*my* backpack") | Spec: "Do not claim unique-object identity unless the implementation actually supports it." This slice records COCO *categories* only. |
| Visual embeddings | No retrieval feature in this slice needs them; `sqlite-vec`-class storage is explicitly deferred until measured necessary. |
| Stored crops/keyframes | Privacy: a crop can contain a bystander/screen/document. Excluded until a feature justifies it. |
| `locationContext` / spatial mapping | Spec: "Do not require full spatial mapping for the first version." Field is reserved-but-unused. |
| Natural-language query / LLM | Spec: object history must be queryable independently of an LLM. Build the independent layer first. |
| Module registry / runtime switching | That is V1.0, triggered *by* this module's real requirements — not built ahead of it. |

---

## File Structure

**Create:**
- `tower/modules/object_memory.py` — the `Module` subclass: lifecycle,
  descriptor, per-frame dispatch. Owns nothing else.
- `tower/object_memory/__init__.py` — package marker.
- `tower/object_memory/records.py` — the `ObjectObservation` record shape
  and its serialization. Pure data, no I/O, no torch.
- `tower/object_memory/detector.py` — torchvision detector wrapper
  (load/run/release), mirroring `tower/experiments/depth.py`'s shape.
- `tower/object_memory/relevance.py` — decides which detections become
  persisted observations. Pure logic, no I/O.
- `tower/object_memory/store.py` — JSONL append/read/purge with retention.
  The only module that touches the filesystem.
- `tower/routes/object_memory.py` — read-only HTTP query + purge endpoints.

**Modify:**
- `tower/config.py` — add `module` and object-memory settings.
- `tower/main.py:15-20` — `_build_cv_module` gains an Object Memory branch.
- `README.md` — Project Structure + configuration table.

**Test:**
- `tests/test_object_memory_records.py`
- `tests/test_object_memory_relevance.py`
- `tests/test_object_memory_store.py`
- `tests/test_object_memory_module.py`
- `tests/test_object_memory_routes.py`
- `tests/test_object_memory_detector_integration.py` (opt-in, real model)

Separation rationale: `records`/`relevance` are pure and fast to test;
`store` is the only filesystem owner so purge correctness is testable in
one place; `detector` is the only torch-touching file so the rest of the
module tests run without torch installed.

---

### Task 1: Observation record shape

Adopts the shared conceptual record from
`docs/superpowers/research/2026-08-20-canonical-memory-architecture.md`
inside this module's own storage — no shared service, zero coordination
cost, but avoids a migration later if a real cross-module need appears.

**Files:**
- Create: `tower/object_memory/__init__.py`
- Create: `tower/object_memory/records.py`
- Test: `tests/test_object_memory_records.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class Confidence(Enum)` with members `UNKNOWN`, `LOW`, `MEDIUM`, `HIGH`
    and classmethod `from_score(score: float | None) -> "Confidence"`.
  - `@dataclass(frozen=True) class ObjectObservation` with fields:
    `object_class: str`, `detector_score: float | None`,
    `confidence: Confidence`, `observed_at: float` (epoch seconds, capture
    time), `recorded_at: float` (epoch seconds, record-created time),
    `source: str`, `module_id: str`, `session_id: str | None`,
    `frame_seq: int | None`, `bounding_box: tuple[float, float, float, float] | None`,
    `retention_tag: str`, `privacy_tags: tuple[str, ...]`,
    `spatial_ref: None`, `external_refs: tuple[()]`, `deleted: bool = False`.
  - `ObjectObservation.to_json_dict(self) -> dict`
  - `object_observation_from_json_dict(data: dict) -> ObjectObservation`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_object_memory_records.py
import pytest

from tower.object_memory.records import (
    Confidence,
    ObjectObservation,
    object_observation_from_json_dict,
)


def _observation(**overrides) -> ObjectObservation:
    defaults = dict(
        object_class="keys",
        detector_score=0.91,
        confidence=Confidence.HIGH,
        observed_at=1000.0,
        recorded_at=1000.5,
        source="glasses-camera",
        module_id="object-memory",
        session_id="session-1",
        frame_seq=42,
        bounding_box=(1.0, 2.0, 3.0, 4.0),
        retention_tag="default",
        privacy_tags=("derived-only",),
        spatial_ref=None,
        external_refs=(),
    )
    defaults.update(overrides)
    return ObjectObservation(**defaults)


def test_confidence_from_score_buckets_by_threshold():
    assert Confidence.from_score(None) is Confidence.UNKNOWN
    assert Confidence.from_score(0.30) is Confidence.LOW
    assert Confidence.from_score(0.60) is Confidence.MEDIUM
    assert Confidence.from_score(0.95) is Confidence.HIGH


def test_observation_round_trips_through_json_dict():
    original = _observation()

    restored = object_observation_from_json_dict(original.to_json_dict())

    assert restored == original


def test_observed_at_and_recorded_at_are_distinct_fields():
    # Rule 16: capture time and record time must not be conflated.
    observation = _observation(observed_at=10.0, recorded_at=99.0)

    data = observation.to_json_dict()

    assert data["observed_at"] == 10.0
    assert data["recorded_at"] == 99.0


def test_confidence_survives_serialization_as_a_label_not_a_number():
    # Rule 16: confidence must survive persistence.
    data = _observation(confidence=Confidence.UNKNOWN).to_json_dict()

    assert data["confidence"] == "unknown"


def test_observation_is_immutable():
    observation = _observation()

    with pytest.raises(Exception):
        observation.object_class = "mutated"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_object_memory_records.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'tower.object_memory'`

- [ ] **Step 3: Write minimal implementation**

```python
# tower/object_memory/__init__.py
```

(empty file — package marker, matching `tower/modules/__init__.py`)

```python
# tower/object_memory/records.py
from dataclasses import dataclass
from enum import Enum

# Bucket boundaries are deliberate placeholders pending measurement, not
# tuned values: no retrieval-accuracy data exists yet to justify specific
# thresholds. They exist so confidence is carried end-to-end from day one
# (Rule 16) rather than retrofitted; revisit once Task 8 produces numbers.
LOW_CONFIDENCE_MAX = 0.5
MEDIUM_CONFIDENCE_MAX = 0.8


class Confidence(Enum):
    UNKNOWN = "unknown"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @classmethod
    def from_score(cls, score: float | None) -> "Confidence":
        if score is None:
            return cls.UNKNOWN
        if score < LOW_CONFIDENCE_MAX:
            return cls.LOW
        if score < MEDIUM_CONFIDENCE_MAX:
            return cls.MEDIUM
        return cls.HIGH


@dataclass(frozen=True)
class ObjectObservation:
    """One "this category was visible at this time" record.

    Deliberately NOT a claim that the object is present now, or that it is
    a specific instance ("my keys" vs "keys"). See 07-PLATFORM-CONSTRAINTS.md
    Core Principle 3 and OBJECT-MEMORY.md's Identity vs. Category section.

    spatial_ref and external_refs are reserved-but-unused: they are carried
    so a later cross-module need does not require rewriting already-persisted
    records (see 2026-08-20-canonical-memory-architecture.md).
    """

    object_class: str
    detector_score: float | None
    confidence: Confidence
    observed_at: float
    recorded_at: float
    source: str
    module_id: str
    session_id: str | None
    frame_seq: int | None
    bounding_box: tuple[float, float, float, float] | None
    retention_tag: str
    privacy_tags: tuple[str, ...]
    spatial_ref: None
    external_refs: tuple[()]
    deleted: bool = False

    def to_json_dict(self) -> dict:
        return {
            "object_class": self.object_class,
            "detector_score": self.detector_score,
            "confidence": self.confidence.value,
            "observed_at": self.observed_at,
            "recorded_at": self.recorded_at,
            "source": self.source,
            "module_id": self.module_id,
            "session_id": self.session_id,
            "frame_seq": self.frame_seq,
            "bounding_box": list(self.bounding_box) if self.bounding_box else None,
            "retention_tag": self.retention_tag,
            "privacy_tags": list(self.privacy_tags),
            "spatial_ref": self.spatial_ref,
            "external_refs": list(self.external_refs),
            "deleted": self.deleted,
        }


def object_observation_from_json_dict(data: dict) -> ObjectObservation:
    box = data.get("bounding_box")
    return ObjectObservation(
        object_class=data["object_class"],
        detector_score=data["detector_score"],
        confidence=Confidence(data["confidence"]),
        observed_at=data["observed_at"],
        recorded_at=data["recorded_at"],
        source=data["source"],
        module_id=data["module_id"],
        session_id=data.get("session_id"),
        frame_seq=data.get("frame_seq"),
        bounding_box=tuple(box) if box else None,
        retention_tag=data["retention_tag"],
        privacy_tags=tuple(data["privacy_tags"]),
        spatial_ref=None,
        external_refs=(),
        deleted=data.get("deleted", False),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_object_memory_records.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Run the full suite unmodified**

Run: `python -m pytest -q`
Expected: `118 passed, 3 skipped`

- [ ] **Step 6: Commit**

```bash
git add tower/object_memory/__init__.py tower/object_memory/records.py tests/test_object_memory_records.py
git commit -m "feat: add Object Memory observation record shape"
```

---

### Task 2: Relevance filter

Implements OBJECT-MEMORY.md's "should not save every detection from every
frame" requirement. Pure logic, no I/O, no torch — so it is fully testable
without a model.

**Files:**
- Create: `tower/object_memory/relevance.py`
- Test: `tests/test_object_memory_relevance.py`

**Interfaces:**
- Consumes: `Confidence`, `ObjectObservation` (Task 1).
- Produces:
  - `@dataclass class RelevancePolicy` with fields
    `min_score: float = 0.5`, `resample_seconds: float = 30.0`.
  - `class RelevanceFilter` with:
    - `__init__(self, policy: RelevancePolicy) -> None`
    - `should_record(self, object_class: str, score: float, now: float) -> bool`
    - `note_recorded(self, object_class: str, now: float) -> None`

Semantics: record a detection when its score clears `min_score` **and**
either the class has not been seen before (a genuinely new observation) or
`resample_seconds` have elapsed since that class was last recorded. This is
the "newly observed object" + "low-value repeated detections should be
sampled" pair from the spec, and nothing more — "picked up/moved",
"disappeared", "reappeared in new context" all require a tracker and are
out of scope.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_object_memory_relevance.py
from tower.object_memory.relevance import RelevanceFilter, RelevancePolicy


def _filter(**overrides) -> RelevanceFilter:
    return RelevanceFilter(RelevancePolicy(**overrides))


def test_detection_below_min_score_is_not_recorded():
    relevance = _filter(min_score=0.5)

    assert relevance.should_record("keys", score=0.49, now=100.0) is False


def test_first_confident_sighting_of_a_class_is_recorded():
    relevance = _filter(min_score=0.5)

    assert relevance.should_record("keys", score=0.80, now=100.0) is True


def test_repeat_sighting_within_resample_window_is_suppressed():
    relevance = _filter(min_score=0.5, resample_seconds=30.0)
    relevance.note_recorded("keys", now=100.0)

    assert relevance.should_record("keys", score=0.99, now=120.0) is False


def test_repeat_sighting_after_resample_window_is_recorded_again():
    relevance = _filter(min_score=0.5, resample_seconds=30.0)
    relevance.note_recorded("keys", now=100.0)

    assert relevance.should_record("keys", score=0.80, now=131.0) is True


def test_suppression_is_per_class_not_global():
    relevance = _filter(min_score=0.5, resample_seconds=30.0)
    relevance.note_recorded("keys", now=100.0)

    assert relevance.should_record("backpack", score=0.80, now=101.0) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_object_memory_relevance.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'tower.object_memory.relevance'`

- [ ] **Step 3: Write minimal implementation**

```python
# tower/object_memory/relevance.py
from dataclasses import dataclass


@dataclass
class RelevancePolicy:
    """Thresholds for turning raw detections into stored observations.

    Values are starting points to be revisited against measured retrieval
    behavior (Task 8), not tuned constants -- no data exists yet to tune
    them against.
    """

    min_score: float = 0.5
    resample_seconds: float = 30.0


class RelevanceFilter:
    """Suppresses low-value repeated detections.

    In-memory only and deliberately not persisted: on restart the first
    sighting of each class is recorded again, which is the safe direction
    to err (an extra honest observation, never a suppressed real one).
    """

    def __init__(self, policy: RelevancePolicy) -> None:
        self._policy = policy
        self._last_recorded_at: dict[str, float] = {}

    def should_record(self, object_class: str, score: float, now: float) -> bool:
        if score < self._policy.min_score:
            return False
        previous = self._last_recorded_at.get(object_class)
        if previous is None:
            return True
        return (now - previous) >= self._policy.resample_seconds

    def note_recorded(self, object_class: str, now: float) -> None:
        self._last_recorded_at[object_class] = now
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_object_memory_relevance.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add tower/object_memory/relevance.py tests/test_object_memory_relevance.py
git commit -m "feat: add Object Memory relevance filter"
```

---

### Task 3: JSONL store with retention and real purge

`06-PRIVACY-DATA.md` makes a working purge a **hard prerequisite**, not a
nice-to-have. Storage technology is JSONL per
`2026-08-20-canonical-memory-architecture.md` ("start with the simplest
thing that works … move to SQLite + sqlite-vec only once actually measured
necessary").

**Files:**
- Create: `tower/object_memory/store.py`
- Test: `tests/test_object_memory_store.py`

**Interfaces:**
- Consumes: `ObjectObservation`, `object_observation_from_json_dict` (Task 1).
- Produces: `class ObservationStore` with:
  - `__init__(self, directory: Path, retention_seconds: float | None) -> None`
  - `append(self, observation: ObjectObservation) -> None`
  - `all_observations(self) -> list[ObjectObservation]`
  - `last_seen(self, object_class: str) -> ObjectObservation | None`
  - `purge(self) -> int` — returns count deleted; real file deletion
  - `prune_expired(self, now: float) -> int` — returns count removed

- [ ] **Step 1: Write the failing test**

```python
# tests/test_object_memory_store.py
from tower.object_memory.records import Confidence, ObjectObservation
from tower.object_memory.store import ObservationStore


def _observation(object_class="keys", observed_at=1000.0) -> ObjectObservation:
    return ObjectObservation(
        object_class=object_class,
        detector_score=0.9,
        confidence=Confidence.HIGH,
        observed_at=observed_at,
        recorded_at=observed_at,
        source="glasses-camera",
        module_id="object-memory",
        session_id=None,
        frame_seq=None,
        bounding_box=None,
        retention_tag="default",
        privacy_tags=("derived-only",),
        spatial_ref=None,
        external_refs=(),
    )


def test_appended_observation_is_readable_back(tmp_path):
    store = ObservationStore(tmp_path, retention_seconds=None)

    store.append(_observation())

    assert store.all_observations() == [_observation()]


def test_last_seen_returns_most_recent_observation_of_that_class(tmp_path):
    store = ObservationStore(tmp_path, retention_seconds=None)
    store.append(_observation("keys", observed_at=100.0))
    store.append(_observation("keys", observed_at=300.0))
    store.append(_observation("backpack", observed_at=200.0))

    assert store.last_seen("keys").observed_at == 300.0


def test_last_seen_returns_none_for_never_observed_class(tmp_path):
    # Absence of observation is not observation of absence -- the caller
    # must be able to tell "no record" apart from "record says absent".
    store = ObservationStore(tmp_path, retention_seconds=None)

    assert store.last_seen("charger") is None


def test_purge_really_deletes_the_backing_file(tmp_path):
    store = ObservationStore(tmp_path, retention_seconds=None)
    store.append(_observation())

    deleted = store.purge()

    assert deleted == 1
    assert store.all_observations() == []
    assert not any(tmp_path.iterdir())


def test_prune_expired_removes_only_observations_past_retention(tmp_path):
    store = ObservationStore(tmp_path, retention_seconds=100.0)
    store.append(_observation("old", observed_at=0.0))
    store.append(_observation("new", observed_at=950.0))

    removed = store.prune_expired(now=1000.0)

    assert removed == 1
    assert [o.object_class for o in store.all_observations()] == ["new"]


def test_store_survives_a_corrupt_line_without_losing_good_records(tmp_path):
    store = ObservationStore(tmp_path, retention_seconds=None)
    store.append(_observation())
    (tmp_path / "observations.jsonl").open("a", encoding="utf-8").write("{not json\n")

    assert len(store.all_observations()) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_object_memory_store.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'tower.object_memory.store'`

- [ ] **Step 3: Write minimal implementation**

```python
# tower/object_memory/store.py
import json
import logging
from pathlib import Path

from tower.object_memory.records import (
    ObjectObservation,
    object_observation_from_json_dict,
)

logger = logging.getLogger(__name__)

OBSERVATIONS_FILENAME = "observations.jsonl"


class ObservationStore:
    """Append-only JSONL store for one module's observations.

    JSONL, not SQLite: at V1 scale a single module's observation history is
    small, and the canonical-memory research explicitly sequences SQLite +
    sqlite-vec behind a measured need. Rewriting this file wholesale during
    prune/purge is acceptable precisely because the file is expected to stay
    small; that assumption is the trigger to revisit, and Task 8 measures it.
    """

    def __init__(self, directory: Path, retention_seconds: float | None) -> None:
        self._directory = Path(directory)
        self._retention_seconds = retention_seconds
        self._path = self._directory / OBSERVATIONS_FILENAME

    def append(self, observation: ObjectObservation) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(observation.to_json_dict()) + "\n")

    def all_observations(self) -> list[ObjectObservation]:
        if not self._path.exists():
            return []
        observations = []
        with self._path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    observations.append(
                        object_observation_from_json_dict(json.loads(line))
                    )
                except (json.JSONDecodeError, KeyError, ValueError):
                    # A corrupt line must not make the whole history
                    # unreadable -- losing one record is strictly better
                    # than losing the store.
                    logger.warning(
                        "object memory: skipping unreadable record at %s:%s",
                        self._path,
                        line_number,
                    )
        return observations

    def last_seen(self, object_class: str) -> ObjectObservation | None:
        matching = [
            o for o in self.all_observations() if o.object_class == object_class
        ]
        if not matching:
            return None
        return max(matching, key=lambda o: o.observed_at)

    def purge(self) -> int:
        count = len(self.all_observations())
        if self._path.exists():
            self._path.unlink()
        return count

    def prune_expired(self, now: float) -> int:
        if self._retention_seconds is None:
            return 0
        observations = self.all_observations()
        cutoff = now - self._retention_seconds
        kept = [o for o in observations if o.observed_at >= cutoff]
        removed = len(observations) - len(kept)
        if removed:
            self._rewrite(kept)
        return removed

    def _rewrite(self, observations: list[ObjectObservation]) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".jsonl.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            for observation in observations:
                handle.write(json.dumps(observation.to_json_dict()) + "\n")
        temporary.replace(self._path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_object_memory_store.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: `129 passed, 3 skipped`

- [ ] **Step 6: Commit**

```bash
git add tower/object_memory/store.py tests/test_object_memory_store.py
git commit -m "feat: add Object Memory JSONL store with retention and purge"
```

---

### Task 4: ⛔ DECISION GATE — detector loading and the lifecycle-timeout gap

> **STOP. Do not write code for this task without an explicit user ruling.**

**The issue.** `ModuleContainer` bounds every lifecycle call with
`asyncio.wait_for(..., LIFECYCLE_TIMEOUT_S)`
(`tower/modules/container.py:40-53`). That timeout **cannot interrupt a
synchronous blocking call inside `_do_load()`** — `asyncio.wait_for` can
only cancel at an await point, and a blocking C/IO call never yields one.
`DepthEstimationModule` already has this gap: its `_do_load()` calls
`torch.hub.load(...)`, which touches the network synchronously
(`docs/superpowers/research/2026-08-20-testing-reliability-techdebt-audit.md`
§3a).

**Why it lands here.** Object Memory's `_do_load()` must load a torchvision
detector — synchronous, and on first run it **downloads weights over the
network**. Writing it the obvious way silently reproduces the exact same
unbounded-blocking gap in a second module, turning a one-off into a
pattern.

**Why this is not an autonomous call.** Master Guide §9 classifies the
lifecycle-timeout gap as **"needs user judgment"**, and §17 STRETCH item 6
says explicitly: if this comes up, "treat it as a 'needs user judgment'
item per §22, not a silent copy of the existing gap." The fix changes the
lifecycle contract's *execution model*, which is an architecture decision,
not a bugfix.

**Options for the user:**

| Option | What it means | Cost / risk |
|---|---|---|
| **A. `asyncio.to_thread` in this module only** | `await asyncio.to_thread(self._detector.load, device)` — makes the load genuinely awaitable, so `wait_for` can actually bound it. | Smallest change; real timeout enforcement. But the module is then cancelled while a thread keeps running — the orphaned thread finishes the download and is discarded. Needs `_do_release()` to be safe against a partially-loaded detector. Leaves `DepthEstimationModule` inconsistent with it. |
| **B. Fix the contract centrally** | Make `Module.load()` (or `ModuleContainer`) run `_do_load` via `to_thread` for all modules. | Consistent; fixes depth too. Larger blast radius — touches the shared lifecycle contract every module depends on, and `V1.1` is the milestone that owns lifecycle hardening. |
| **C. Pre-provision weights, accept the gap** | Document that weights must be downloaded before first run; leave loading synchronous. | Zero architectural change. Does not fix anything — just moves the hazard to an operational precondition. |
| **D. Defer Object Memory** | Do V1.1 lifecycle hardening first, then build this module on the fixed contract. | Cleanest ordering; costs the most schedule time. |

**Recommendation (not a decision):** **A** for this slice, with a code
comment pointing at this gate and at the techdebt audit, because it is
local, reversible, and does not touch the shared contract mid-milestone —
then **B** as part of V1.1 where lifecycle hardening actually belongs. But
this is the user's call.

- [ ] **Step 1: Obtain and record the user's ruling** in this file, with
      date and reasoning, before proceeding.
- [ ] **Step 2: Implement the chosen option**, then continue to Task 5.

---

### Task 5: Detector wrapper

**Blocked by Task 4.** Written assuming ruling **A**; adapt if the user
chooses otherwise.

**Files:**
- Create: `tower/object_memory/detector.py`
- Test: `tests/test_object_memory_detector_integration.py` (opt-in)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `class ObjectDetector` with:
  - `__init__(self) -> None`
  - `load(self, device: str) -> None`
  - `run(self, raw_bytes: bytes) -> list[tuple[str, float, tuple[float, float, float, float]]]`
    returning `(coco_label, score, (x1, y1, x2, y2))`
  - `release(self) -> None`

Mirror `tower/experiments/depth.py` exactly for: local torch import,
`StageTimer` usage, `FrameProcessingError` on an undecodable frame, CUDA
memory logging, and `release()` being safe after a partial load.

- [ ] **Step 1: Write the failing opt-in integration test**

```python
# tests/test_object_memory_detector_integration.py
import io
import os

import pytest
from PIL import Image

from tower.object_memory.detector import ObjectDetector

pytestmark = pytest.mark.skipif(
    os.environ.get("TOWER_RUN_MODEL_TESTS") != "1",
    reason="opt-in: requires a real torch/torchvision install and a "
    "detector weight download on first run; set TOWER_RUN_MODEL_TESTS=1",
)


def _jpeg_bytes(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color=(120, 130, 140)).save(buffer, format="JPEG")
    return buffer.getvalue()


def test_detector_returns_well_formed_detections():
    detector = ObjectDetector()
    detector.load("cpu")
    try:
        detections = detector.run(_jpeg_bytes(320, 320))
    finally:
        detector.release()

    assert isinstance(detections, list)
    for label, score, box in detections:
        assert isinstance(label, str) and label
        assert 0.0 <= score <= 1.0
        assert len(box) == 4


def test_release_is_safe_without_a_successful_load():
    ObjectDetector().release()  # must not raise
```

- [ ] **Step 2: Run to verify it fails**

Run: `TOWER_RUN_MODEL_TESTS=1 python -m pytest tests/test_object_memory_detector_integration.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'tower.object_memory.detector'`

- [ ] **Step 3: Write the implementation**

```python
# tower/object_memory/detector.py
import logging
import time

import cv2
import numpy as np

from tower.modules.base import FrameProcessingError

logger = logging.getLogger(__name__)

# Pinned explicitly rather than via a default/alias: a floating weights
# selection is a reproducibility risk for any measured result, exactly as
# the V0.9.1 MiDaS torch.hub ref pin established.
WEIGHTS_NAME = "COCO_V1"


class ObjectDetector:
    """COCO-pretrained torchvision detector.

    torchvision, not ultralytics/YOLO: torchvision is already installed via
    the ml extra, so this adds no dependency and no AGPL obligation. Revisit
    only if measured accuracy on real glasses footage proves inadequate.
    """

    def __init__(self) -> None:
        self._model = None
        self._weights = None
        self._device = None

    def load(self, device: str) -> None:
        import torch
        from torchvision.models.detection import (
            SSDLite320_MobileNet_V3_Large_Weights,
            ssdlite320_mobilenet_v3_large,
        )

        start = time.perf_counter()
        self._device = torch.device(device)
        self._weights = getattr(SSDLite320_MobileNet_V3_Large_Weights, WEIGHTS_NAME)
        self._model = ssdlite320_mobilenet_v3_large(weights=self._weights)
        self._model.to(self._device)
        self._model.eval()
        load_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "[Tower][Module] object detector loaded on %s in %.1fms (torch %s)",
            self._device,
            load_ms,
            torch.__version__,
        )

    def release(self) -> None:
        is_cuda = self._device is not None and self._device.type == "cuda"
        if is_cuda:
            import torch

            peak_mb = torch.cuda.max_memory_allocated() / (1024 * 1024)

        self._model = None
        self._weights = None
        self._device = None

        if is_cuda:
            torch.cuda.empty_cache()
            logger.info(
                "[Tower][Module] object detector released; peak cuda allocation %.1fMB",
                peak_mb,
            )

    def run(self, raw_bytes: bytes) -> list[tuple[str, float, tuple[float, float, float, float]]]:
        array = np.frombuffer(raw_bytes, dtype=np.uint8)
        image = cv2.imdecode(array, cv2.IMREAD_COLOR)
        if image is None:
            raise FrameProcessingError("undecodable frame")

        import torch

        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        tensor = torch.from_numpy(image_rgb).permute(2, 0, 1).float().div(255.0)
        tensor = tensor.to(self._device)

        with torch.inference_mode():
            predictions = self._model([tensor])[0]

        categories = self._weights.meta["categories"]
        detections = []
        for label_index, score, box in zip(
            predictions["labels"].tolist(),
            predictions["scores"].tolist(),
            predictions["boxes"].tolist(),
        ):
            detections.append((categories[label_index], float(score), tuple(box)))
        return detections
```

- [ ] **Step 4: Run to verify it passes**

Run: `TOWER_RUN_MODEL_TESTS=1 python -m pytest tests/test_object_memory_detector_integration.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Confirm the default suite still skips it**

Run: `python -m pytest -q`
Expected: `129 passed, 5 skipped` (the 3 existing depth skips + 2 new)

- [ ] **Step 6: Commit**

```bash
git add tower/object_memory/detector.py tests/test_object_memory_detector_integration.py
git commit -m "feat: add Object Memory torchvision detector wrapper"
```

---

### Task 6: The Module itself

**Files:**
- Create: `tower/modules/object_memory.py`
- Test: `tests/test_object_memory_module.py`

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces:
  - `DESCRIPTOR: ModuleDescriptor` with `id="object-memory"`,
    `data_behavior=ModuleDataBehavior(persists_data=True,
    retains_raw_imagery=False, retention="configurable",
    supports_purge=True, transmits_externally=False)`.
  - `class ObjectMemoryModule(Module)` with
    `__init__(self, device: str, store: ObservationStore, relevance: RelevanceFilter, detector: ObjectDetector | None = None)`.
  - `ObjectMemoryModule.last_seen(self, object_class: str) -> ObjectObservation | None`
  - `ObjectMemoryModule.purge(self) -> int`

`_do_process` returns an `ExperimentResult` so the existing
`ws.py`/`frame_result` path needs **no change**: `result_label
= "objects_recorded"`, `result_value` = count persisted for that frame.
Reusing the envelope is deliberate — generalizing the output contract is
V1.0 work, triggered by a real second-module need, not pre-built here.

Note the descriptor's `persists_data=True` — this is the **first** module
in the platform to declare it, which is exactly why the purge path in
Task 3 had to exist first.

- [ ] **Step 1: Write the failing test** (uses a fake detector — no torch)

```python
# tests/test_object_memory_module.py
import asyncio

from tower.modules.base import ModuleState
from tower.modules.container import ModuleContainer
from tower.modules.object_memory import ObjectMemoryModule
from tower.object_memory.relevance import RelevanceFilter, RelevancePolicy
from tower.object_memory.store import ObservationStore


class _FakeDetector:
    def __init__(self, detections):
        self.detections = detections
        self.released = False

    def load(self, device):
        return None

    def run(self, raw_bytes):
        return self.detections

    def release(self):
        self.released = True


def _module(tmp_path, detections):
    return ObjectMemoryModule(
        device="cpu",
        store=ObservationStore(tmp_path, retention_seconds=None),
        relevance=RelevanceFilter(RelevancePolicy(min_score=0.5)),
        detector=_FakeDetector(detections),
    )


def test_confident_detection_is_persisted_as_an_observation(tmp_path):
    module = _module(tmp_path, [("keys", 0.9, (0.0, 0.0, 1.0, 1.0))])
    asyncio.run(module.load())
    asyncio.run(module.start())

    result = module.process(b"frame-bytes")

    assert result.result_label == "objects_recorded"
    assert result.result_value == 1.0
    assert module.last_seen("keys").object_class == "keys"


def test_low_confidence_detection_is_not_persisted(tmp_path):
    module = _module(tmp_path, [("keys", 0.10, (0.0, 0.0, 1.0, 1.0))])
    asyncio.run(module.load())
    asyncio.run(module.start())

    result = module.process(b"frame-bytes")

    assert result.result_value == 0.0
    assert module.last_seen("keys") is None


def test_descriptor_declares_persistence_and_purge_truthfully(tmp_path):
    module = _module(tmp_path, [])

    behavior = module.descriptor.data_behavior

    assert behavior.persists_data is True
    assert behavior.retains_raw_imagery is False
    assert behavior.supports_purge is True
    assert behavior.transmits_externally is False


def test_purge_removes_everything_the_module_stored(tmp_path):
    module = _module(tmp_path, [("keys", 0.9, (0.0, 0.0, 1.0, 1.0))])
    asyncio.run(module.load())
    asyncio.run(module.start())
    module.process(b"frame-bytes")

    assert module.purge() == 1
    assert module.last_seen("keys") is None


def test_module_runs_through_the_container_lifecycle(tmp_path):
    container = ModuleContainer(_module(tmp_path, []))

    asyncio.run(container.load_and_start())

    assert container.state == ModuleState.ACTIVE
    asyncio.run(container.shutdown())
    assert container.state == ModuleState.UNLOADED
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_object_memory_module.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'tower.modules.object_memory'`

- [ ] **Step 3: Write the implementation**

```python
# tower/modules/object_memory.py
import time

from tower.experiments import ExperimentResult
from tower.instrumentation import StageTimer
from tower.modules.base import Module, ModuleDataBehavior, ModuleDescriptor
from tower.object_memory.detector import ObjectDetector
from tower.object_memory.records import Confidence, ObjectObservation
from tower.object_memory.relevance import RelevanceFilter
from tower.object_memory.store import ObservationStore

DESCRIPTOR = ModuleDescriptor(
    id="object-memory",
    name="Object Memory",
    version="0.1.0",
    data_behavior=ModuleDataBehavior(
        persists_data=True,
        retains_raw_imagery=False,
        retention="configurable",
        supports_purge=True,
        transmits_externally=False,
    ),
)

SOURCE = "glasses-camera"


class ObjectMemoryModule(Module):
    """First module in the platform that actually persists data.

    Records that a COCO *category* was visible at a time, never that a
    specific instance is present now (OBJECT-MEMORY.md, Identity vs.
    Category; 07-PLATFORM-CONSTRAINTS.md Core Principle 3).
    """

    descriptor = DESCRIPTOR

    def __init__(
        self,
        device: str,
        store: ObservationStore,
        relevance: RelevanceFilter,
        detector: ObjectDetector | None = None,
    ) -> None:
        super().__init__()
        self._device = device
        self._store = store
        self._relevance = relevance
        self._detector = detector if detector is not None else ObjectDetector()

    async def _do_load(self) -> None:
        # See docs/superpowers/plans/2026-08-20-object-memory-first-slice.md
        # Task 4 (DECISION GATE) for why this is not a bare synchronous call.
        import asyncio

        await asyncio.to_thread(self._detector.load, self._device)

    async def _do_start(self) -> None:
        return None

    def _do_process(self, observation: bytes) -> ExperimentResult:
        timer = StageTimer()
        with timer.stage("detect"):
            detections = self._detector.run(observation)

        with timer.stage("persist"):
            now = time.time()
            recorded = 0
            for object_class, score, box in detections:
                if not self._relevance.should_record(object_class, score, now):
                    continue
                self._store.append(
                    ObjectObservation(
                        object_class=object_class,
                        detector_score=score,
                        confidence=Confidence.from_score(score),
                        observed_at=now,
                        recorded_at=time.time(),
                        source=SOURCE,
                        module_id=DESCRIPTOR.id,
                        session_id=None,
                        frame_seq=None,
                        bounding_box=box,
                        retention_tag="default",
                        privacy_tags=("derived-only",),
                        spatial_ref=None,
                        external_refs=(),
                    )
                )
                self._relevance.note_recorded(object_class, now)
                recorded += 1

        return ExperimentResult(
            result_value=float(recorded),
            result_label="objects_recorded",
            processing_ms=timer.total_ms,
            stage_ms=timer.snapshot(),
        )

    async def _do_stop(self) -> None:
        return None

    async def _do_unload(self) -> None:
        self._detector.release()

    def _do_release(self) -> None:
        self._detector.release()

    def last_seen(self, object_class: str) -> ObjectObservation | None:
        return self._store.last_seen(object_class)

    def purge(self) -> int:
        return self._store.purge()
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_object_memory_module.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add tower/modules/object_memory.py tests/test_object_memory_module.py
git commit -m "feat: add ObjectMemoryModule with persistence and purge"
```

---

### Task 7: Wiring and query/purge endpoints

**Files:**
- Modify: `tower/config.py`
- Modify: `tower/main.py:15-20`
- Create: `tower/routes/object_memory.py`
- Test: `tests/test_object_memory_routes.py`

**Interfaces:**
- Consumes: `ObjectMemoryModule` (Task 6).
- Produces:
  - `Settings` gains `module: str` (`TOWER_MODULE`, default `"experimental-cv"`),
    `object_memory_dir: str` (`TOWER_OBJECT_MEMORY_DIR`, default
    `"data/object_memory"`), `object_memory_retention_s: float | None`
    (`TOWER_OBJECT_MEMORY_RETENTION_S`, default `None` = keep until purged).
  - `GET /object-memory/last-seen/{object_class}` →
    `{"object_class": str, "observed": bool, "observation": dict | None}`
  - `POST /object-memory/purge` → `{"deleted": int}`

`TOWER_MODULE` is a deliberate minimum: it selects between the two modules
that exist without building discovery, a registry, or descriptor
negotiation. That generalization is V1.0, triggered *by* this module
existing — building it now would be the speculative generalization Rule 10
prohibits.

The `observed: false` field matters: it lets a caller distinguish "we have
no record" from "the object is gone." Returning bare `null` would invite
exactly the absence-of-observation-as-observation-of-absence error Core
Principle 3 forbids.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_object_memory_routes.py
import asyncio

from fastapi.testclient import TestClient

from tower.main import create_app


def test_last_seen_reports_not_observed_for_unknown_class(monkeypatch, tmp_path):
    monkeypatch.setenv("TOWER_MODULE", "object-memory")
    monkeypatch.setenv("TOWER_OBJECT_MEMORY_DIR", str(tmp_path))
    client = TestClient(create_app())

    response = client.get("/object-memory/last-seen/charger")

    assert response.status_code == 200
    assert response.json() == {
        "object_class": "charger",
        "observed": False,
        "observation": None,
    }


def test_purge_endpoint_reports_deleted_count(monkeypatch, tmp_path):
    monkeypatch.setenv("TOWER_MODULE", "object-memory")
    monkeypatch.setenv("TOWER_OBJECT_MEMORY_DIR", str(tmp_path))
    client = TestClient(create_app())

    response = client.post("/object-memory/purge")

    assert response.status_code == 200
    assert response.json() == {"deleted": 0}


def test_health_reports_the_object_memory_descriptor(monkeypatch, tmp_path):
    monkeypatch.setenv("TOWER_MODULE", "object-memory")
    monkeypatch.setenv("TOWER_OBJECT_MEMORY_DIR", str(tmp_path))
    client = TestClient(create_app())

    assert client.get("/health").json()["module_id"] == "object-memory"
```

> **Note for the executor:** these tests construct the real module, so with
> ruling **A** they will load a real detector. If that makes the default
> suite slow or network-dependent, gate these three tests behind
> `TOWER_RUN_MODEL_TESTS=1` exactly like the detector tests, rather than
> weakening the assertions. Do not mock `create_app`'s internals.

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_object_memory_routes.py -q`
Expected: FAIL — 404 on both endpoints (routes not registered)

- [ ] **Step 3: Extend settings**

```python
# tower/config.py -- add to Settings and get_settings
    module: str
    object_memory_dir: str
    object_memory_retention_s: float | None
```

```python
        module=os.environ.get("TOWER_MODULE", "experimental-cv"),
        object_memory_dir=os.environ.get(
            "TOWER_OBJECT_MEMORY_DIR", "data/object_memory"
        ),
        object_memory_retention_s=(
            float(os.environ["TOWER_OBJECT_MEMORY_RETENTION_S"])
            if os.environ.get("TOWER_OBJECT_MEMORY_RETENTION_S")
            else None
        ),
```

- [ ] **Step 4: Add the routes**

```python
# tower/routes/object_memory.py
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/object-memory")


def _module(request: Request):
    module = request.app.state.module_container._module
    if module.descriptor.id != "object-memory":
        raise HTTPException(status_code=404, detail="object memory module is not active")
    return module


@router.get("/last-seen/{object_class}")
def last_seen(object_class: str, request: Request) -> dict:
    observation = _module(request).last_seen(object_class)
    return {
        "object_class": object_class,
        # Explicit: "we have no record" is not "the object is absent".
        "observed": observation is not None,
        "observation": observation.to_json_dict() if observation else None,
    }


@router.post("/purge")
def purge(request: Request) -> dict:
    return {"deleted": _module(request).purge()}
```

- [ ] **Step 5: Wire it up in `main.py`**

```python
def _build_cv_module(settings: Settings) -> Module:
    if settings.module == "object-memory":
        from pathlib import Path

        from tower.modules.object_memory import ObjectMemoryModule
        from tower.object_memory.relevance import RelevanceFilter, RelevancePolicy
        from tower.object_memory.store import ObservationStore

        return ObjectMemoryModule(
            device=settings.cv_device,
            store=ObservationStore(
                Path(settings.object_memory_dir),
                retention_seconds=settings.object_memory_retention_s,
            ),
            relevance=RelevanceFilter(RelevancePolicy()),
        )
    if settings.cv_experiment == "depth":
        from tower.modules.depth_cv import DepthEstimationModule

        return DepthEstimationModule(settings.cv_device)
    return ExperimentalCVModule(settings.cv_experiment)
```

Also add `app.include_router(object_memory.router)` next to the existing
router registrations, and import it alongside `health, ws`.

- [ ] **Step 6: Extend conftest**

`tests/conftest.py` must also clear `TOWER_MODULE` and
`TOWER_OBJECT_MEMORY_DIR` at import time and in the autouse fixture — same
reason the existing entries exist: `tower/main.py`'s module-level
`app = create_app()` runs at import, before any fixture.

- [ ] **Step 7: Run to verify it passes**

Run: `python -m pytest tests/test_object_memory_routes.py -q`
Expected: PASS (3 passed)

- [ ] **Step 8: Run the full suite**

Run: `python -m pytest -q`
Expected: all green, no unexplained skips

- [ ] **Step 9: Commit**

```bash
git add tower/config.py tower/main.py tower/routes/object_memory.py tests/test_object_memory_routes.py tests/conftest.py
git commit -m "feat: wire Object Memory module and query/purge endpoints"
```

---

### Task 8: Measured report

`OBJECT-MEMORY.md`'s First-Version Success Criteria items 5 and 6 require
*measured* precision/recall-or-retrieval-accuracy and *measured* resource
usage. Per Rule 3 and `EXPERIMENTAL-CV.md`, the milestone is not done
without real numbers.

**Files:**
- Create: `scripts/object_memory_benchmark.py`
- Create: `guidelines/docs/reports/V1.2-object-memory-first-slice-report.md`
- Modify: `README.md`, `guidelines/docs/03-ROADMAP.md`

- [ ] **Step 1: Write the benchmark script**, following
      `scripts/depth_benchmark.py`'s established shape: per-stage timing via
      `StageTimer`, CPU vs CUDA runs, first-frame excluded from steady-state
      averages. Accept `--video` so it can run against the same footage the
      World Builder harnesses use.

- [ ] **Step 2: Run it on CPU and CUDA**, capturing real numbers for:
      detect/persist stage times, end-to-end per-frame cost, observations
      persisted per minute, store size growth, peak GPU memory.

- [ ] **Step 3: Measure retrieval honestly.** Hand-label which COCO
      categories genuinely appear in a short clip, then compare against what
      the module recorded. Report precision/recall as measured — including
      if they are poor. A bad measured number is a valid result; an
      unmeasured claim is not.

- [ ] **Step 4: Write the report** using
      `V0.9.1-depth-cv-baseline-report.md`'s structure (Success Criteria,
      Run metadata, Measured, Conclusion). **If any measurement used dataset
      footage rather than real glasses footage, carry the same
      validity-scope box and acceptance gate used in
      `V0.9.3-world-builder-experiments-1-2-report.md`.**

- [ ] **Step 5: Update README + roadmap** only if the milestone genuinely
      completed (Master Guide §25).

- [ ] **Step 6: Commit**

---

## Self-Review

**Spec coverage against `OBJECT-MEMORY.md`:**

| Spec section | Covered by |
|---|---|
| Goal / "where did I last see X" | Task 3 `last_seen`, Task 7 endpoint |
| Intended Inputs | Task 6 (`camera frames`, timestamps); voice/spatial explicitly deferred |
| Sensor Profile Hypothesis | **Not covered** — no settings-negotiation mechanism exists platform-wide; that is V1.0. Flagged, not silently skipped. |
| Core CV Pipeline | Tasks 5–6 (detector → observation builder → relevance → persistence). **Tracker deliberately excluded** — documented in Scope. |
| Relevance | Task 2 (new-object + resampling only; the other four event types need a tracker) |
| Identity vs. Category | Enforced by omission — category only; documented in the module docstring |
| Persistence | Task 3 |
| Query Layer | Task 7 (`last_seen` only; `seen_today`/`history`/`recent_objects` deferred, LLM excluded) |
| Output / uncertainty | Task 1 `Confidence`, Task 7 `observed: bool` |
| Failure Behavior | Task 6 (`FrameProcessingError` → frame skipped, module stays ACTIVE via existing container logic) |
| Privacy | Global Constraints + Task 3 (`derived-only`, no crops, real purge, configurable retention) |
| First-Version Success Criteria 1–4 | Tasks 5–7 |
| First-Version Success Criteria 5–6 | Task 8 |

**Known gaps a reviewer should weigh in on:**
1. **Sensor Profile** has no home in the current architecture — correctly
   V1.0 work, but it means this module cannot request 5–15 FPS or a
   resolution; it takes whatever the stream sends.
2. **`session_id`/`frame_seq` are populated as `None`** in Task 6 because
   `_do_process` receives only `raw_bytes` — the module contract passes no
   frame metadata. Threading it through is a real (small) contract change
   and is intentionally *not* smuggled into this plan. It connects directly
   to the Master Guide §7 item 3 `source_seq`/`tx_seq` work.
3. **Retention pruning is never called** by any task — `prune_expired`
   exists and is tested, but nothing schedules it. Wiring it (on load? on
   append? on a timer?) is a real design choice deferred to review rather
   than guessed.

**Placeholder scan:** none — every code step contains runnable code, and
Task 4's "gate" is a deliberate decision point with concrete options, not a
vague TODO.

**Type consistency:** `ObservationStore`, `RelevanceFilter`,
`RelevancePolicy`, `ObjectDetector`, `ObjectObservation`, `Confidence`, and
`ObjectMemoryModule` are spelled identically across Tasks 1–8;
`last_seen`/`purge`/`prune_expired`/`should_record`/`note_recorded`
signatures match between definition and use.

---

## Execution Handoff

**Do not execute yet.** This plan's Task 4 requires a user ruling, and the
Master Guide gates Object Memory implementation on review of this plan.

When authorized, the recommended approach is
**superpowers:subagent-driven-development**: a fresh subagent per task with
review between tasks. Tasks 1–3 are independent of the Task 4 gate and
could proceed first if the user wants progress while deciding.
