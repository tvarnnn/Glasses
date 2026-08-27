# Stage 2 — what `r_H` actually touches, read from the contract and the code

**Date:** 2026-08-27. **Branch:** `world-builder/next-generation`.
**Status:** analysis, pre-implementation. No production code touched.

The roadmap (`2026-08-26-world-builder-modern-slam-comparison.md` §3 Stage 2)
says `r_h` is on the Tower→iOS wire and that removing it is a cross-subsystem
contract change, not a line deletion. That is correct. This note establishes
exactly how far the blast radius extends, because the roadmap's recommendation
(*keep the field, emit `null`, raise removal separately*) is only safe if
nothing downstream derives from it.

**Result: the blast radius is smaller than feared, and the change is
schema-legal. But it is not zero, and §4 records the part that is genuinely a
contract question.**

---

## 1. `r_h` is a declared contract field — confirmed

`docs/agent-handoffs/TOWER-TO-IOS.md:372-375` defines:

> **`KeyframeEdge`** — `from_keyframe_id`, `to_keyframe_id`, `matches`,
> `inliers`, `inlier_ratio`, `median_parallax_px`, `median_parallax_deg`,
> `cheirality_fraction`, **`r_h`**, `rotation_dominant`, `pose_status`,
> `degeneracy`, `quality`, `frame_revision`.

Under `CLAUDE.md`, `docs/contracts/` and the handoffs are shared protocol truth.
So the roadmap is right that this is not a deletion a Tower-side lane may make
unilaterally.

## 2. Emitting `null` is schema-legal — confirmed

`records.py:772`:

```python
r_h: float | None = None
```

Already `float | None`, already defaulting to `None`, serialised verbatim at
`records.py:790` and read back at `:810`. **A null `r_h` is a value the schema
already admits, not a schema change.**

Stronger still: it is a value iOS *already receives routinely*. On the HEAD
replay only **23 of 415 edges carry a non-null `r_h`** `[QUOTED, synthesis
§3 Stage 2]`. Any consumer that could not tolerate null would already be
failing on ~94% of edges.

## 3. `rotation_dominant` does NOT derive from `r_h` — the important check

This was the real risk: `rotation_dominant` sits beside `r_h` in the same
contract struct, and in the SLAM literature the two are conventionally coupled
(ORB-SLAM thresholds r_H to decide rotation dominance). If production computed
it that way, nulling `r_h` would silently change a *second* contract field.

It does not. `engine.py:660`:

```python
rotation_dominant=(pose.status != POSE_STATUS_SOLVED),
```

It is derived from **pose status**, not from `r_h`. Independent.

The only place the two are coupled anywhere in the tree is
`scripts/feature_trackability.py:211`, which thresholds `r_h_values` against
`R_H_THRESHOLD` — a **diagnostic script**, not production, and not on the wire.

**So nulling `r_h` changes exactly one field's values and nothing else's.**

## 4. What is still a genuine contract question

Emitting `null` forever is *semantically* different from emitting `null`
because a pair happened not to produce one, even though both are the same JSON.
Today a null means "not computed for this edge"; afterwards it would mean
"never computed, deliberately". A consumer distinguishing those cannot, and no
Tower-side change can tell it apart.

That is a documentation and handoff obligation, not a code one, and it is why
the roadmap's "raise the field's removal as a separate contract item" is the
right call rather than fold-it-into-a-half-day-stage. **Recorded for the Mac
handoff; not resolved here.**

## 5. The codebase already knew what the research re-discovered

The most striking find. `records.py:767-771`, describing `cheirality_fraction`:

> The actual degeneracy discriminator (see `Keyframe.r_h` for why it is not
> `r_h`): the fraction of correspondences passing `recoverPose`'s cheirality
> check. Measured to be **near-binary — ~0.01 when degenerate, ~1.0 when
> healthy** — at roughly 0.5 deg median parallax.

And `records.py:666-671`, on a *different* field deliberately not named `r_h`:

> Deliberately NOT named `r_h`. `KeyframeEdge.r_h` is ORB-SLAM's dimensionless
> H/(H+F) inlier ratio — a different quantity, in different units. Both once
> shared the name, which would have let a successor compare them and get a
> meaningless answer with no error.

This is independent corroboration, from inside production and predating the
research, of two of the programme's headline findings: that the **cheirality
gate is the real degeneracy discriminator** (the synthesis measured it at 0.0%
false-positive on a synthetic zero-baseline null, the best of anything tested),
and that **`r_H` is not the discriminator it looks like**.

Worth stating plainly because it cuts against the framing that this pipeline
was naive about degeneracy: it was not. The `r_H` field is a recorded
measurement someone deliberately declined to gate on, and the research's
contribution is proving *why* that instinct was right — `r_H`'s median is
**0.4960 on pairs that are definitionally pure rotation** `[QUOTED, synthesis
§5.1.5]`, i.e. it is useless in precisely the regime it exists for.

## 6. Consequences for Stage 2

- **Fixing the uninitialised-mask defect** (`geometry.py:120-123`: check the
  model before trusting the mask) is internal, changes no field's declared
  type, and is safe to do now. It is worth doing because it is *free while
  already in that file* and because non-determinism is miserable to debug
  later — not because it is urgent. Current values are benign: 23 non-null
  edges, all in 0.44–0.51, bit-identical across two fresh processes `[QUOTED]`.
- **Ceasing to populate `r_h`** is schema-legal and touches no other field.
  Safe as a Tower-side change.
- **Deleting the field** is not in scope tonight and must go to the Mac lane as
  a written contract item.
- The **cheirality gate is not to be touched.** It is the asset here.
