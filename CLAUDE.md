# Glasses Monorepo Agent Rules

Default to your assigned subsystem.

`ios/` owns Swift/iOS/DAT/UI/runtime work.

`tower/` owns Python/Tower/CV/ML/storage work.

Cross-read the other subsystem only when needed for integration,
contract reconciliation, debugging, or compatibility analysis.

Do not modify the other subsystem unless the task explicitly authorizes
cross-subsystem changes.

Shared protocol truth lives under `docs/contracts/`.

Shared current-state handoffs live under `docs/agent-handoffs/`.

Never solve a cross-system mismatch by importing implementation details
across subsystem boundaries.
---

# Glasses filesystem / worktree policy

This section is not style advice. It was written after a cleanup pass found
~1 GB of Glasses artifacts sitting at the Windows drive root and in the user
home directory: mutation trees (`C:\wbmut*`), benchmark output
(`C:\wb-adv`, `C:\wb-stage0`), thirteen world-builder run roots
(`C:\wbr*`, `C:\wbrev*`), a Tower source copy (`C:\wb-src`), and a scratch
directory (`~/wbscratch`). Two causes produced all of it, and both are
still available to you if you ignore what follows. See
`tower/docs/superpowers/reports/2026-08-27-filesystem-cleanup.md`.

## The two ways this goes wrong

1. **A relative artifact root resolved from the wrong directory.** Session
   CLIs default `--root` to a *relative* path. Run one from `C:\` and the
   artifacts land at `C:\`. This used to be silent; `tower/artifact_paths.py`
   now refuses it at the CLI boundary.

2. **MAX_PATH pressure.** Windows' 260-character limit makes deep paths
   genuinely fail (`Filename too long`), and the tempting fix is a very
   short path like `C:\m3s`. The pressure is real; the drive root is still
   the wrong answer. Use a short directory *under* `Projects\`, or enable
   long paths, rather than escaping to the root.

## The rules

1. Never create Glasses project artifacts directly under `C:\`.
2. Never create Glasses project artifacts directly under `C:\Users\<you>\`.
3. The canonical repository is `C:\Users\<you>\Projects\Glasses`.
4. Persistent Glasses worktrees live under `C:\Users\<you>\Projects\`.
   Prefer `C:\Users\<you>\Projects\Glasses-worktrees\` for new work.
5. Disposable development artifacts belong under
   `C:\Users\<you>\Projects\Glasses-scratch\`.
6. That includes benchmark copies, mutation trees, profiling output,
   temporary scripts, experimental repository copies, and generated
   scratch data.
7. Every `git worktree add` must name its destination explicitly.
8. Never rely on the current working directory, or on a default path, when
   creating a worktree.
9. Record every temporary resource you create, in your handoff.
10. Never move or delete another active agent's worktree.
11. Manage git worktrees only through git-aware operations
    (`git worktree add` / `list` / `move`), never by moving directories.
12. Tests and benchmarks must not leave persistent directories outside
    approved project locations. Use `tmp_path` / `tempfile`, which stay
    inside the OS temp directory and are allowed.
13. An autonomous run should quarantine its own disposable artifacts into
    `Glasses-scratch\` when it finishes, if it can do so safely.
14. **Deletion requires explicit human approval.** Not "it is
    reproducible", not "it is on GitHub", not "it is large".
15. When cleaning up without explicit deletion permission, *move* artifacts
    to `Glasses-scratch\`. Never delete them.

## Writing a new CLI that takes a path

Route it through the guard, or the test suite will fail:

```python
from tower.artifact_paths import artifact_root_arg

parser.add_argument("--root", type=artifact_root_arg, default=str(DEFAULT_ROOT))
```

`tests/test_artifact_paths.py::test_every_cli_root_flag_routes_through_the_guard`
scans `scripts/` and fails on any `--root` that skips it.
