"""Pytest plugin that REMOVES the guided re-observation mechanism.

A test suite that still passes with the feature gone is not defending the
feature. This neutralises `_reobserve_against_pose` to return {} -- the
exact behaviour before commit 44bb566 -- without editing production code,
so the review never has to write into tower/tower/.

    pytest -p neutralize_plugin tests/...

Set NEUTRALIZE=older_features to instead starve the mechanism of its
inputs (extra_references always empty), which is the other way the
feature could be removed.
"""
import os

import tower.world_builder.backends.classical as classical


def pytest_configure(config):
    mode = os.environ.get("NEUTRALIZE", "guided")
    if mode == "guided":
        def _dead(self, *args, **kwargs):
            return {}
        classical.ClassicalTwoViewBackend._reobserve_against_pose = _dead
        print("\n[NEUTRALIZE] _reobserve_against_pose -> {}")
    elif mode == "older_features":
        classical.EXTEND_REFERENCE_DEPTH = 1
        print("\n[NEUTRALIZE] EXTEND_REFERENCE_DEPTH -> 1")
    else:
        raise SystemExit(f"unknown NEUTRALIZE mode {mode!r}")
