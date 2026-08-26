import json

import pytest

from tower.object_memory.records import Confidence, ObjectObservation
from tower.object_memory.store import (
    DEFAULT_RETENTION_SECONDS,
    MANIFEST_FILENAME,
    OBSERVATIONS_FILENAME,
    ObservationStore,
)

# The placeholder labels these cases name their records with. append()
# refuses a class outside the persistable whitelist (see
# relevance.PERSISTED_CLASSES), and most of these cases are about
# retention and file handling rather than about the whitelist -- so they
# opt their fake classes in explicitly, exactly as an in-process caller
# with a custom RelevancePolicy would have to. The DEFAULT refusal is
# pinned separately, on a store built with no configuration at all.
TEST_CLASSES = (
    "keys",
    "backpack",
    "charger",
    "widget",
    "old",
    "new",
    "fresh",
    "ancient",
    "laptop",
    "cell phone",
)


def _store(directory, **kwargs):
    kwargs.setdefault("allowed_classes", TEST_CLASSES)
    return ObservationStore(directory, **kwargs)


def _observation(
    object_class="keys", observed_at=1000.0, best_score=None
) -> ObjectObservation:
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
        best_score=best_score,
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
    store = _store(tmp_path, retention_seconds=None)

    store.append(_observation())

    assert store.all_observations() == [_observation()]


def test_last_seen_returns_most_recent_observation_of_that_class(tmp_path):
    store = _store(tmp_path, retention_seconds=None)
    store.append(_observation("keys", observed_at=100.0))
    store.append(_observation("keys", observed_at=300.0))
    store.append(_observation("backpack", observed_at=200.0))

    assert store.last_seen("keys").observed_at == 300.0


def test_last_seen_returns_none_for_never_observed_class(tmp_path):
    # Absence of observation is not observation of absence -- the caller
    # must be able to tell "no record" apart from "record says absent".
    store = _store(tmp_path, retention_seconds=None)

    assert store.last_seen("charger") is None


def test_purge_really_deletes_the_backing_file(tmp_path):
    store = _store(tmp_path, retention_seconds=None)
    store.append(_observation())

    deleted = store.purge()

    assert deleted == 1
    assert store.all_observations() == []
    assert not any(tmp_path.iterdir())


def test_prune_expired_removes_only_observations_past_retention(tmp_path):
    store = _store(
        tmp_path, retention_seconds=100.0, clock=lambda: 1000.0
    )
    store.append(_observation("old", observed_at=0.0))
    store.append(_observation("new", observed_at=950.0))

    removed = store.prune_expired(now=1000.0)

    assert removed == 1
    assert [o.object_class for o in store.all_observations()] == ["new"]


def test_store_survives_a_corrupt_line_without_losing_good_records(tmp_path):
    store = _store(tmp_path, retention_seconds=None)
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
    store = _store(tmp_path, retention_seconds=None)
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
    store = _store(
        tmp_path, retention_seconds=100.0, clock=lambda: 1000.0
    )
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
    store = _store(
        tmp_path, retention_seconds=100.0, clock=lambda: 1000.0
    )
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
    store = _store(tmp_path, retention_seconds=None)
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
    store = _store(tmp_path, retention_seconds=None)
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
    store = _store(tmp_path, retention_seconds=100.0)
    _write_raw_line(
        tmp_path, _raw_record(confidence="impossible-label", recorded_at=950.0)
    )

    removed = store.prune_expired(now=1000.0)

    assert removed == 0
    with (tmp_path / OBSERVATIONS_FILENAME).open("r", encoding="utf-8") as handle:
        content = handle.read()
    assert "impossible-label" in content


def test_prune_expired_removes_schema_mismatched_record_when_expired(tmp_path):
    store = _store(tmp_path, retention_seconds=100.0)
    _write_raw_line(
        tmp_path, _raw_record(confidence="impossible-label", recorded_at=800.0)
    )

    removed = store.prune_expired(now=1000.0)

    assert removed == 1
    with (tmp_path / OBSERVATIONS_FILENAME).open("r", encoding="utf-8") as handle:
        content = handle.read()
    assert content == ""


def test_prune_expired_still_drops_truly_corrupt_json_lines(tmp_path):
    store = _store(tmp_path, retention_seconds=100.0)
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
    store = _store(tmp_path, retention_seconds=100.0)
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
    store = _store(tmp_path, retention_seconds=None)
    _write_raw_line(tmp_path, _raw_record(confidence="impossible-label"))

    removed = store.prune_expired(now=1000.0)

    assert removed == 0


def test_negative_retention_seconds_is_rejected(tmp_path):
    # A negative retention puts the cutoff in the future, which would
    # delete everything on the first prune -- reject it up front instead.
    with pytest.raises(ValueError):
        _store(tmp_path, retention_seconds=-1.0)


# --- FIX 4: pin the load-bearing behaviours mutation testing missed ---


def test_prune_expired_cutoff_applies_to_recorded_at_not_observed_at(tmp_path):
    # observed_at is long expired but recorded_at (the privacy-relevant
    # clock) is not -- the record must survive.
    store = _store(
        tmp_path, retention_seconds=100.0, clock=lambda: 1000.0
    )
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
    store = _store(tmp_path, retention_seconds=None)
    store.append(_observation("keys", observed_at=300.0))
    store.append(_observation("keys", observed_at=100.0))

    assert store.last_seen("keys").observed_at == 300.0


# --- FIX 5: retention is a promise about AVAILABILITY, not about disk ---
#
# all_observations()/last_seen() used to serve every line in the file
# regardless of age, so a reader on a long-running tower was handed
# expired observations indefinitely and the retention claim was only true
# for whoever happened to call prune_expired(). 06-PRIVACY-DATA.md makes
# retention a bound on how long data is AVAILABLE, so reads must apply it
# too. Filtering is the default; a caller has to ask for expired records
# by name.


def test_all_observations_hides_records_past_retention(tmp_path):
    store = _store(
        tmp_path, retention_seconds=100.0, clock=lambda: 1000.0
    )
    store.append(_observation("old", observed_at=0.0))
    store.append(_observation("fresh", observed_at=950.0))

    assert [o.object_class for o in store.all_observations()] == ["fresh"]


def test_last_seen_ignores_an_observation_past_retention(tmp_path):
    # The dangerous shape: the ONLY sighting of a class is expired, so an
    # unfiltered last_seen answers "your laptop was on the desk" from data
    # the wearer was promised had been forgotten.
    store = _store(
        tmp_path, retention_seconds=100.0, clock=lambda: 1000.0
    )
    store.append(_observation("laptop", observed_at=0.0))

    assert store.last_seen("laptop") is None


def test_last_seen_falls_back_to_the_newest_unexpired_sighting(tmp_path):
    store = _store(
        tmp_path, retention_seconds=100.0, clock=lambda: 1000.0
    )
    store.append(_observation("laptop", observed_at=0.0))
    store.append(_observation("laptop", observed_at=920.0))

    assert store.last_seen("laptop").observed_at == 920.0


def test_reads_are_unfiltered_when_retention_is_none(tmp_path):
    # "Keep forever" is a real setting, not an oversight -- with no
    # retention there is no cutoff and every record stays readable.
    store = _store(tmp_path, retention_seconds=None)
    store.append(_observation("ancient", observed_at=0.0))

    assert [o.object_class for o in store.all_observations()] == ["ancient"]


def test_a_caller_must_opt_out_of_the_retention_filter_by_name(tmp_path):
    # The opt-out exists for maintenance paths that must see what is
    # physically on disk. It is deliberately not the default.
    store = _store(
        tmp_path, retention_seconds=100.0, clock=lambda: 1000.0
    )
    store.append(_observation("old", observed_at=0.0))

    assert store.all_observations() == []
    assert len(store.all_observations(include_expired=True)) == 1
    assert store.last_seen("old") is None
    assert store.last_seen("old", include_expired=True) is not None


def test_read_filtering_uses_recorded_at_not_observed_at(tmp_path):
    # Same clock choice prune_expired documents: retention bounds how long
    # WE have held the record, not how old the sighting claims to be.
    store = _store(
        tmp_path, retention_seconds=100.0, clock=lambda: 1000.0
    )
    store.append(
        ObjectObservation(
            object_class="laptop",
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
    )

    assert len(store.all_observations()) == 1


def test_a_record_with_no_usable_recorded_at_is_not_served(tmp_path):
    # Matches prune_expired: a record that cannot be SHOWN to be within
    # retention is treated as expired rather than given the benefit of
    # the doubt.
    store = _store(
        tmp_path, retention_seconds=100.0, clock=lambda: 1000.0
    )
    _write_raw_line(tmp_path, _raw_record(recorded_at="not-a-number"))

    assert store.all_observations() == []


def test_purge_still_counts_and_deletes_expired_records(tmp_path):
    # purge() deletes the file outright, so it must count what it is
    # actually removing -- including records reads would no longer serve.
    store = _store(
        tmp_path, retention_seconds=100.0, clock=lambda: 1000.0
    )
    store.append(_observation("old", observed_at=0.0))
    store.append(_observation("fresh", observed_at=950.0))

    assert store.purge() == 2
    assert not any(tmp_path.iterdir())


def test_prune_expired_defaults_to_the_stores_own_clock(tmp_path):
    store = _store(
        tmp_path, retention_seconds=100.0, clock=lambda: 1000.0
    )
    store.append(_observation("old", observed_at=0.0))
    store.append(_observation("fresh", observed_at=950.0))

    assert store.prune_expired() == 1


# --- REVIEW FINDING 2: the whitelist must be enforced where disk is touched ---
#
# The closed whitelist lived only in RelevanceFilter, so
# `store.append(ObjectObservation(object_class="person", ...))` was
# accepted, written and read back. The engine being the only writer today
# is not a guarantee; it is a habit. The store is the last thing between a
# record and the disk, so the refusal belongs here too.


def test_append_refuses_a_class_this_slice_may_not_persist(tmp_path):
    store = ObservationStore(tmp_path, retention_seconds=None)

    with pytest.raises(ValueError):
        store.append(_observation("person"))

    assert not (tmp_path / OBSERVATIONS_FILENAME).exists()


def test_append_accepts_the_persisted_classes_with_no_configuration(tmp_path):
    store = ObservationStore(tmp_path, retention_seconds=None)

    store.append(_observation("laptop"))
    store.append(_observation("cell phone"))

    assert [o.object_class for o in store.all_observations()] == [
        "laptop",
        "cell phone",
    ]


def test_the_in_process_allowed_classes_knob_still_opens_the_store(tmp_path):
    # RelevancePolicy(allowed_classes=...) is documented and legitimate;
    # a caller using it has to hand the store the same list, which is the
    # point -- widening happens in one visible place, not by accident.
    store = ObservationStore(
        tmp_path, retention_seconds=None, allowed_classes=("widget",)
    )

    store.append(_observation("widget"))

    assert [o.object_class for o in store.all_observations()] == ["widget"]
    with pytest.raises(ValueError):
        store.append(_observation("laptop"))


# --- REVIEW FINDING 1: the window the store was WRITTEN under is the ceiling ---
#
# Nothing used to persist the producer's retention, so the READER was
# authoritative: `--retention-days 3650` against a store written under the
# 30-day default served a 40-day-old record in full. A promise a caller
# can opt out of by passing a flag is not a promise. The manifest records
# what was actually promised; every read clamps to
# min(persisted, requested), so a reader may narrow the window and can
# never widen it.

DAY = 86400.0


def _aged_store(tmp_path, *, written_under, age_days, now, object_class="laptop"):
    """A store written `age_days` ago under `written_under`, read at `now`."""
    recorded_at = now - age_days * DAY
    writer = ObservationStore(
        tmp_path,
        retention_seconds=written_under,
        clock=lambda: recorded_at,
        allowed_classes=TEST_CLASSES,
    )
    writer.append(_observation(object_class, observed_at=recorded_at))
    return recorded_at


def test_a_reader_cannot_widen_the_window_the_store_was_written_under(tmp_path):
    now = 1000 * DAY
    _aged_store(tmp_path, written_under=30 * DAY, age_days=40, now=now)

    reader = ObservationStore(
        tmp_path,
        retention_seconds=3650 * DAY,
        clock=lambda: now,
        allowed_classes=TEST_CLASSES,
    )

    assert reader.last_seen("laptop") is None
    assert reader.all_observations() == []


def test_a_reader_asking_to_keep_forever_cannot_widen_it_either(tmp_path):
    # `--retention-days 0` is the same hole wearing a different hat.
    now = 1000 * DAY
    _aged_store(tmp_path, written_under=30 * DAY, age_days=40, now=now)

    reader = ObservationStore(
        tmp_path,
        retention_seconds=None,
        clock=lambda: now,
        allowed_classes=TEST_CLASSES,
    )

    assert reader.last_seen("laptop") is None


def test_a_reader_may_narrow_the_window(tmp_path):
    # Narrowing is always allowed: it serves less, never more.
    now = 1000 * DAY
    _aged_store(tmp_path, written_under=30 * DAY, age_days=10, now=now)

    narrow = ObservationStore(
        tmp_path,
        retention_seconds=1 * DAY,
        clock=lambda: now,
        allowed_classes=TEST_CLASSES,
    )
    wide = ObservationStore(
        tmp_path,
        retention_seconds=30 * DAY,
        clock=lambda: now,
        allowed_classes=TEST_CLASSES,
    )

    assert narrow.last_seen("laptop") is None
    assert wide.last_seen("laptop") is not None


def test_the_manifest_records_the_window_at_first_append(tmp_path):
    store = ObservationStore(
        tmp_path, retention_seconds=30 * DAY, allowed_classes=TEST_CLASSES
    )
    assert not (tmp_path / MANIFEST_FILENAME).exists()

    store.append(_observation("laptop"))

    manifest = json.loads((tmp_path / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert manifest["retention_seconds"] == 30 * DAY


def test_a_producer_writing_under_a_narrower_window_tightens_the_manifest(tmp_path):
    # The manifest holds the tightest promise anything has written under.
    # A run told to keep 7 days has promised 7 days about what it writes,
    # and a later reader must not be handed 30.
    first = ObservationStore(
        tmp_path,
        retention_seconds=30 * DAY,
        clock=lambda: 0.0,
        allowed_classes=TEST_CLASSES,
    )
    first.append(_observation("laptop", observed_at=0.0))

    second = ObservationStore(
        tmp_path,
        retention_seconds=7 * DAY,
        clock=lambda: 1.0,
        allowed_classes=TEST_CLASSES,
    )
    second.append(_observation("laptop", observed_at=1.0))

    manifest = json.loads((tmp_path / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert manifest["retention_seconds"] == 7 * DAY
    assert manifest["created_at"] == 0.0


def test_a_producer_asking_for_a_wider_window_does_not_move_the_manifest(tmp_path):
    first = ObservationStore(
        tmp_path,
        retention_seconds=7 * DAY,
        clock=lambda: 0.0,
        allowed_classes=TEST_CLASSES,
    )
    first.append(_observation("laptop", observed_at=0.0))

    second = ObservationStore(
        tmp_path,
        retention_seconds=None,
        clock=lambda: 1.0,
        allowed_classes=TEST_CLASSES,
    )
    second.append(_observation("laptop", observed_at=1.0))

    manifest = json.loads((tmp_path / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert manifest["retention_seconds"] == 7 * DAY


def test_a_store_with_no_manifest_is_read_under_the_documented_default(tmp_path):
    # The 55 records already on disk predate the manifest. They must not
    # become unreadable, and they must not become unbounded either.
    now = 1000 * DAY
    _write_raw_line(
        tmp_path,
        _raw_record(object_class="laptop", recorded_at=now - 40 * DAY),
    )

    reader = ObservationStore(
        tmp_path,
        retention_seconds=None,
        clock=lambda: now,
        allowed_classes=TEST_CLASSES,
    )

    assert reader.all_observations() == []


def test_a_store_with_no_manifest_still_serves_records_inside_the_default(tmp_path):
    now = 1000 * DAY
    _write_raw_line(
        tmp_path,
        _raw_record(object_class="laptop", recorded_at=now - 3 * DAY),
    )

    reader = ObservationStore(
        tmp_path,
        retention_seconds=None,
        clock=lambda: now,
        allowed_classes=TEST_CLASSES,
    )

    assert len(reader.all_observations()) == 1


def test_appending_to_a_manifestless_store_does_not_widen_its_window(tmp_path):
    # A producer run with "keep forever" must not retroactively unbound
    # records that were written under the default.
    now = 1000 * DAY
    _write_raw_line(
        tmp_path,
        _raw_record(object_class="laptop", recorded_at=now - 40 * DAY),
    )
    store = ObservationStore(
        tmp_path,
        retention_seconds=None,
        clock=lambda: now,
        allowed_classes=TEST_CLASSES,
    )

    store.append(_observation("laptop", observed_at=now))

    manifest = json.loads((tmp_path / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert manifest["retention_seconds"] == DEFAULT_RETENTION_SECONDS
    assert len(store.all_observations()) == 1


def test_prune_expired_honours_the_persisted_window_over_a_wider_request(tmp_path):
    # Reads and prune must never disagree about what retention means.
    now = 1000 * DAY
    _aged_store(tmp_path, written_under=30 * DAY, age_days=40, now=now)

    reader = ObservationStore(
        tmp_path,
        retention_seconds=None,
        clock=lambda: now,
        allowed_classes=TEST_CLASSES,
    )

    assert reader.prune_expired() == 1


def test_purge_removes_the_manifest_with_everything_else(tmp_path):
    store = ObservationStore(
        tmp_path, retention_seconds=30 * DAY, allowed_classes=TEST_CLASSES
    )
    store.append(_observation("laptop"))

    store.purge()

    assert not (tmp_path / MANIFEST_FILENAME).exists()
    assert not any(tmp_path.iterdir())


# --- REVIEW FINDING 6: an in-window upgrade, written in place ---


def test_update_best_score_raises_the_best_on_the_matching_record(tmp_path):
    store = ObservationStore(
        tmp_path, retention_seconds=None, allowed_classes=TEST_CLASSES
    )
    store.append(_observation("laptop", observed_at=900.0, best_score=0.60))

    assert store.update_best_score("laptop", 900.0, 0.97) is True

    (observation,) = store.all_observations()
    assert observation.best_score == pytest.approx(0.97)
    # The first sighting's own numbers are untouched.
    assert observation.detector_score == pytest.approx(0.9)
    assert observation.observed_at == 900.0


def test_update_best_score_never_lowers_a_recorded_best(tmp_path):
    store = ObservationStore(
        tmp_path, retention_seconds=None, allowed_classes=TEST_CLASSES
    )
    store.append(_observation("laptop", observed_at=900.0, best_score=0.97))

    assert store.update_best_score("laptop", 900.0, 0.60) is False

    (observation,) = store.all_observations()
    assert observation.best_score == pytest.approx(0.97)


def test_update_best_score_leaves_other_records_alone(tmp_path):
    store = ObservationStore(
        tmp_path, retention_seconds=None, allowed_classes=TEST_CLASSES
    )
    store.append(_observation("laptop", observed_at=900.0, best_score=0.60))
    store.append(_observation("laptop", observed_at=1000.0, best_score=0.60))

    store.update_best_score("laptop", 1000.0, 0.97)

    by_time = {o.observed_at: o.best_score for o in store.all_observations()}
    assert by_time[900.0] == pytest.approx(0.60)
    assert by_time[1000.0] == pytest.approx(0.97)


def test_update_best_score_preserves_keys_this_schema_does_not_know(tmp_path):
    # Same promise prune_expired keeps: the rewrite is over raw dicts.
    store = ObservationStore(
        tmp_path, retention_seconds=None, allowed_classes=TEST_CLASSES
    )
    _write_raw_line(
        tmp_path,
        _raw_record(
            object_class="laptop",
            observed_at=900.0,
            best_score=0.60,
            future_field="keep-me",
        ),
    )

    assert store.update_best_score("laptop", 900.0, 0.97) is True

    content = (tmp_path / OBSERVATIONS_FILENAME).read_text(encoding="utf-8")
    assert "keep-me" in content
    assert json.loads(content)["best_score"] == pytest.approx(0.97)


def test_update_best_score_reports_when_there_is_nothing_to_upgrade(tmp_path):
    store = ObservationStore(
        tmp_path, retention_seconds=None, allowed_classes=TEST_CLASSES
    )

    assert store.update_best_score("laptop", 900.0, 0.97) is False
