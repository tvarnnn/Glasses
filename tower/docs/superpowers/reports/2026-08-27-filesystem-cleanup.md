# Filesystem cleanup and hygiene pass — 2026-08-27

An autonomous, **non-destructive** cleanup of filesystem pollution created
during the parallel World Builder / Object Memory / CV Lab / Document Memory
development push.

**Nothing was deleted.** Misplaced artifacts were *moved* into a quarantine
directory for manual review. The root causes were found and fixed.

---

## 1. Starting state

Two other Claude sessions were **live** throughout this pass and were treated
as untouchable:

| Session cwd | What it was doing |
|---|---|
| `Projects\Glasses` | `pytest -q -p no:cacheprovider`, plus `world_build_session.py --follow-capture` against a temp root |
| `Projects\GlassesTower` | `pytest tests/test_result_channel_protocol.py` |

The canonical repository had 8 branches and 5 registered worktrees, all clean
and tracking their remotes.

## 2. What was found

**~1.05 GB of Glasses artifacts outside every Glasses directory.**

### At the drive root (`C:\`)

| Artifact | Size | What it is |
|---|---|---|
| `wb-adv` | 139 MB | Adversarial/accuracy benchmark output |
| `wb-stage0` | 743 MB | Determinism-bisect / staging benchmark tree |
| `wbmut`, `wbmut_m1..m7` (+ 7 logs) | 81 MB | Mutation-testing baseline and seven mutants |
| `wbr3`–`wbr6`, `wbrev`, `wbrev2`, `wbr_*` (13) | 68 MB | World Builder run roots |
| `wb-src` | 8 MB | Tower source copy under benchmark |
| `m3s\MASt3R-SLAM` | 337 MB | Third-party SLAM repo cloned for research |
| `c\Users\...\observations.jsonl` | 393 B | Path-resolution bug artifact |

### In the user home (`C:\Users\tvllo\`)

`wbscratch\` (20 MB of adversarial attack and mutation scripts), plus loose
scripts `findworld.ps1`, `lsworld.ps1`, `lsworld2.ps1`, `intr.ps1`,
`worker.ps1`, `wsdump.py`, `tower_start.ps1`, `start_tower.ps1`, `render.py`.

### Under `Projects\`

Nothing misplaced. The four `Glasses-*` directories are legitimate registered
worktrees, all clean and in sync. `GlassesTower` and `GlassesIOS_Side` are
separate repositories with their own remotes.

## 3. What was moved

**37 artifacts, 309 MB, 13,386 files**, all into
`C:\Users\tvllo\Projects\Glasses-scratch\`, organised into `benchmarks\`,
`mutation-tests\`, `experimental-copies\`, `temp-scripts\` and
`unknown-but-glasses-related\`. Original locations are encoded in the
destination names (`C-drive__wbmut`, `user-home__wsdump.py`).

Every move was a filesystem rename — never copy-then-delete — with file count
and byte size compared before and after. All 37 matched exactly. The full log
is `Glasses-scratch\.move-log.txt`; the human-readable index is
`Glasses-scratch\README-CLEANUP-INVENTORY.md`.

## 4. What was deliberately left alone

| Path | Classification | Why |
|---|---|---|
| `C:\wb-stage0` | `ACTIVE_DO_NOT_TOUCH` | OS refused the move (`Permission denied`) — open handle or a live shell cwd. Verified intact. |
| `C:\wbr_20ce3c23` | `ACTIVE_DO_NOT_TOUCH` | Same, on two attempts. Verified intact. |
| `C:\m3s\MASt3R-SLAM` | `KEEP_IN_PLACE` | Third-party repo. Its short path is a *documented* MAX_PATH workaround and research docs cite `C:\m3s\...` as provenance. |
| `~\tower_start.ps1`, `~\start_tower.ps1`, `~\render.py` | `ACTIVE_DO_NOT_TOUCH` | Operational launchers for repos with live agents in them. |
| `C:\tool\rojo.exe` | Out of scope | Roblox tooling, not Glasses. |
| 5 registered worktrees | `KEEP_IN_PLACE` | Clean, in sync, and already under `Projects\`. |

`C:\wb-stage0` and `C:\wbr_20ce3c23` are the only Glasses artifacts still at
the drive root.

## 5. Root causes

### RC1 — CWD-relative artifact roots (`TEST_TOOLING` / `BENCHMARK_TOOLING`)

Every session CLI defaulted `--root` to a **relative** path
(`Path("data/world_builder")`). What that is relative *to* is decided by
wherever the caller happens to be standing. An agent working from `C:\` with
`--root wbr3` got `C:\wbr3` — silently, with no error and no warning.

This is the direct and sufficient explanation for `C:\wbr3`, `wbr4`, `wbr5`,
`wbr6`, `wbrev`, `wbrev2`, `wbr_*` and `wb-stage0`.

**Fixed.** See §6.

### RC2 — MAX_PATH pressure (`AGENT_BEHAVIOR`)

Windows caps paths at 260 characters, and deep project paths genuinely fail.
`tower/docs/superpowers/research/2026-08-26-slam-lane-learned-3d.md:251`
records it verbatim:

> `Filename too long` [M]. Worked around by cloning to `C:\m3s` with …

The pressure is real; the drive root is the wrong relief valve. It explains
`C:\m3s`, and the very short names `wbmut`, `wb-adv`, `wb-src`.

**Fixed by policy**, not by code — the guard names the approved short
location instead.

### RC3 — Relative interpretation of a drive-qualified path (`AGENT_BEHAVIOR`)

`C:\c\Users\tvllo\AppData\Local\Temp\claude\...` is a `c:\...` path treated
as *relative* while the working directory was `C:\`. Same underlying habit as
RC1: working from the drive root.

### RC4 — No policy existed (`REPOSITORY_TOOLING`)

`CLAUDE.md` said nothing about where artifacts, worktrees or scratch data
belong. Nothing in the repository told an agent that `C:\` was wrong.

**Fixed.** See §7.

## 6. Tooling fix

New module **`tower/tower/artifact_paths.py`**. It refuses, at the CLI
boundary, the four placements that are never correct:

* a filesystem root itself (`C:\`, `/`)
* a direct child of a filesystem root (`C:\wbmut`, `C:\wb-stage0`)
* the user home directory itself
* a direct child of the user home directory (`~\wbscratch`)

Temp directories are deep inside the home directory rather than direct
children of it, so `tempfile` and pytest `tmp_path` are unaffected — verified
by the full suite.

Wired into every CLI on `main` that takes `--root`:
`world_build_session.py`, `world_inspect.py`, `document_memory_session.py`,
`document_query.py`. The default is now passed as a string so argparse runs
the converter over it too — meaning **the default itself is validated**,
which is what closes RC1.

Behaviour, reproducing the original bug exactly:

```
$ cd C:\ && python world_inspect.py --root wbr99
world_inspect.py: error: argument --root: refusing to write artifacts to
C:\wbr99: it sits directly at the drive root C:\. This is usually a relative
--root resolved from the wrong working directory. Disposable Glasses
artifacts belong under C:\Users\<you>\Projects\Glasses-scratch\ ; …
```

No directory is created.

## 7. Policy added

`CLAUDE.md` gained a **Glasses filesystem / worktree policy** section, at
repository root where every agent reads it: the two failure modes above, the
15 rules (canonical repo, worktrees under `Projects\Glasses-worktrees\`,
scratch under `Projects\Glasses-scratch\`, explicit worktree destinations,
never touch another agent's worktree, **deletion requires human approval**),
and the snippet for wiring a new `--root` flag.

`.gitignore` gained a defensive `Glasses-scratch/` entry. The quarantine
directory is a *sibling* of the repository, so git cannot track it
regardless; the entry guards against anyone creating one inside a checkout.

## 8. Recurrence protection

`tower/tests/test_artifact_paths.py` — 17 tests. Beyond unit-testing each
rule (parameterised over the directory names actually found on disk), two
tests keep it honest as the codebase grows:

* `test_every_cli_root_flag_routes_through_the_guard` walks the AST of every
  script in `scripts/` that declares `--root` and fails if its `type=` is not
  `artifact_root_arg`. **A new CLI that forgets the guard fails the suite.**
* `test_the_scan_actually_finds_the_session_clis` guards the guard, so the
  scan cannot silently become vacuous.

## 9. Tests run

| Suite | Result |
|---|---|
| `tests/test_artifact_paths.py` | **17 passed** |
| CLI + architecture regression subset | **85 passed** |
| **Full Tower suite** | **1044 passed, 30 skipped** in 159.77s |

Verified afterwards: canonical repo intact at `6e325f8`, 459 commits, 8
branches, all 5 pre-existing worktrees still resolving, all clean.

## 10. Remaining manual work

1. Review `Glasses-scratch\README-CLEANUP-INVENTORY.md` and decide what to
   delete. **Deletion is yours alone; none was performed.**
2. Move `C:\wb-stage0` and `C:\wbr_20ce3c23` once nothing holds them open.
3. Decide whether `C:\m3s\MASt3R-SLAM` should stay. If it moves, update the
   `C:\m3s\...` citations in the SLAM research docs.
4. Consider promoting the `attack_*.py` probes in
   `Glasses-scratch\mutation-tests\user-home__wbscratch\` into `tower/tests/`.
5. `wbmut_m2_thresh0` records a **surviving mutant** — a real test-coverage
   gap worth closing.
6. Feature branches carry session CLIs that do not exist on `main`
   (`world_registration.py`, `object_memory_session.py`, `object_query.py`).
   They need the same one-line wiring when they merge; the AST test will
   fail until they get it.
7. Consider enabling Windows long paths to relieve RC2 at the source.

## 11. Deletion statement

**Zero files or directories were intentionally deleted.**

No `rm`, `rm -rf`, `del`, `erase`, `rmdir`, `rd`, `Remove-Item`, `git clean`,
`git worktree remove`, `git branch -d` or `git branch -D` was invoked at any
point in this pass. Every relocation was a rename, size- and count-verified
on both sides. No operation unexpectedly removed or replaced anything; the
two moves that failed (`wb-stage0`, `wbr_20ce3c23`) failed cleanly, leaving
the sources intact and creating no partial destination.

`ios/` was not modified.
