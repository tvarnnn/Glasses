# Object Memory on iOS — handoff to a machine with a Swift toolchain

**Everything described here is UNCOMPILED and UNVERIFIED.** It was written on
Windows, where `swiftc`, `swift` and `xcodebuild` are all absent. No build has
been attempted, no test has been executed, no simulator has been launched, and
nothing has been signed or run on a device. Treat every claim below about
behaviour as *intent*, and every claim about correctness as *unchecked*.

What **was** verified on the authoring machine: the Tower half. The Swift model
was written against a live dump of `build_observations` / `build_last_seen` run
over the real 55-observation corpus in `tower/data/object_memory`, field by
field, not against the contract document alone. `tower` was not modified, and
its suite still reports **1497 passed, 30 skipped**.

---

## 1. What was built

The first product surface for Object Memory: a workspace that shows what the
Tower's object memory recorded, over the two read-only `GET` routes in
`docs/contracts/OBJECT-MEMORY.md`.

### Files added

| File | What it is |
|---|---|
| `ios/Glasses/Workspaces/ObjectMemory/ObjectMemoryModel.swift` | Wire types (`ObjectObservation`, `FrameReference`, `ObjectMemoryEnvelope`, `ObservationListing`, `LastSeenAnswer`, `ObjectMemoryRetention`) and `ObjectMemoryDecoder`. |
| `ios/Glasses/Workspaces/ObjectMemory/ObjectMemoryCopy.swift` | **Every user-facing string.** The product constraint lives here. |
| `ios/Glasses/Workspaces/ObjectMemory/ObjectMemoryClient.swift` | `ObjectMemoryHTTPClient` (transport), `ObjectMemoryService` / `ObjectMemoryState`, the `ObjectMemoryClient` protocol, `TowerObjectMemoryClient`, `ObjectMemoryViewModel`. |
| `ios/Glasses/Workspaces/ObjectMemory/ObjectMemoryWorkspaceView.swift` | The screen. Contains **no** user-facing string literal of its own. |
| `ios/GlassesTests/ObjectMemoryTests.swift` | 5 suites: decoding, transport, client state, view model, copy. |

### Files changed

| File | Change |
|---|---|
| `ios/Glasses/Workspaces/CartridgeWorkspace.swift` | Added the `objectMemory` case (fifth). |
| `ios/Glasses/Cartridges/Cartridge.swift` | Attached the workspace to `object-memory`, and **rewrote its catalog summary**. It read *"Remembers where objects were last seen"* — the one claim the cartridge's contract spends four sections refusing. `status` stays `.planned`. |
| `ios/Glasses/Cartridges/Integration/CartridgeClients.swift` | Added `objectMemory`, defaulting to a real `TowerObjectMemoryClient` rather than an unavailable stub — it is the first cartridge whose Tower half answers. |
| `ios/Glasses/ContentView.swift` | One `switch` arm, inside `TowerReachabilityReader`, with no `GlassesConnection`. |
| `ios/GlassesTests/ProductShellTests.swift` | Two edits — see §5. |
| `ios/Glasses.xcodeproj/project.pbxproj` | Registered `ObjectMemoryTests.swift` at all four points. |
| `docs/contracts/OBJECT-MEMORY.md` | iOS consumer rows, status, and a correction to the `confidence` table (§4). |

The app target uses a `PBXFileSystemSynchronizedRootGroup` for `Glasses/`, so
the four new app sources need no project edit. **The test target does not** —
`GlassesTests` is an ordinary `PBXGroup`, and a file absent from it "passes by
not existing", which has happened here before. `ObjectMemoryTests.swift` is
registered as a `PBXBuildFile` (`7F2D5E31…`), a `PBXFileReference`
(`C4A17E9B…`), a child of the `GlassesTests` group, and a member of the
`Sources` build phase. Verify all four survived.

---

## 2. The product constraint, and where it is enforced

This cartridge does not know where anything is. `spatial_ref` is `null` at every
level of every payload, always. The `where` object is a **frame reference** — a
capture id, a frame sequence number, a camera, a box in normalised *frame*
coordinates — and it is a pointer back into a recording, not a place.

Three claims travel in the payload and constrain every sentence:

- `claim: "category-was-visible-once"` — a record says a category was in view
  **once**, never that it is there now;
- `identity: "category-not-instance"` — `laptop` means *a* laptop, never "your
  laptop", and two records are not evidence about the same object;
- `absence_means: "not-observed-by-this-cartridge"` — an empty answer is about
  what the camera captured, never about the world.

**Where this is enforced, in descending order of load-bearing-ness:**

1. `ObjectMemoryCopy` produces every string, and the view renders only from it.
   `ObjectMemoryCopyTests` runs `everyString(for:)` and `everyStaticString`
   through a forbidden-phrase list — present-tense possession and location
   claims, generated per recorded class ("your laptop", "the laptop is",
   "laptop is on", …) plus class-independent ones ("still there", "on the map",
   "last seen in session", "there is no ", …).
2. `testACaptureIdentifierNeverAppearsWithoutBeingCalledAFrameReference`
   encodes the brief's own failure example: a session id may not appear in any
   string that does not also say "Frame reference".
3. `testEveryRecordCarriesTheClaimAndTheNotAPlaceCaveat` — a rendered record
   must include a string containing "not a place" and one containing "does not
   say anything about now".
4. `ObjectMemoryDecoder` **refuses** a populated `spatial_ref` (envelope and
   frame) and refuses any changed claim value, rather than ignoring either.
5. `testTheCatalogSummaryDoesNotPromiseALocation` — the drawer row, which is the
   first sentence anyone reads about this module.

**The one hole**: the rule "the view writes no prose" is a convention the
compiler does not check. A `Text("…")` literal added to
`ObjectMemoryWorkspaceView.swift` escapes every test above. If you want that
closed mechanically, a lint step over that file for string literals inside
`Text(` is the shape it would take.

### The exact copy

For a found record (`laptop`, high confidence, capture `22e9d428…`, frame 3410):

```
A laptop was visible
The Tower received this frame on 24 Aug 2026 at 2:31 PM. That is the Tower's
receipt time, not the moment the shutter fired.
A category was in view once. That is the whole claim: it does not say anything
about now, and it cannot tell one laptop from another.
  ▸ Frame reference and detection detail
    Frame reference: capture 22e9d428…, frame 3410, camera glasses-camera.
    That is a pointer back into a recording, not a place. Nothing in this
    memory knows where anything is in a room.
    Within that picture the detection covered 33% to 55% across and 51% to 77%
    down. Those are fractions of the frame, not distances in a room.
    The frame it points at is kept capture-side, under a retention this
    cartridge neither sets nor enforces. Removing this record would not reach
    that imagery.
    Detector confidence: high. Strongest score while it stayed in view: 100%.
    Score in the frame above: 93%. None of these is a calibrated probability;
    they are detector output.
    This record holds a label, a score and a box. No pixels.
```

For an empty result on a class the cartridge does record:

```
No record of a laptop
This memory holds no record of a laptop within the window it can see. That is a
statement about what the camera captured, not about what exists: it may never
have been pointed at one, or the detector may not have scored it highly enough
to write down. Absence of a record is not absence of the thing.
```

And for a class it never records — a **weaker** silence, worded differently on
purpose:

```
Never looked for
"teapot" is not a category this memory ever records, so it has never been looked
for. Its absence carries no information at all.
```

---

## 3. Architecture notes for review

**Availability.** This is the one genuinely novel piece. World Builder's
contract is *declared* over the socket before anything is asked for, so
`TowerCapabilities` can resolve it. Object Memory's contract travels in the
`contract` field of an **answer**, so the only way to learn whether this Tower
serves object memory is to ask it. That makes "nothing has been asked" a real
state, and `CartridgeAvailability`'s four cases cannot express it — "nothing
declared" and "nothing asked" are different and only the first is
`.noContract`.

So: `ObjectMemoryService` holds what asking has taught the client;
`availability(isTowerReachable:)` projects it onto the shared vocabulary
conservatively (unprobed + reachable → `.noContract`); and
`knownAvailability(isTowerReachable:)` returns `nil` in exactly that case. The
workspace reads the second, so the control that would find out is not hidden on
the grounds that nobody has used it yet.

**`TowerCapabilities` was deliberately not touched.** No entry in `declared`, no
addition to `supported`, no `towerCartridgeNames` mapping — those describe
socket-declared cartridges, and three existing tests pin them. Adding Object
Memory there would have been inert (there is no name mapping for it to resolve
through) and would have broken `testTheTowerDeclaresOnlyTheWorldBuilderContract`
for no gain. If the Tower ever declares object memory over the socket, that is
the moment to revisit.

**404 is a state, not an error.** `TOWER_OBSERVATION_ROOT` unset ⇒ 404 ⇒
`ObjectMemoryState.noObjectMemory`, `service == .notConfigured`, availability
`.noContract`, and the *object memory's own wording* rather than the shared
"this Tower has not declared a contract" sentence — because the Tower did
answer, and what it said was about its configuration.

**An unreachable Tower maps to `.disconnected`, not `.failed`.** A
`CartridgeFailure` of kind `.transport` yields `CartridgePhase.disconnected`,
which is the shell's existing "the capability exists and cannot be reached
right now". The ask control stays **enabled** while the socket is down, because
reachability there is the *WebSocket's* and object memory travels over HTTP;
refusing on the strength of a different transport would hide a request that
might succeed. The caveat is shown instead.

**Nothing polls.** No timer, no subscription, no socket. One request per tap.

**Read-only, permanently.** Two `GET`s. No delete path exists on this side and
none may be added: real deletion is `scripts/object_query.py --purge-all`, typed
by a human.

---

## 4. Verified against the live route

The Swift types were checked field by field against an actual dump, not the
document. Two things the document alone would have got wrong:

1. **`confidence` has four values, not three.** `tower/confidence.py` defines
   `unknown`, returned by `Confidence.from_score(None)`, so it reaches the wire
   for any record with a `null` `best_score`. A decoder accepting only
   `low|medium|high` refuses a real record. Fixed in the decoder, and the
   contract table is corrected.
2. **`retention_tag` is `"default"`** on the real corpus; the document only says
   "the record's own retention class". Decoded as an opaque string.

Also confirmed live: `observation_count` is 55 across `laptop` and
`cell phone`; `effective_days` is `30.0`; `clamped` is a real `bool`;
`spatial_ref` is `null` at both levels; `bounding_box_normalized` is
`(x1, y1, x2, y2)` (`engine.py` divides by width and height in that order);
`last-seen` for `teapot` answers 200 with `recordable: false, observed: false`.

---

## 5. Changes to existing tests, and why

`ProductShellTests.CartridgeClientTests` asserts "**nothing in this app produces
Tower data, because the Tower produces none**" over a table of four clients.
That premise is now false for Object Memory — its Tower half genuinely answers —
so it is **not** in that table, and the suite's doc comment now says so. It is
covered by `ObjectMemoryTests` instead, which asserts the stronger properties
that actually apply to it.

`testEveryOpenableCartridgeHasAClient` **does** still cover it: the client id is
read off `CartridgeClients()` rather than hardcoded, so a sixth cartridge cannot
satisfy it with a string in the test file.

Nothing else needed changing. `object-memory` stays `.planned`, so the roadmap
pin in `testHavingAWorkspaceDoesNotPromoteACartridgesStatus` is untouched;
`visual-qa`, `accessibility` and `environmental-memory` remain workspace-less, so
`testAStoredCartridgeWithoutAWorkspaceDoesNotReopen` is not vacuous.

---

## 6. Most compiler-sensitive areas

Ranked by how likely they are to be the first thing that fails:

1. **`ObjectMemoryStubProtocol` in the test file.** A `URLProtocol` subclass with
   `static var handler` / `static var requestedURLs`. The test target is
   `SWIFT_VERSION = 5.0` and has **no** `SWIFT_DEFAULT_ACTOR_ISOLATION`, so this
   should be a warning at worst — but it is mutable global state and it is the
   least conventional thing here. If it fights you, `nonisolated(unsafe)` on the
   two statics is the fix.
2. **Default `MainActor` isolation on the app target.**
   `SWIFT_DEFAULT_ACTOR_ISOLATION = MainActor` is set for `Glasses` (not for
   `GlassesTests`). Every new app type is therefore implicitly `@MainActor`, and
   every new test class was written `@MainActor` for that reason. If a test
   fails to see an app type, that is why.
3. **`Picker` with an optional tag.** `Text(...).tag(String?.none)` and
   `.tag(String?.some(objectClass))` against a `Binding<String?>`. Correct, and
   the exact spelling matters — a bare `.tag(nil)` will not infer.
4. **`DisclosureGroup(isExpanded:content:label:)`** trailing-closure form in
   `ObjectObservationRow`.
5. **`URL.path`** in `testAClassWithASpaceIsPercentEncodedIntoThePath` is
   deprecated in favour of `path(percentEncoded:)`. Expect a warning; if the
   target treats warnings as errors, switch it.
6. **`Date.formatted(date:time:)`** in `ObjectMemoryCopy.timeLine` — used
   elsewhere in the app already, so it should be fine.

The four things this codebase has been bitten by before were watched for
specifically: no empty collection literal in an `Any` slot (the empty-listing
fixture writes `[[String: Any]]()`); every in-body `init` that suppresses a
memberwise initializer has one written out; the test file is registered in the
project; and every nullable wire field is an Optional, with
`testNullScoresStayNilRatherThanBecomingZero` holding it.

---

## 7. Running the Tower route locally, to exercise the screen

From `tower/`, against the real corpus:

```bash
TOWER_OBSERVATION_ROOT=data/object_memory ./.venv/Scripts/python.exe -m uvicorn tower.main:app --host 0.0.0.0 --port 8000
```

(Windows PowerShell: `$env:TOWER_OBSERVATION_ROOT = "data/object_memory"` then
the same `python -m uvicorn …`.)

Check it by hand before pointing the phone at it:

```bash
curl 'http://localhost:8000/object-memory/observations' | head -c 400
curl 'http://localhost:8000/object-memory/last-seen/cell%20phone'
curl 'http://localhost:8000/object-memory/last-seen/teapot'
curl 'http://localhost:8000/object-memory/observations?retention_days=3650'
```

Expect: 55 observations; `cell phone` observed; `teapot` **200** with
`recordable: false, observed: false`; and the last one still `effective_days:
30.0` with `clamped: true` — the widening refused, and reported.

**Startup with the variable unset is the other half of the test.** Both routes
answer 404, and the app must show *"This Tower serves no object memory…"* rather
than an empty memory. That is one of the two states most likely to be got wrong
in a way a screenshot would not reveal.

`TowerConfiguration.httpBaseURL` is hardcoded to `http://100.110.156.55:8000`.
Point it at wherever the Tower actually is before running on device.

---

## 8. What only physical validation can settle

Everything below needs a Mac, a phone, and a Tower — none of it is reachable
from a test:

1. **That it compiles at all.** Nothing here has been through a compiler.
2. **The four screen states, seen.** Records; an empty answer; a Tower with
   `TOWER_OBSERVATION_ROOT` unset; a Tower that is off. The third and fourth
   must look and read like *different* things, and only a person looking at both
   can confirm they do.
3. **Whether the copy survives being read fast.** The tests prove no string
   *asserts* possession or location. They cannot prove a person skimming a row
   does not come away believing their laptop is somewhere. Show the found-record
   screen to someone who has not read this document, ask what it told them, and
   see whether the word "where" comes back. **That is the only real test of this
   work**, and it is the one that would justify changing the layout.
4. **55 rows on a phone.** The listing renders every record in one `VStack`
   inside the shell's `ScrollView`. With the real corpus that is 55 rows, each
   with a disclosure. If it is sluggish or unreadable, a `List` or a cap with an
   explicit "showing the most recent N" line is the fix — and the line must say
   it is a display limit, not a retention one.
5. **Timing.** The 10s request timeout against a real Tailscale path to a Tower
   reading a JSONL file.
6. **That opening the workspace disturbs nothing.** `ContentView`'s invariant is
   that `GlassesConnection` is created once per launch and a workspace switch
   does not tear the graph down. Switching into and out of Object Memory during
   a live capture should not interrupt the stream, and
   `[Glasses][Init] GlassesConnection created` should still appear exactly once.
