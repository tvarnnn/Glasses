import json

import pytest

from tower.object_memory.records import Confidence, ObjectObservation
from tower.object_memory.store import OBSERVATIONS_FILENAME, ObservationStore


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


def _raw_record(**overrides) -> dict:
    # A hand-built raw dict, not routed through ObjectObservation, so
    # tests can construct records this version's schema cannot parse
    # (e.g. an unrecognised confidence label) while still being valid
    # JSON -- the distinction FIX 2 depends on.
    raw = dict(
        object_class="widget",
        detector_score=0.5,
        confidence="high",
        observed_at=950.0,
        time_basis="tower-receipt",
        recorded_at=950.0,
        source="glasses-camera",
        module_id="object-memory",
        session_id=None,
        frame_seq=None,
        bounding_box=None,
        retention_tag="default",
        privacy_tags=[],
        spatial_ref=None,
        external_refs=[],
    )
    raw.update(overrides)
    return raw


def _write_raw_line(tmp_path, raw: dict) -> None:
    with (tmp_path / OBSERVATIONS_FILENAME).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(raw) + "\n")


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


def test_purge_returns_count_of_observations_not_corrupt_lines(tmp_path):
    # Finding 1: purge() returns count of parseable observations,
    # not total lines in the file. A corrupt line doesn't count.
    store = ObservationStore(tmp_path, retention_seconds=None)
    store.append(_observation())
    with (tmp_path / "observations.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")

    deleted = store.purge()

    assert deleted == 1  # Only the parseable observation counts
    assert store.all_observations() == []
    assert not any(tmp_path.iterdir())  # File is completely deleted


def test_prune_expired_cleans_corrupt_lines_even_when_nothing_expires(tmp_path):
    # Finding 2: with retention configured, corrupt lines are rewritten away
    # even if no valid records have expired.
    store = ObservationStore(tmp_path, retention_seconds=100.0)
    store.append(_observation("fresh", observed_at=950.0))
    with (tmp_path / "observations.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")

    removed = store.prune_expired(now=1000.0)

    assert removed == 0  # No valid observations removed
    assert [o.object_class for o in store.all_observations()] == ["fresh"]
    # Corrupt line is gone
    with (tmp_path / "observations.jsonl").open("r", encoding="utf-8") as handle:
        content = handle.read()
    assert "{not json" not in content


def test_prune_expired_removes_both_expired_obs_and_corrupt_lines(tmp_path):
    # Finding 2: when valid records expire, corrupt lines are also removed.
    store = ObservationStore(tmp_path, retention_seconds=100.0)
    store.append(_observation("old", observed_at=0.0))
    store.append(_observation("fresh", observed_at=950.0))
    with (tmp_path / "observations.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")

    removed = store.prune_expired(now=1000.0)

    assert removed == 1  # Only the expired valid observation
    assert [o.object_class for o in store.all_observations()] == ["fresh"]
    with (tmp_path / "observations.jsonl").open("r", encoding="utf-8") as handle:
        content = handle.read()
    assert "{not json" not in content


def test_prune_expired_with_none_retention_leaves_everything_untouched(tmp_path):
    # Finding 2: retention_seconds=None means "keep forever", so nothing
    # is touched, including corrupt lines.
    store = ObservationStore(tmp_path, retention_seconds=None)
    store.append(_observation("old", observed_at=0.0))
    with (tmp_path / "observations.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")

    # Read original file content
    with (tmp_path / "observations.jsonl").open("r", encoding="utf-8") as handle:
        original_content = handle.read()

    removed = store.prune_expired(now=1000.0)

    # File is untouched byte-for-byte
    with (tmp_path / "observations.jsonl").open("r", encoding="utf-8") as handle:
        new_content = handle.read()
    assert new_content == original_content
    assert removed == 0
    assert "{not json" in new_content


# --- FIX 1: purge() must remove every artifact the store owns ---


def test_purge_removes_a_stale_rewrite_temp_file(tmp_path):
    # A stale .tmp is what a crash mid-_rewrite leaves behind. Nothing
    # else ever reads or deletes it, so if purge() doesn't, it's a false
    # claim of deletion: real observation data survives on disk.
    store = ObservationStore(tmp_path, retention_seconds=None)
    store.append(_observation())
    temp_path = tmp_path / f"{OBSERVATIONS_FILENAME}.tmp"
    temp_path.write_text(
        json.dumps(_observation().to_json_dict()) + "\n", encoding="utf-8"
    )

    store.purge()

    assert not temp_path.exists()
    assert not any(tmp_path.iterdir())


# --- FIX 2: a valid-JSON schema mismatch must not be treated as garbage ---


def test_prune_expired_keeps_schema_mismatched_record_within_retention(tmp_path):
    store = ObservationStore(tmp_path, retention_seconds=100.0)
    _write_raw_line(
        tmp_path, _raw_record(confidence="impossible-label", recorded_at=950.0)
    )

    removed = store.prune_expired(now=1000.0)

    assert removed == 0
    with (tmp_path / OBSERVATIONS_FILENAME).open("r", encoding="utf-8") as handle:
        content = handle.read()
    assert "impossible-label" in content


def test_prune_expired_removes_schema_mismatched_record_when_expired(tmp_path):
    store = ObservationStore(tmp_path, retention_seconds=100.0)
    _write_raw_line(
        tmp_path, _raw_record(confidence="impossible-label", recorded_at=800.0)
    )

    removed = store.prune_expired(now=1000.0)

    assert removed == 1
    with (tmp_path / OBSERVATIONS_FILENAME).open("r", encoding="utf-8") as handle:
        content = handle.read()
    assert content == ""


def test_prune_expired_still_drops_truly_corrupt_json_lines(tmp_path):
    store = ObservationStore(tmp_path, retention_seconds=100.0)
    store.append(_observation("fresh", observed_at=950.0))
    with (tmp_path / OBSERVATIONS_FILENAME).open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")

    removed = store.prune_expired(now=1000.0)

    assert removed == 0  # the corrupt line was never a valid observation
    with (tmp_path / OBSERVATIONS_FILENAME).open("r", encoding="utf-8") as handle:
        content = handle.read()
    assert "{not json" not in content
    assert "fresh" in content


def test_prune_expired_preserves_unknown_extra_key(tmp_path):
    # records.py reserves fields so a future need doesn't require
    # rewriting persisted records. That promise only holds if prune
    # rewrites raw dicts rather than round-tripping through the current
    # ObjectObservation schema, which would silently drop the extra key.
    # An expired second record forces an actual rewrite to happen, so
    # this exercises the rewrite path rather than passing vacuously.
    store = ObservationStore(tmp_path, retention_seconds=100.0)
    store.append(_observation("old", observed_at=0.0))
    _write_raw_line(
        tmp_path,
        _raw_record(
            confidence="high",
            recorded_at=950.0,
            future_field="keep-me",
        ),
    )

    removed = store.prune_expired(now=1000.0)

    assert removed == 1  # only the truly-expired "old" record
    with (tmp_path / OBSERVATIONS_FILENAME).open("r", encoding="utf-8") as handle:
        content = handle.read()
    assert "keep-me" in content
    assert "old" not in content


def test_prune_expired_retention_seconds_none_still_short_circuits(tmp_path):
    store = ObservationStore(tmp_path, retention_seconds=None)
    _write_raw_line(tmp_path, _raw_record(confidence="impossible-label"))

    removed = store.prune_expired(now=1000.0)

    assert removed == 0


def test_negative_retention_seconds_is_rejected(tmp_path):
    # A negative retention puts the cutoff in the future, which would
    # delete everything on the first prune -- reject it up front instead.
    with pytest.raises(ValueError):
        ObservationStore(tmp_path, retention_seconds=-1.0)


# --- FIX 4: pin the load-bearing behaviours mutation testing missed ---


def test_prune_expired_cutoff_applies_to_recorded_at_not_observed_at(tmp_path):
    # observed_at is long expired but recorded_at (the privacy-relevant
    # clock) is not -- the record must survive.
    store = ObservationStore(tmp_path, retention_seconds=100.0)
    observation = ObjectObservation(
        object_class="keys",
        detector_score=0.9,
        confidence=Confidence.HIGH,
        observed_at=0.0,
        time_basis="tower-receipt",
        recorded_at=990.0,
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
    store.append(observation)

    removed = store.prune_expired(now=1000.0)

    assert removed == 0
    assert len(store.all_observations()) == 1


def test_last_seen_returns_newest_by_timestamp_when_appended_out_of_order(tmp_path):
    store = ObservationStore(tmp_path, retention_seconds=None)
    store.append(_observation("keys", observed_at=300.0))
    store.append(_observation("keys", observed_at=100.0))

    assert store.last_seen("keys").observed_at == 300.0
