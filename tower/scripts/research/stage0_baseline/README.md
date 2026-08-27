# Stage 0 baseline — what these artifacts are, and one trap in them

## The control

`baseline_HEAD_d3d24b5.json` is the **DEPTH=1 control** for the 2026-08-27
overnight run: the pinned 8-capture corpus replayed through the engine
*before* `EXTEND_REFERENCE_DEPTH` was introduced.

| | |
|---|---|
| segments | 230 |
| keyframes | 1,712 |
| poses_solved | **591** |
| poses_refused | 891 |
| points | **75,369** |
| exactly-2-view | 70.38% |
| ≥3-view | 29.62% |

Independently reproduced, on every field, by the adversarial reviewer
using a different method (in-process depth binding rather than editing the
constant).

The shipped state (DEPTH=3) measures **620 solved / 71,122 points /
61.70% two-view**. The A/B and its raw JSON live in
`../stage1_covisibility/results/`.

## THE TRAP: the recorded repeat mismatch is NOT nondeterminism

This artifact records a corpus repeat disagreeing with its parent run —
notably **112 versus 131 solved poses on capture `22e9d428`**. Read
naively that looks like a ±19-pose noise floor, which would swamp the
whole run's +29-pose result.

**It is not noise. It is a source-tree change straddling the run.**
112 is DEPTH=1 and 131 is DEPTH=3. `corpus_repeat_check` spawns fresh
subprocesses which re-read `backends/classical.py` from disk, and the
constant was toggled between the parent run and its repeats.

**The real noise floor is zero.** Three fresh processes produce
byte-identical `points.json` and `support.json`, deltas exactly 0.0
(verified by the adversarial reviewer, and separately by the determinism
check in this harness).

## What was fixed so this cannot recur

`measure_baseline.py` now records, in every artifact it writes:

- `solver_source_sha256` — a hash of each of the five files that carry
  the solve (`backends/classical.py`, `geometry.py`, `engine.py`,
  `keyframes.py`, `frontend.py`)
- `git_head` and `git_status_porcelain`
- `tower_package` — the resolved package path, which also catches the
  editable-install trap below

and `corpus_repeat_check` now compares repeats **against the run they are
attached to**, not only against each other. The previous version reported
IDENTICAL while both repeats agreed with one another and disagreed with
their parent.

Any artifact carrying `solver_source_sha256` can be trusted about which
bytes produced it. **This one predates that field.**

## Running it

There is no venv in this worktree. The only venv is in the MAIN repo and
contains an editable install mapping `tower` at the MAIN repo — a
different branch. Always:

```
cd C:\Users\tvllo\Projects\Glasses-world-builder\tower
PYTHONPATH="C:\Users\tvllo\Projects\Glasses-world-builder\tower" \
  C:\Users\tvllo\Projects\Glasses\tower\.venv\Scripts\python.exe \
  scripts/research/stage0_baseline/measure_baseline.py --label <name> --out <path>
```

Verify before trusting any number:
`import tower.world_builder.backends.classical as m; m.__file__` must
resolve under `Glasses-world-builder`. The corpus lives only in the main
repo (`...\Glasses\tower\data\captures`); input data is branch-independent,
CODE is not.

`--no-registration --no-reprojection --no-determinism` cuts a full run
from roughly 12 minutes to about 4. Registration alone is 472 s against
219 s for all replay-and-build.
