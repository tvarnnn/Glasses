# Lane ownership — who may change what

**As of 2026-08-26.** Three lanes work this repository concurrently. This
document is the boundary. When a lane needs something owned by another, it
**documents the requirement** rather than implementing it.

| Lane | Branch | Owns |
|---|---|---|
| **Tower / cartridges** (this lane) | `integration/world-builder-lifecycle-v1` | Everything not claimed below |
| **iOS / Mac** | `ios/world-builder-integration` | **All of `ios/`**, exclusively |
| **World Builder** | `world-builder/next-generation` | The World Builder subsystem |

---

## 1. What this lane must NOT change

### 1.1 iOS — total freeze

**No file under `ios/` may be modified by this lane.** The Mac lane holds a
Swift toolchain and this host does not, so a compiler result outranks any
static reasoning produced here.

Requirements flow through **`docs/agent-handoffs/IOS-EXECUTION-PLAN.md`**,
which is the single current iOS document.

### 1.2 World Builder — frozen while the dedicated lane owns it

May be **read and consumed**. May not be redesigned, modified, or
re-contracted here.

Frozen surfaces:

- `tower/tower/world_builder/**` — engine, backends, frontend, keyframes,
  store, intrinsics.
- `tower/tower/results/world_builder_geometry.py` and
  `tower/tower/routes/geometry.py` — the geometry transport.
- `docs/contracts/WORLD-BUILDER-*.md` — World Builder-specific contracts.
- World Builder-specific tests and `scripts/world_*.py`.

**Consuming an existing World Builder interface is allowed.** Changing one,
or adding a new one, is not.

Requirements this lane discovers for World Builder are written to
**§4 below** and to the relevant research document, never implemented here.

---

## 2. What this lane continues to own

- **Cartridges:** Scene Understanding, Object Memory, Document Memory,
  Experimental CV Lab.
- **Shared infrastructure:** `tower/tower/detection.py`,
  `tower/tower/modules/**` (lifecycle, container), `tower/tower/loading.py`,
  the cartridge result channel core, `tower/tower/routes/observations.py`,
  health and cartridges routes.
- **Benchmarks and harnesses**, research, and all documentation not owned
  above.

---

## 3. Borderline cases, ruled

**`tests/test_result_channel_hostile.py`** — the result channel is shared
infrastructure, but this file drives it through World Builder fixtures and
unlinks `world.json`. **Ruled: defer to the World Builder lane.** The known
`WinError 32` flake in it is a Windows sharing-violation race in the test's
own file handling (confirmed, not hypothesised — see the run handoff). The
fix is to tolerate a transient sharing violation on the unlink. **The
assertion that follows it must never be softened**: it guards the result
channel against fabricated results.

**The cartridge result channel envelope** (`cartridge_results.envelope/…`)
is shared and stays with this lane. The **World Builder status payload**
carried inside it (`world_builder.status/…`) is World Builder's.

---

## 4. Requirements this lane has for the World Builder lane

**4.1 The capture-clock epoch across a reconnect — BLOCKING for capture
lineage.** The iOS lane measured that DAT's frame timestamps are a genuine
capture clock, not a receipt time
(`research/2026-08-26-two-clocks-capture-vs-receipt.md`). Their own commit
records that **whether the epoch survives a reconnect is untested**.

This matters more to World Builder than to anyone: a capture that chains
across a mid-walk reconnect must not splice two different epochs into one
timeline. Until proven, a transported capture clock is valid only within a
single uninterrupted connection.

**4.2 The camera captures ~24 fps; Tower receives ~12.** Established from
two directions independently: the iOS lane's 1/24 s PTS grid, and Tower's
`source_seq` stepping by **2** against a measured 83.5 ms delivered
interval. Roughly every other captured frame never arrives.

*No World Builder constant is invalidated* — keyframe selection, reference
staleness and tracking all consume delivered frames, which is the correct
denominator for them. But **"the frame rate" is now ambiguous** and should
be qualified as capture or delivery wherever it appears.

**4.4 The face-redaction filter fires on 40% of real frames, and is
mostly wrong when it does — PRICING, not correctness.**
`tower/tower/world_builder/redaction.py` fills detected face regions
BEFORE persistence, and its own analysis priced the honest cost as "the
5% row -- no keyframes lost, about 9% of the point cloud". That pricing
rests on "0 false positives on 40 face-free frames", measured on forty
**synthetic room renders**.

Measured at the same settings on the real corpus (1,845 evenly-spaced
frames from all 34 captures, `scripts/research/face_filter_false_positives.py`):

    frames with at least one firing   741 of 1,845 -- 40.2%
    regions filled                    976
    median region area                12.5% of the frame
    largest region                    84.2% of the frame

Of 36 firings inspected by eye, **4 were a real face** (the wearer
reflected in a mirror) and **32 were not**: hands on a keyboard in the
large majority, plus laptop and phone screens, a white interior door, and
a sink.

The detector is not being accused of being bad at faces -- it found the
mirror. The finding is that the 5% assumption does not hold on this
footage, and World Builder destroys these pixels permanently. Object
Memory hit the same thing on read and responded by REPORTING the overlap
rather than weakening the filter, because a face-detection threshold is
not a picture-quality knob; the equivalent response here is a
re-pricing, not a threshold change.

Detail: `docs/superpowers/research/2026-08-27-object-memory-corpus-precision.md` §6.

**4.5 `spatial_ref`, when there is a world to anchor against.**
`docs/contracts/OBJECT-MEMORY.md` §12 specifies the shape Object Memory
will consume, including the `anchor_keyframe_id` and `frame_revision`
that `CARTRIDGE-GROUNDWORK.md` §4 requires. Object Memory will not build
it and keeps working without it.

**4.3 Deferred World Builder findings** remain triaged at
`tower/docs/superpowers/plans/2026-08-25-geometry-transport-followups.md`
items 1–6 (Tower side) and 7–21 (iOS side). This lane has not acted on any
of them since the freeze.

---

## 5. Git discipline, all lanes

- **Never merge to `main`.** It sits at `35214a1` and has not moved.
- **Never force-push.** Preserve both lanes' commits.
- **Fetch before every push** and check whether the remote advanced; if it
  did, integrate rather than overwrite.
- On a genuine conflict: stop editing the conflicted files, inspect
  ownership by this document, and resolve only if the intended result is
  unambiguous. Otherwise document it for integration.
