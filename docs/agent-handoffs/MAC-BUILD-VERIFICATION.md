# Mac verification — the Swift compiled, and what it cost

**Answers `IOS-EXECUTION-PLAN.md` §3.1 and §3.2.** Read this before
writing more iOS-facing work: it says which of the plan's assumptions
survived contact with a compiler and which did not.

**Lane:** Mac/iOS. **Branch:** `ios/world-builder-integration`.
**Tower lane integrated:** `integration/world-builder-lifecycle-v1` @ `d0291c1`.
**Date:** 2026-08-26.

**Toolchain that produced every result below:** Xcode 26.6 (17F113),
Swift 6.3.3, iOS SDK 26.5, Simulator iPhone 17 Pro (iOS 26.5), physical
iPhone 16 Pro (iPhone17,1).

---

## 1. The headline

**All 4,383+ lines of `[BUILD UNVERIFIED]` Swift compile.** Debug,
Release and a signed device build, all clean and now **warning-free**.
**388 tests pass, 0 fail.**

The static review in `IOS-STATIC-REVIEW.md` was accurate: §4.1's fix was
the only compile error in the new Swift, and §4.2/§4.3 were correctly
retired — no `@MainActor` was needed on a test class, and the
`URLProtocol` stubs' `static var` is not an error at `SWIFT_VERSION = 5.0`.

**Both new suites executed rather than passing by absence.** The failure
mode §3.1 warns about did not recur:

| Suite | Executed |
|---|---|
| `WorldGeometryDecoderTests`, `…CoordinatesTests`, `…StoreTests`, `…RetryTests`, `WorldFragmentsModelTests`, `WorldBuilderViewModelGeometryTests` | yes |
| `ObjectMemoryDecodingTests`, `…TransportTests`, `…ClientStateTests`, `…ViewModelTests`, `…CopyTests` | yes |

§3.2's other acceptance check also holds: the no-overclaim sweep asserts
`XCTAssertFalse(strings.isEmpty)` before scanning
(`ObjectMemoryTests.swift:951`), so it cannot pass over zero strings.

---

## 2. Commits

| Commit | What |
|---|---|
| `df117e7` | merge of `361b7e3` (superseded within the hour — see §3) |
| `ac43cdd` | merge of `d0291c1`, conflicts resolved, **the compile gate** |
| `1e5ce39` | geometry decoder pinned against real Tower bytes |
| `870692d` | Object Memory's three branches pinned against real Tower bytes |
| `7fa6a80` | the isolation the Swift 6 language mode would refuse |

22 files, +1,736 / −113 against `d0291c1`. **`tower/` untouched.**

---

## 3. Read this before the next handoff: the branch moved under me

I fetched, merged `361b7e3`, and started building. Fifteen minutes later
the same branch was at `d0291c1` — **80+ commits further on, including
every `[BUILD UNVERIFIED]` iOS commit and the execution plan itself.**
The first merge was wasted work and the plan I was working from was two
editions old.

Not a complaint, and nothing was lost. But if the two lanes keep running
concurrently, **say in the handoff when a lane is still writing**, so the
other one waits for a quiescent point rather than merging a moving branch.

---

## 4. Conflicts — five unions and one judgment call

Six files conflicted, all at the World Builder seam, because both lanes
edited it. Five were unions of independent additions (session binding on
one side, geometry on the other). Two duplicates were dropped: a second
`WorldBuilderIntegrationTests` file reference in the pbxproj, and a
second `stateSubject`.

**The one that was not a union, and the only place a reviewer should
look hard:**

The Tower lane's geometry emission was written into `publishLastReport()`
and read `envelope`, which this lane's earlier refactor had moved out of
scope — the two edits had never seen each other. `publishLastReport()`
also runs on a **capture-bracket change**, where the Tower has said
nothing new, so a send there would fire on a phone-side event.

Moved to `apply(_:)`, which is where the envelope arrives. That preserves
the "one send per arriving payload, unfiltered" semantics its own comment
asks for, and `WorldBuilderViewModel` still does the revision filtering,
so the ~2 s heartbeat costs nothing.

---

## 5. The one real defect the tests caught

`ObjectMemoryClient.get(_:query:)`. `JSONSerialization.jsonObject(with:)`
**throws** on a malformed body rather than returning something the
`as? [String: Any]` cast rejects — so only the cast path reached
`.undecodable`, and every genuine parse failure fell to the generic catch
and was relabelled `.transport`.

That is not cosmetic. `ObjectMemoryClient` maps `.transport` to the
shell's `.disconnected`, so **a Tower serving malformed JSON would have
told the wearer the network was down.** A body that arrived and could not
be read is now `.undecodable`.

Caught by `testAnUnreadableBodyIsUndecodableRatherThanEmpty`, which had
asserted the right behaviour all along.

**This is `IOS-EXECUTION-PLAN.md` §6.3's first item, and it was not
diagnostics-only.** The other two halves of §6.3 remain open and are
still diagnostics-only — see §9.

---

## 6. Validated against a live Tower, not just a mock

The Tower was started on the Windows host from this Mac over SSH
(`tower.main:app`, `--env-file .env`, plus `TOWER_OBSERVATION_ROOT`
in the process environment — **`.env` was not modified**).

### 6.1 The app, running, against the real Tower

The real `TowerClient`, real `TowerWorldBuilderClient`, real decoder,
Simulator, over Tailscale. Console in order, nothing elided:

```
[Glasses][Init] GlassesConnection created            <- exactly one
[Glasses][Tower] ping sent / pong validated          <- pong still first
[Glasses][Tower] receive loop started
[Glasses][Tower] cartridges sent                     <- after the pong
[Glasses][Tower] cartridges declared: world_builder/status available=true
[Glasses][WorldBuilder] awaitingFirstUpdate binding=none
[Glasses][Tower] result_subscribe(world_builder) sent
[Glasses][Tower] result_subscribed: sub-1 world_builder/status
[Glasses][Tower] cartridge_result: world_builder/status seq=1 revision=db9ae368b5403525
[Glasses][WorldBuilder] idle binding=none
```

**`world_builder.status/2026-08-25` is accepted.** The refusal sentence
that was on the phone on 2026-08-25 is gone, against a Tower actually
serving the new identifier.

`idle` is correct and was verified against the payload rather than
assumed: the result channel answers with the most-recently-updated world,
which is `54ec98ff…`, whose own `lifecycle.evidence` reads *"the world
exists and has no sessions"*. `binding=none` is also correct — no capture
bracket is open, and §9 of the boundary document says the Tower's own
state passes through unchanged there.

### 6.2 Object Memory, through the app's own client

`ObjectMemoryHTTPClient` was driven against the live route for all three
branches, then the responses were pinned as fixtures:

| Request | recordable | observed | observation |
|---|---|---|---|
| `last-seen/laptop` | true | true | present |
| `last-seen/laptop?retention_days=1e-07` | true | false | **nil** |
| `last-seen/person` | **false** | false | **nil** |

All three **HTTP 200**, as §3.2 requires. `observations` returned 55,
`recorded_classes` `["laptop", "cell phone"]`, contract
`object_memory.observations/2026-08-26`.

### 6.3 Geometry, over HTTP

`GET /worlds/3dd986b1…/geometry/manifest?session_id=dd5d13a2…` → 200,
16,047 bytes, contract `world_builder.geometry/2026-08-25`, **51 segments
of which 19 carry points** — the 19 islands the transport was designed
around, confirmed on the wire. `pose_convention` matches this build's
expected nine keys exactly. Segment 1 → 200, 79 points, `point_sampling:
"none"`, anchor pose at identity.

### 6.4 What is now pinned rather than argued

Three fixtures taken verbatim off the running Tower, so the decoders are
tested against the Tower's own bytes and not against a reading of its
source: the status snapshot (pre-existing), the geometry manifest and
segment chunk (new), and Object Memory's three branches (new).

---

## 7. Isolation — twelve warnings, five of them future errors

`SWIFT_DEFAULT_ACTOR_ISOLATION = MainActor` on the app target quietly
makes every pure value type main-actor isolated, **including its
synthesized `Equatable` conformance and its memberwise `init`**. So a
`Sendable` struct could not be compared inside an actor, a decoder could
not be called off the main actor, and `= WorldGeometryClient()` as a
default argument was a main-actor call from a nonisolated context.

**Two were a real race, not a formality.** `TowerClient` sends with
`[weak self]` and then hops to the main actor in a nested `Task`. A weak
capture is a *mutable* binding, and reading the enclosing closure's copy
from concurrently-executing code is the thing the rule forbids. Both
Tasks now re-capture `[weak self]` themselves.

**Worth knowing for future iOS work in this repo:** any new value type in
the app target needs `nonisolated` if it will cross an actor boundary or
be used as a default argument. `MonotonicClock` already carried the
comment explaining this; the pattern is now applied consistently.

Clean Debug, Release and device builds are **warning-free**, so a new
warning during the physical run will be visible rather than lost in noise.

---

## 8. Physical validation — the app runs on the phone

**The app is installed, trusted, launched and connected on the physical
iPhone 16 Pro.** This is the first time any of it has run on the real
device: every prior claim in this repository was Simulator-only.

Signed `Apple Development: tv.lloyd@icloud.com`, profile
`iOS Team Provisioning Profile: com.tristanvarner.Glasses`. The launch
refusal from the earlier attempt was **not** the locked phone recorded in
`WORLD-BUILDER-INTEGRATION.md` §5 — it was an untrusted developer
profile, cleared by the wearer in Settings → General → VPN & Device
Management. One tap, one time per certificate.

### 8.1 Cold launch on the device, against the live Tower

```
[Glasses][Init] GlassesConnection created                    <- exactly one
[Glasses][Tower] connection attempt: ws://100.110.156.55:8000/ws
[Glasses][Registration] state changed: RegistrationState(rawValue: 3)
[Glasses][Devices] devicesStream changed: count=1 ids=["5161af8fd5447c3389d04546819fb7ec"]
[Glasses][CameraPermission] check failed: All discovered devices are powered off or disconnected
[Glasses][Tower] ping sent / pong validated                  <- pong still first
[Glasses][Tower] receive loop started
[Glasses][Tower] cartridges sent                             <- after the pong, never before
[Glasses][Tower] cartridges declared: world_builder/status available=true
[Glasses][WorldBuilder] awaitingFirstUpdate binding=none
[Glasses][Tower] result_subscribe(world_builder) sent
[Glasses][Tower] result_subscribed: sub-1 world_builder/status
[Glasses][Tower] cartridge_result: world_builder/status seq=1 revision=2443af56fca5ce87
[Glasses][WorldBuilder] idle binding=none
```

**Every cold-launch check in `WORLD-BUILDER-INTEGRATION.md` §6.1 passes
on hardware**, including the two the Simulator cannot answer:

- `RegistrationState(rawValue: 3)` — the phone is **registered** with
  Meta's wearables service. The Simulator reports `0` and says
  "Meta AI unavailable".
- **The Ray-Ban glasses are discovered**, `count=1`, id
  `5161af8fd5447c3389d04546819fb7ec`. DAT sees them. They are powered off
  or out of range, which the app reports as exactly that rather than as
  an error.

`world_builder.status/2026-08-25` is accepted on the phone, and `idle` is
the honest answer (§6.1).

### 8.2 One packaging observation, from the device only

The device console carries ~30 `objc[…] Class … is implemented in both`
warnings: **`MWDATCamera.framework` and `MWDATMockDevice.framework` both
embed the same `SUPMediaStream*` and `FB*` classes.** The runtime's own
words are "may cause spurious casting failures and mysterious crashes".

This is the vendored `MetaWearablesDAT` 0.9.0 package, not this
repository's code, and nothing has misbehaved because of it. Recorded
because it is invisible in the Simulator and because it is the first
thing to suspect if the camera path ever fails in a way that makes no
sense. Dropping `MWDATMockDevice` from the device build would remove it,
if it ever earns the attention.

### Still not validated, and why

| | Status |
|---|---|
| App on the physical iPhone, Tower connected | **DONE** — §8.1 |
| Glasses **powered on**, camera streaming | **not done** — discovered, powered off. Needs a person to open them |
| Frames from the real camera reaching the Tower | not reached, blocked on the above |
| **P3 — fragments appearing during a walk** | **not reached.** The geometry *transport* is proven live (§6.3) and the decoder is pinned, but the app has never fetched geometry for a world it was watching: the result channel serves the newest world, and the newest world has no geometry. This needs a walk, not a fix |
| P11 — the sidestep experiment | not reached |
| P9/P10 — loop closure | not reached |
| Sender FPS against the physical baseline | not reached |
| Redaction against a real face | not reached, and §8 of the plan says this corpus cannot answer it anyway |
| Calibration | no board printed |

**The single next physical action is: power on the glasses.** Everything
downstream of that is code that is now built, installed, running and
connected.

## 9. For the Tower lane

**Nothing is blocked on you.** Two notes, neither urgent:

1. **`IOS-EXECUTION-PLAN.md` §6.3's remaining two halves are confirmed
   present** in the geometry client — a `JSONSerialization` throw
   labelled `.transport`, and a `CancellationError` swallowed into
   `.transport`. Left alone deliberately: no test reproduces them and the
   plan classifies them as diagnostics quality. The Object Memory one was
   fixed only because a test proved it (§5). Say the word if you want
   them aligned.
2. **§6.1 (fetching all 51 segments when 19 are usable) is confirmed real
   on live data** — the manifest names 51 and 32 resolve to nothing.
   Deliberately not optimised: the plan asks for the product outcome
   (latency, battery on a live walk) to be measured, and that measurement
   needs a walk that has not happened.

**Contract identifiers, verified equal on both sides:**
`cartridge_results.envelope/2026-08-23`,
`world_builder.status/2026-08-25`,
`world_builder.geometry/2026-08-25`,
`object_memory.observations/2026-08-26`.

---

## 10. Reproducing all of it

```bash
cd ios
xcodebuild -project Glasses.xcodeproj -scheme Glasses -configuration Debug \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' build
xcodebuild -project Glasses.xcodeproj -scheme Glasses -configuration Release \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' build
xcodebuild -project Glasses.xcodeproj -scheme Glasses -configuration Debug \
  -destination 'platform=iOS,id=<device-udid>' build          # signs
xcodebuild -project Glasses.xcodeproj -scheme Glasses -configuration Debug \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' test
```

Starting the Tower from this Mac, since `Start-Process` does not survive
a non-interactive SSH session and the quoting through `ssh powershell
-Command` does not survive either — **write the script to the host and
run it by path**:

```powershell
# C:\Users\tvllo\tower_start.ps1
$root = 'C:\Users\tvllo\Projects\Glasses\tower'
$cmd = 'cmd.exe /c cd /d ' + $root + ' && set TOWER_OBSERVATION_ROOT=data/object_memory && ' +
       '.venv\Scripts\python.exe -m uvicorn tower.main:app --env-file .env --host 0.0.0.0 --port 8000 > tower.log 2>&1'
Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $cmd }
```

```bash
ssh tower 'powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\tvllo\tower_start.ps1'
```

Note `TOWER_OBSERVATION_ROOT` is **not** in the Tower's `.env`, so
`/object-memory/*` answers 404 without it. Everything else comes from
`.env`.
