# Module Concept — Scene Understanding

## Status

**Concept seed, and a narrowing of an existing module rather than a new one.**
Future. The Tower has not adopted this scope, has not agreed to build it, and
declares no contract for it. It appears in the iOS cartridge catalog because the
iOS app ships a workspace for it — a fact about the phone, not about the Tower
(see `08-IOS-CARTRIDGE-SHELL.md`, "Two axes").

Written from the iOS side while preparing the cartridge integration layer, so
the workspace could cite a real specification rather than an invented one. It is
a proposal, not a decision. `docs/agent-handoffs/IOS-TO-TOWER.md` states what
iOS would need from the Tower if the scope is adopted.

## Relationship to existing modules

`OBJECT-MEMORY.md` already specifies the pipeline this module reads from:

```text
camera frame -> object detector -> multi-object tracker -> observation builder
```

Object Memory is about **history** — where something was last seen, retrieved
later. Scene Understanding is about **now**: what the camera can currently see,
published live and not stored. It is the live half of that pipeline surfaced on
its own, without the persistence layer.

What it takes:
- detection and multi-object tracking;
- the class-versus-identity discipline of Limitation 6.

What it leaves behind:
- persistence of any kind. This module stores nothing;
- retrieval, queries, and "last seen" semantics — those are Object Memory's;
- any attempt at instance re-identification.

If Object Memory is implemented, this should become a live view onto its
tracker rather than a separate pipeline.

## Goal

Give a coarse, anonymous, live read of the immediate surroundings: how many
people and objects the camera can see, roughly where they are, and which way
they are oriented.

## Anonymity Is the Design, Not a Setting

**No identity, at any layer.** No names, no face descriptors, no embeddings kept
for matching, no handle that survives a session.

`ENVIRONMENTAL-MEMORY.md` requires the platform to "avoid biometric identity
features unless a future use case explicitly justifies them and is handled
appropriately". No such use case exists here, and this module must not create
one as a side effect.

A track identifier distinguishes the person on the left from the person on the
right **within one tracking session** and is meaningless afterwards. A handle
that survived sessions would be a re-identification key by function, whatever it
was made of. This module therefore has no persistence at all — which is the
simplest possible guarantee that no such key can accumulate.

Limitation 6's distinction is preserved exactly: an object may carry a **class**
label ("chair"), never an **identity** claim ("your chair").

## Orientation, Not Gaze

`07-PLATFORM-CONSTRAINTS.md` Limitation 8, classified REQUIRES FUTURE
HARDWARE/API: the target glasses have no eye tracking, and nothing in the camera
feed establishes attention.

So this module may report **body/head orientation relative to the camera** and
must describe it as such:

> "facing your direction" — permitted.
> "looking at you", "watching you", "making eye contact" — forbidden, at any
> confidence, in any phrasing.

The reverse holds too: a person in frame has not been established as having been
seen by the wearer.

## Counts Are About the Camera

A count of zero means zero **currently tracked within the camera's field of
view**. It is not a statement about the room, and it is never evidence that
nobody is present — Core Principle 3.

Any surface showing a count must carry that qualification. Field of view is
narrower than human awareness, and a wearer looking at a desk has most of the
room behind the camera.

## Positions

Two frames of reference, and they must not be conflated:

- **camera-relative** — a bearing that changes as the wearer turns their head;
- **world-relative** — only if World Build later exposes a shared spatial
  service, and then only as an explicit architecture evolution.

Any distance is subject to `WORLD-BUILD.md`'s rule without exception: the glasses
are monocular RGB, so a distance is inferred and must be identifiable as an
estimate wherever it is displayed. A bearing is an angle and needs no depth, so
it is not subject to that rule.

## Relationships

The module may report relations between tracks ("next to", "holding", "seated
at"). These are inferences about pairs of inferences and are the least certain
output here; each must carry its own confidence, and the predicate vocabulary is
the Tower's to define.

## Persistence

**None.** This module stores nothing. Its output is live state, replaced as the
scene changes and discarded when observation stops.

Per `04-MODULE-SYSTEM.md`, its data-behavior declaration is therefore: persists
nothing, retains nothing, transmits nothing beyond the local system, and needs no
purge capability because there is nothing to purge. If a future version needs
history, that is Object Memory, and it is a separate architecture decision with a
separate privacy review.

## Failure Behavior

- Weak tracking must reduce confidence, not be smoothed into apparent certainty.
- A lost track disappears rather than being extrapolated to a guessed position —
  Limitation 7: a stale observation must never be presented as current state.
- If the Tower is unavailable, the module is unavailable and reports no scene.

## First-Version Success Criteria

A bounded V1 should demonstrate:

1. person and object detection on real first-person imagery, with measured
   precision/recall;
2. within-session track stability, measured;
3. coarse orientation classification, with its error rate stated;
4. bearing accuracy sufficient for "to your left" to be right more often than a
   coin;
5. an audit confirming no identity-bearing data is produced or retained anywhere
   in the pipeline.
