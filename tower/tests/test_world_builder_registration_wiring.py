"""Registration runs when a walk ends, and cannot take the walk down with it.

The defect these cover is not a wrong answer, it is a question never
asked. `scripts/world_registration.py` -- the Sim3 fit, the mutual
evidence rule, the cycle check, the digest-bound persistence, the
serving-side staleness refusal -- was complete, tested and inert. Nothing
called it. Every physical walk therefore finalised with no
`placements.json`, and the phone drew every segment as its own island:
22 disconnected fragments on the 2026-08-29 drawer walk, whose segments
were not refused so much as never considered.

So these tests are about wiring and blast radius, not about geometry.
The geometry is `tests/test_world_registration.py`'s subject and is
unchanged.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.world_build_session import register_session  # noqa: E402
from scripts.world_registration import (  # noqa: E402
    NO_VISUAL_LINK,
    SupportMissingError,
)


def _run(script, *args):
    return subprocess.run(
        [sys.executable, f"scripts/{script}", *args],
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="module")
def registered_world(tmp_path_factory):
    """A real synthetic walk, built and registered through the driver.

    The `derived_world` conftest fixture cannot be used here: it writes
    no `support.json`, and registration refuses outright without the
    2-D/3-D association. Driving the script end to end is also the only
    way to exercise the wiring these tests are about.
    """
    root = tmp_path_factory.mktemp("reg")
    result = _run(
        "world_build_session.py",
        "--synthetic", "--synthetic-frames", "16",
        "--root", str(root), "--format", "json", "--register",
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)

    from tower.world_builder.store import WorldStore

    return (
        WorldStore(root),
        report["world_id"],
        report["session_id"],
        report,
    )


class _Boom:
    """A store whose every read fails, standing in for any solver fault."""

    def __init__(self, error):
        self._error = error

    def __getattr__(self, name):
        def explode(*_args, **_kwargs):
            raise self._error

        return explode


class TestTheDriverAsksTheQuestion:
    def test_a_run_without_the_flag_still_does_not_register(self, tmp_path):
        """The flag is opt-in at the script, and the Tower opts in.

        Kept explicit so a batch reprocess -- which may be exploring a
        threshold -- cannot silently overwrite what a world serves.
        """
        result = _run(
            "world_build_session.py",
            "--synthetic", "--synthetic-frames", "10",
            "--root", str(tmp_path), "--format", "json",
        )

        assert result.returncode == 0
        assert "registration" not in json.loads(result.stdout)

    def test_registering_reports_what_it_placed_and_writes_it_down(
        self, tmp_path
    ):
        result = _run(
            "world_build_session.py",
            "--synthetic", "--synthetic-frames", "12",
            "--root", str(tmp_path), "--format", "json", "--register",
        )

        assert result.returncode == 0
        report = json.loads(result.stdout)
        registration = report["registration"]
        assert registration["attempted"] is True
        assert registration["wrote_placements"] is True

        placements = (
            Path(tmp_path) / "worlds" / report["world_id"] / "derived"
            / report["session_id"] / "placements.json"
        )
        assert placements.exists(), (
            "registration reported success and wrote nothing, so the "
            "serving layer still has no placement to read"
        )

        # Refusal is the default answer and a perfectly good outcome; what
        # must never happen is a placement claimed without a transform.
        rows = json.loads(placements.read_text())["placements"]
        assert rows
        for row in rows:
            if row["state"] == "registered":
                assert row["rotation_wxyz"] is not None
                assert row["translation"] is not None
                assert row["scale"] is not None
                assert row["reference_segment"] is not None
            else:
                assert row["rotation_wxyz"] is None
                assert row["translation"] is None
                assert row["scale"] is None
                assert row["refusal_reason"]


class TestAFailedRegistrationCostsNothingButTheRegistration:
    """A reconstruction is worth keeping even when it cannot be placed.

    Registration runs after the last build, so by the time it can fail
    the poses, points and support are already on disk. Letting it
    propagate would throw away the whole walk to lose a transform -- and
    it is the newest, least exercised step in the pipeline.
    """

    def test_a_solver_fault_is_reported_not_raised(self, caplog):
        outcome = register_session(
            _Boom(RuntimeError("the solver fell over")), "w" * 32, "s" * 32
        )

        assert outcome["attempted"] is True
        assert outcome["wrote_placements"] is False
        assert "the solver fell over" in outcome["error"]

    def test_a_world_with_no_support_says_so_rather_than_failing(self):
        """Worlds built before support.json existed cannot be registered.

        That is a refusal with a remedy in it, not an error, and it must
        read differently from a crash.
        """
        outcome = register_session(
            _Boom(SupportMissingError("world w has no support.json")),
            "w" * 32,
            "s" * 32,
        )

        assert outcome["attempted"] is True
        assert outcome["wrote_placements"] is False
        assert "support.json" in outcome["refusal"]
        assert "error" not in outcome


class TestEveryCandidatePairIsAccountedFor:
    """A pair the matcher could not link must still produce a row.

    This branch used to `continue`. On the 2026-08-29 drawer walk that
    left `candidate_pairs` at 228 of the 253 pairs over 23 segments with
    geometry, and the missing 25 were indistinguishable in the report
    from pairs that were never enumerated. The distinction matters
    because it is the one that says whether a walk's problem is
    RETRIEVAL -- we never found the shared view -- or ESTIMATION -- we
    found it and could not agree about it. Those want opposite work.
    """

    def test_the_report_covers_the_whole_upper_triangle(self, registered_world):
        from scripts.world_registration import register

        store, world_id, session_id, _ = registered_world
        report = register(store, world_id, session_id)

        n = report["segments_with_geometry"]
        assert report["candidate_pairs"] == n * (n - 1) // 2, (
            "a pair vanished from the report; a pair nobody could link is "
            "a measurement, not an absence"
        )

    def test_an_unlinkable_pair_names_the_matcher_as_the_reason(
        self, registered_world
    ):
        from scripts.world_registration import register

        store, world_id, session_id, _ = registered_world
        report = register(store, world_id, session_id)

        for pair in report["pairs"]:
            if pair["reason"] == NO_VISUAL_LINK:
                assert pair["registered"] is False
                assert pair["clauses"]["verified_frame_pairs"] == 0
                assert pair["clauses"]["inliers"] == 0

    def test_a_linked_pair_reports_how_much_evidence_it_had(
        self, registered_world
    ):
        """Refusals were legible; the evidence behind them was not.

        A pair refused with 4,449 verified inliers and one refused with
        16 are different situations, and before this the report said the
        same thing about both.
        """
        from scripts.world_registration import register

        store, world_id, session_id, _ = registered_world
        report = register(store, world_id, session_id)

        linked = [
            p for p in report["pairs"]
            if p["clauses"].get("verified_frame_pairs", 0) > 0
        ]
        if not linked:
            pytest.skip("no pair on this fixture shares a verified view")
        for pair in linked:
            assert pair["clauses"]["inliers"] > 0
