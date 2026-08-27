# World Builder — physical validation plan

**Branch:** `world-builder/next-generation` @ `c3aaae0` or later
**Prepared by:** the World Builder lane, which cannot wear the glasses
**Status:** NOT RUN. Every claim below is a prediction.

---

## 0. Why this exists now

Everything replay can settle has been settled. The branch has moved the corpus
from 346 to 591 solved poses, from 47,429 to 75,369 published points, from 28 of
48 legible fragments to 91 of 94, and taken cross-segment registration from zero
registered segments on every capture to real clusters on two of them.

**None of that is the milestone.** The milestone is that a wearer walks around a
room, looks at the phone, and recognises the room. Replay cannot answer it, and
three specific questions now block on a person:

| # | Question | Why replay cannot answer it |
|---|---|---|
| **P1** | Does a normal walk now produce a recognisable room? | The corpus says fragments are legible at 140pt. Legible is not recognisable. |
| **P2** | Is a registered cluster geometrically *correct*? | A wrong Sim3 fits at 1.62 px with 88% of points under 3 px while being 3.2x wrong on scale. Nothing automated catches it. |
| **P3** | Does deliberate translation raise the registrable fraction? | The dominant registration refusal across the corpus is "the wearer stood still". No algorithm change fixes a capture that has no baseline. |

P3 is the highest-leverage experiment available and has been outstanding since
`WORLD-BUILDER-STATUS.md` P11. It is the one to run first if only one is run.

---

## 1. What to run

### Tower

```
cd C:\Users\tvllo\Projects\Glasses-world-builder\tower
git log --oneline -1        # expect c3aaae0 or later on world-builder/next-generation
```

Start the capture-following builder against a live capture:

```
.venv\Scripts\python.exe scripts\world_build_session.py --follow-capture <capture dir>
```

Use `--follow-capture`, never `--frames`: the frames path fabricates `source_seq`
and drops `received_at`.

### iOS

Whatever the Mac lane currently has. **The registration work in
`docs/agent-handoffs/WORLD-BUILDER-NEXT-GENERATION-MAC.md` §4b is NOT required
for P1 or P3** — those read Tower-side output. It IS required for P2, because
without it the phone cannot draw a registered cluster at all.

If the Mac lane has not landed §4b, run P1 and P3 anyway and read P2 from the
Tower.

---

## 2. P3 — the sidestep experiment (run this first)

**Hypothesis:** the registrable fraction is limited by capture technique, not by
the software. If true, a walk with deliberate lateral translation should register
a materially larger share of its points than a walk of the same length spent
turning in place.

### Procedure

Two captures, same room, same lighting, back to back. **Both about 90 seconds.**

**Capture A — "pan":** stand roughly in one spot and turn. Look around the room
the way a person naturally does when showing someone a space. Do not deliberately
walk. This is the control, and it is what most of the existing corpus looks like.

**Capture B — "sidestep":** keep the head still relative to the body and *move
the body*. Step sideways along walls. Walk an arc around a table or chair,
keeping it in view. Cross the room and come back along a different line. The rule
of thumb: **the camera should travel at least its own distance to what it is
looking at.** For a table 2 m away, move 2 m while watching it.

Avoid in B: standing and turning, walking straight at a wall (the epipole sits in
the image and parallax is genuinely ill-conditioned there — measured at 82%
refusal in a simulated hallway), and fast motion.

### What to record for each

```
# after the walk, from the Tower
.venv\Scripts\python.exe scripts\world_inspect.py --world <world id>

# then registration, WRITING the result
.venv\Scripts\python.exe scripts\world_registration.py --world <world id> --write --format json > reg-<A|B>.json
```

Preserve: the world id, `derived/<session>/manifest.json`, `reg-A.json`,
`reg-B.json`, and a screenshot of the fragments grid for each.

### Pass criteria

**The prediction is that B registers a materially larger fraction of its points
than A.** Concretely, from each `reg-*.json`:

- `points_registered / points_total`
- the count of pairs refused with "the wearer stood still"

**PASS:** B's registered fraction is at least double A's, and B's "stood still"
refusals are a much smaller share of its pairs.

**REFUTED:** B registers no better than A. That would be the more valuable
result: it would mean the limit is not capture technique, and the next work is
candidate retrieval rather than a walking protocol. Report it plainly — this
plan is not written to be confirmed.

Best corpus figures to beat, for scale: `2e6cffa2` registers 44% of its points,
`e1c52b9f` 25%, and five other captures register 0%.

---

## 3. P1 — does it look like the room?

One walk, 60–90 s, using capture-B technique. Watch the phone **during** the
walk, not only after.

### Expected, and what each failure means

| Observation | Meaning |
|---|---|
| Fragments appear progressively during the walk | The transport claim holds |
| Fragment cards show structure spread across the card | The point-quality gates did their job |
| **More fragment cards than you remember** | Expected. Segments rose ~81% corpus-wide, because breaks that used to be silently swallowed are now boundaries |
| A card is empty or shows a single dot | The gates are over-refusing. Capture `derived/<session>/manifest.json` — `points_discarded` says how many were refused and why |
| `unresolvedCount` unchanged from before the branch | Correct. This branch does not resolve new areas; it stops publishing coordinates it cannot defend and stops abandoning keyframes |
| Fewer fragments than before | Something regressed; `segment_count` should rise, not fall |

**The honest bar:** can you tell which fragment is which part of your room? Not
"is it pretty". If the answer is no, say so and say what it looks like instead —
that description is the next research input, and no metric on this branch
substitutes for it.

---

## 4. P2 — is the registered cluster correct?

Only meaningful on a walk that registers something, so run it on capture B if B
registered.

### Procedure

Walk a **loop**: leave a distinctive corner, go around the room, and return to
that same corner from the same direction. The revisit is the point — it is what
gives composition something to check itself against, and the current admitted
graph is a path with no cycle at all, so nothing has ever checked it.

### Checking it

From `reg-B.json`, the registered segments and their `reference_segment`.
Segments sharing a reference are claimed to be in one space.

**On the phone (requires Mac §4b):** the registered fragments should line up
into a plausible partial floor plan. Look for:

- **A fold.** One part of the room laid through another at an angle. That is a
  wrong rotation, and rotation reciprocity is a guard against it that has never
  fired on real data — every solvable pair in the corpus agrees to under 2.4°.
- **A wrong scale.** One region sensibly proportioned and another obviously too
  large or too small, joined seamlessly. This is the dangerous one: it looks like
  a slightly odd floor plan rather than an error, and reprojection error does not
  catch it.
- **A dot.** A segment collapsed to a point at another's origin. This is refused
  by the scale gate and by a stored-record invariant, so seeing one is a real
  finding.

**PASS:** the registered fragments agree with the room's actual layout.
**FAIL:** any of the above. Preserve `reg-B.json` — every clause's measured value
is in `pairs[].clauses`, so a wrong admission can be traced to the clause that
let it through.

---

## 5. What NOT to conclude

- **Do not read more fragments as a regression.** It is the expected consequence
  of no longer abandoning keyframes after a solve break, and it comes with ~71%
  more solved poses.
- **Do not read fewer published points as geometry loss.** Roughly 20% of points
  are now refused as unpublishable; `points_discarded` in the manifest accounts
  for every one, and `points + discarded == points_triangulated` exactly.
- **Do not tune anything from a single walk.** Per-capture variance in this
  project is large and bidirectional — one capture has gone 27→111 solved poses
  and another 94→61 under the same change. Anything that looks like a threshold
  problem should go back through
  `scripts/world_builder_corpus_benchmark.py`, not into a constant.

---

## 6. If something is blocked

P2 needs the Mac lane's §4b to be visible on the phone. P1 and P3 do not. If §4b
is not ready, run P1 and P3, read P2's numbers from `reg-*.json`, and record that
the visual half is outstanding rather than skipping the experiment.
