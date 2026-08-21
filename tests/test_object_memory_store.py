from tower.object_memory.records import Confidence, ObjectObservation
from tower.object_memory.store import ObservationStore


def _observation(object_class="keys", observed_at=1000.0) -> ObjectObservation:
    return ObjectObservation(
        object_class=object_class,
        detector_score=0.9,
        confidence=Confidence.HIGH,
        observed_at=observed_at,
        time_basis="tower-receipt",
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
    # with-block, not a bare .open(...).write(...): the latter only
    # flushes because CPython refcounting closes the temporary
    # immediately, which is an implementation detail and emits a
    # ResourceWarning that would fail under filterwarnings=error.
    with (tmp_path / "observations.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")

    assert len(store.all_observations()) == 1
