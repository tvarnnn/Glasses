"""Contract identifiers, and why they are opaque strings.

`IOS-to-Tower.md` section 6 item 6 is explicit that iOS compares contract
identifiers **for equality only**:

    "Contract versioning semantics -- identifiers are compared for
     equality only, so ordering and compatibility remain the Tower's to
     define."

and section 0.1 that the identifier is "an **opaque identifier compared
for equality** (`CartridgeContract`)" which "deliberately does *not*
assume integer versions, ordering, or backward compatibility".

So these are strings, not integers, and nothing may parse them. That is a
deliberate departure from `tower/world_builder/schema.py: SCHEMA_VERSION`,
which is an int -- and the two are not in tension, because they answer
different questions. SCHEMA_VERSION governs whether THIS BUILD can read a
file THIS PROJECT wrote, where a monotonic int and a refuse-on-unknown
rule are right. A contract identifier governs whether ANOTHER MACHINE,
built and shipped separately, implements the agreement we are offering --
and there the only sound operation is equality, because a phone in the
App Store cannot be assumed to know anything about an identifier minted
after it shipped.

Dated rather than numbered, for the same reason: a date makes it obvious
that two identifiers differ without inviting anyone to compute which is
"greater".

Changing a value here is a WIRE BREAK. iOS will report "update the app"
and stop decoding, which is the intended behaviour -- see
`IOS-to-Tower.md` section 0.1. Change one only when the payload's meaning
changes in a way an existing decoder would get WRONG. Adding an optional
field that an older decoder ignores is not that; removing a field,
renaming one, or changing what a field means is.
"""

# The cartridge names iOS keys on. Stable identifiers, not display names.
CARTRIDGE_WORLD_BUILDER = "world_builder"
CARTRIDGE_EXPERIMENTAL_CV = "experimental_cv"
CARTRIDGE_DOCUMENT_MEMORY = "document_memory"
# Present here before it is present in `registry.declare()`, and that is
# not an oversight. The name is what a session URL and a `/health` row
# are keyed on, and both exist now; the socket DECLARATION is a separate
# decision that breaks a pinned iOS test the moment it lands, so it waits
# for the iOS lane to take both halves at once. See
# `docs/agent-handoffs/OBJECT-MEMORY-MAC-HANDOFF.md` section 3.
CARTRIDGE_OBJECT_MEMORY = "object_memory"
CARTRIDGE_SCENE_UNDERSTANDING = "scene_understanding"

# Result types within a cartridge. A cartridge may eventually offer more
# than one; the pair (cartridge, result_type) is what a subscription
# names.
RESULT_TYPE_STATUS = "status"

# The one contract that exists.
#
# Bumped from .../2026-08-23 because `trajectory.pose_count` changed
# MEANING, not merely because a field was added. It used to be
# `keyframes - poses_refused`, which counts a segment anchor -- an
# identity rotation at the origin, by construction -- as a camera
# position. On the 2026-08-24 physical walk that reported "36 camera
# poses" from a build whose manifest read `poses_solved: 0, points: 0`.
#
# A consumer pinned to the old identifier is refused rather than quietly
# served a number that means something different. That is what "compare
# for equality only; a mismatch means we are not talking about the same
# agreement" is for, and a correction is exactly the case where serving
# the old id would be a lie about compatibility. Adding `poses_anchor`
# alone would not have justified this; changing what an existing figure
# counts does.
WORLD_BUILDER_STATUS_CONTRACT = "world_builder.status/2026-08-25"

# The channel's own envelope contract, distinct from any cartridge's.
# A change here affects every cartridge at once, which is exactly why it
# is versioned separately from the payloads it carries.
ENVELOPE_CONTRACT = "cartridge_results.envelope/2026-08-23"

# Every timestamp this channel emits. There is no capture timestamp
# anywhere on the wire (tower/frames.py carries no time field), so a
# Tower timestamp is when the TOWER saw something, never when the glasses
# did. `IOS-to-Tower.md` 0.3 holds observedAt and receivedAt separately
# and will never substitute one for the other; naming the basis on every
# envelope is how that survives the hop.
TIME_BASIS = "tower-receipt"
