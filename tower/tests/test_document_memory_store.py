"""Persistence, retention, and deletion that is really deletion.

The store is where `06-PRIVACY-DATA.md` stops being a document and starts
being behaviour. Documents are the platform's clearest case of sensitive
content -- financial, medical, identity and private correspondence all
appear as literal readable text -- so the properties tested hardest here
are the ones about getting rid of it.
"""

import json

import pytest

from tower.confidence import Confidence
from tower.document_memory.records import (
    SCHEMA_VERSION,
    DocumentObservation,
    PageObservation,
)
from tower.document_memory.store import DOCUMENTS_FILENAME, DocumentStore


def _document(document_id="doc-1", observed_at=1000.0, recorded_at=1000.0, text="hello world"):
    return DocumentObservation(
        document_id=document_id,
        observed_at=observed_at,
        recorded_at=recorded_at,
        observed_seconds=4.0,
        pages=(
            PageObservation(
                page_index=0,
                text=text,
                region_count=2,
                mean_region_confidence=0.9,
                min_region_confidence=0.8,
                confidence=Confidence.HIGH,
            ),
        ),
        title="Hello",
    )


@pytest.fixture
def store(tmp_path) -> DocumentStore:
    return DocumentStore(tmp_path)


class TestRoundTrip:
    def test_a_document_survives_a_write_and_a_cold_read(self, tmp_path):
        """A SECOND store over the same directory, because that is what a
        query process is: no shared state with the writer."""
        DocumentStore(tmp_path).append(_document())

        documents = DocumentStore(tmp_path).read_all()

        assert len(documents) == 1
        assert documents[0].document_id == "doc-1"
        assert documents[0].pages[0].text == "hello world"
        assert documents[0].confidence is Confidence.UNKNOWN

    def test_every_field_round_trips(self, store):
        original = DocumentObservation(
            document_id="d",
            observed_at=1.0,
            recorded_at=2.0,
            observed_seconds=3.0,
            pages=(PageObservation(page_index=0, text="t", region_count=1),),
            title="T",
            summary="S",
            frames_considered=9,
            frames_ocred=2,
            confidence=Confidence.MEDIUM,
            capture_id="cap",
            world_id="w",
            world_session_id="ws",
            frame_revision=3,
            retains_raw_imagery=True,
            timing_source="assumed-interval",
            assumed_frame_interval_s=0.3,
        )
        store.append(original)

        assert store.read_all()[0] == original

    def test_reading_an_absent_store_is_empty_not_an_error(self, tmp_path):
        assert DocumentStore(tmp_path / "nothing-here").read_all() == []


class TestItRefusesRatherThanGuesses:
    def test_a_record_from_an_unknown_schema_is_skipped(self, store):
        """Skipped, not guessed at, and not fatal.

        A reader that guessed would produce a plausible wrong answer that
        stays wrong; one that raised would make a single bad record
        destroy the whole memory.
        """
        store.append(_document("keeper"))
        with store.path.open("a", encoding="utf-8") as handle:
            payload = _document("from-the-future").to_json_dict()
            payload["schema_version"] = SCHEMA_VERSION + 99
            handle.write(json.dumps(payload) + "\n")

        documents = store.read_all()

        assert [document.document_id for document in documents] == ["keeper"]

    def test_a_torn_line_does_not_take_the_rest_with_it(self, store):
        """An interrupted write is corruption of one line, not of a memory."""
        store.append(_document("first"))
        with store.path.open("a", encoding="utf-8") as handle:
            handle.write('{"document_id": "torn", "obser')
        store.append(_document("third"))

        assert [document.document_id for document in store.read_all()] == [
            "first",
            "third",
        ]

    def test_a_mid_journal_tear_is_survived_not_just_a_final_one(self, store):
        """The benign case is a torn LAST line. This is the other one."""
        store.append(_document("a"))
        raw = store.path.read_text(encoding="utf-8")
        store.path.write_text(raw[:-20] + "\n" + raw, encoding="utf-8")
        store.append(_document("c"))

        ids = [document.document_id for document in store.read_all()]

        assert "c" in ids


class TestRetention:
    def test_nothing_is_pruned_without_a_window(self, tmp_path):
        """"Forever" has to be chosen, but it is choosable."""
        store = DocumentStore(tmp_path, retention_seconds=None)
        store.append(_document("old", recorded_at=0.0))

        assert store.prune_expired(now=1e9)["documents_removed"] == 0
        assert store.count() == 1

    def test_documents_older_than_the_window_are_really_gone(self, tmp_path):
        store = DocumentStore(tmp_path, retention_seconds=100.0)
        store.append(_document("old", recorded_at=0.0))
        store.append(_document("new", recorded_at=950.0))

        removed = store.prune_expired(now=1000.0)["documents_removed"]

        assert removed == 1
        assert [document.document_id for document in store.read_all()] == ["new"]
        assert "old" not in store.path.read_text(encoding="utf-8"), (
            "pruning must remove the TEXT, not merely hide the record"
        )

    def test_a_negative_window_is_rejected_at_construction(self, tmp_path):
        with pytest.raises(ValueError):
            DocumentStore(tmp_path, retention_seconds=-1.0)

    def test_retention_deletes_the_page_pixels_not_just_the_record(self, tmp_path):
        """A retention window that leaves the picture is not a window.

        An earlier version dropped the journal record and orphaned the
        page image, so the store reported the document gone while the
        image of it stayed on disk indefinitely.
        """
        store = DocumentStore(tmp_path, retention_seconds=100.0)
        store.write_page_image("old-00.jpg", b"sensitive page pixels")
        store.append(
            DocumentObservation(
                document_id="old",
                observed_at=0.0,
                recorded_at=0.0,
                observed_seconds=5.0,
                pages=(
                    PageObservation(
                        page_index=0, text="secret", image_relpath="pages/old-00.jpg"
                    ),
                ),
                retains_raw_imagery=True,
            )
        )
        image = store.images_dir() / "old-00.jpg"
        assert image.exists()

        report = store.prune_expired(now=100_000.0)

        assert report["documents_removed"] == 1
        assert report["images_removed"] == 1
        assert report["complete"] is True
        assert not image.exists()

    def test_retention_keeps_the_images_of_documents_it_keeps(self, tmp_path):
        """The other half: pruning must not delete a live document's image."""
        store = DocumentStore(tmp_path, retention_seconds=100.0)
        store.write_page_image("new-00.jpg", b"still current")
        store.append(_document("old", recorded_at=0.0))
        store.append(
            DocumentObservation(
                document_id="new",
                observed_at=950.0,
                recorded_at=950.0,
                observed_seconds=5.0,
                pages=(
                    PageObservation(
                        page_index=0, text="t", image_relpath="pages/new-00.jpg"
                    ),
                ),
            )
        )

        store.prune_expired(now=1000.0)

        assert (store.images_dir() / "new-00.jpg").exists()

    def test_a_prune_that_cannot_delete_an_image_says_so(self, tmp_path, monkeypatch):
        store = DocumentStore(tmp_path, retention_seconds=100.0)
        store.write_page_image("stuck.jpg", b"bytes")
        store.append(
            DocumentObservation(
                document_id="old",
                observed_at=0.0,
                recorded_at=0.0,
                observed_seconds=1.0,
                pages=(
                    PageObservation(
                        page_index=0, text="x", image_relpath="pages/stuck.jpg"
                    ),
                ),
            )
        )
        real_unlink = type(store.path).unlink

        def refuse(self, *args, **kwargs):
            if self.suffix == ".jpg":
                raise OSError("locked")
            return real_unlink(self, *args, **kwargs)

        monkeypatch.setattr("pathlib.Path.unlink", refuse)

        report = store.prune_expired(now=100_000.0)

        assert report["complete"] is False
        assert report["images_retained"]


class TestPurgeIsRealDeletion:
    def test_purging_everything_empties_the_journal(self, store):
        store.append(_document("a"))
        store.append(_document("b"))

        report = store.purge()

        assert report["documents_removed"] == 2
        assert report["complete"] is True
        assert store.read_all() == []
        assert store.path.read_text(encoding="utf-8").strip() == ""

    def test_purging_one_document_leaves_the_others(self, store):
        store.append(_document("keep"))
        store.append(_document("drop"))

        store.purge("drop")

        assert [document.document_id for document in store.read_all()] == ["keep"]

    def test_purge_removes_page_images_too(self, store):
        store.write_page_image("doc-1-00.jpg", b"not-really-a-jpeg")
        store.append(
            DocumentObservation(
                document_id="doc-1",
                observed_at=1.0,
                recorded_at=1.0,
                observed_seconds=1.0,
                pages=(
                    PageObservation(
                        page_index=0, text="x", image_relpath="pages/doc-1-00.jpg"
                    ),
                ),
                retains_raw_imagery=True,
            )
        )
        image = store.images_dir() / "doc-1-00.jpg"
        assert image.exists()

        report = store.purge("doc-1")

        assert not image.exists()
        assert report["images_removed"] >= 1
        assert report["complete"] is True

    def test_purge_reports_what_it_could_not_delete(self, store, monkeypatch):
        """A purge that cannot delete everything must never claim success.

        A false claim of deletion is worse than an honest failure: the
        user stops looking for data that is still there.
        """
        store.write_page_image("stuck.jpg", b"bytes")
        store.append(
            DocumentObservation(
                document_id="d",
                observed_at=1.0,
                recorded_at=1.0,
                observed_seconds=1.0,
                pages=(
                    PageObservation(
                        page_index=0, text="x", image_relpath="pages/stuck.jpg"
                    ),
                ),
            )
        )

        # Narrowly targeted: only the IMAGE refuses to go. A blanket
        # patch would also break the journal rewrite's own temp cleanup
        # and the test would pass for the wrong reason.
        real_unlink = type(store.path).unlink

        def refuse(self, *args, **kwargs):
            if self.suffix == ".jpg":
                raise OSError("file is locked")
            return real_unlink(self, *args, **kwargs)

        monkeypatch.setattr("pathlib.Path.unlink", refuse)

        report = store.purge("d")

        assert report["complete"] is False
        assert report["images_retained"], "the retained path must be reported"

    def test_purging_an_empty_store_is_complete_not_an_error(self, store):
        assert store.purge()["complete"] is True


class TestObservableGrowth:
    def test_bytes_used_separates_journal_from_imagery(self, store):
        store.append(_document())
        before = store.bytes_used()
        store.write_page_image("p.jpg", b"x" * 500)
        after = store.bytes_used()

        assert before["images"] == 0
        assert after["images"] >= 500
        assert after["total"] == after["journal"] + after["images"]

    def test_an_empty_store_reports_zero_rather_than_failing(self, tmp_path):
        assert DocumentStore(tmp_path / "absent").bytes_used()["total"] == 0


class TestPageImagesAreFsyncedBeforeUse:
    def test_no_temp_file_survives_a_write(self, store):
        store.write_page_image("a.jpg", b"payload")

        leftovers = list(store.images_dir().glob("*.tmp"))

        assert leftovers == []
        assert (store.images_dir() / "a.jpg").read_bytes() == b"payload"


def test_the_journal_filename_is_stable(store):
    """A query process finds the file by name; renaming it breaks them."""
    store.append(_document())

    assert (store.directory / DOCUMENTS_FILENAME).exists()
