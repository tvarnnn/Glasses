"""Observation transport adapter for Object Memory.

Named after its cartridge, for the same reason `world_builder.py` and
`world_builder_geometry.py` are: an adapter named after one cartridge
cannot leak that cartridge's assumptions into the next, because the next
one gets its own file. `tower/routes/observations.py` imports only this
module and never reaches `tower.object_memory` directly.

THIS FILE READS. IT DOES NOT DELETE.

`ObservationStore` also has `purge()` and `prune_expired()`. Neither is
reachable from here, and neither may become reachable. An unauthenticated
HTTP endpoint that erases a wearer's memory is not a feature, and
06-PRIVACY-DATA.md's real deletion stays where a human types it: the
`--purge-all` flag on `scripts/object_query.py`.

WHAT THIS PAYLOAD IS ALLOWED TO CLAIM

Every observation carries `spatial_ref: None`. The field is reserved,
never populated, and actively nulled on read -- nothing in this cartridge
knows where anything is in a room. So the payload answers "where" as a
FRAME REFERENCE: a capture id, a frame sequence number, a camera, and a
box in normalised frame coordinates. That is a pointer back into a
recording, not a place.

The names below are the enforcement. A doc that says "do not read this as
a location" is advice; a field called `where.kind == "frame-reference"`
with `spatial_ref` sitting next to it as an explicit null is a shape that
makes an overclaiming client awkward to write. Three claims are therefore
carried IN the payload rather than only in `docs/contracts/OBJECT-MEMORY.md`:

  claim          a category was VISIBLE ONCE -- not that it is there now
  identity       a CATEGORY, not an instance. Not "your" laptop.
  absence_means  no record is a statement about what this cartridge
                 captured, never about what is in the world

`spatial_ref` is carried as an explicit `null` rather than omitted, so a
consumer can see that the field exists and is empty. An absent key looks
like a version skew; a null is an answer.
"""

import time

from tower.object_memory.relevance import recordable_classes
from tower.object_memory.store import ObservationStore


def recorded_classes_for(verifier: str) -> tuple[str, ...]:
    """Which classes a Tower with this verifier will actually write.

    Lives in the ADAPTER, not in `main.py`, and that placement is the
    point. `main.py` is the wiring point and must not import a cartridge:
    it knows the world builder as an argv and it knows object memory the
    same way. This file is the one door -- it is already the only module
    outside `tower/object_memory/` that imports the cartridge's policy --
    so the answer travels through it as a tuple of strings.
    """
    return recordable_classes(verifier != "none")

# Opaque and dated, in the style of `world_builder.geometry/2026-08-25`.
# Compared for equality only: never parsed, never ordered, never used to
# infer that one contract is newer than another.
OBSERVATIONS_CONTRACT = "object_memory.observations/2026-08-26"

# The three sentences above, as values a decoder can switch on.
CATEGORY_CLAIM = "category-was-visible-once"
IDENTITY_SCOPE = "category-not-instance"
ABSENCE_MEANING = "not-observed-by-this-cartridge"

# `min(persisted, requested)` in one line, carried on every response so
# the rule travels with the data rather than living only in a document.
RETENTION_POLICY = (
    "min(persisted, requested): a reader may narrow this window and can "
    "never widen it"
)

SECONDS_PER_DAY = 86400.0


def retention_seconds_for(days: float | None) -> float | None:
    """A requested window in days, as the store's `retention_seconds`.

    None and "0 or less" both mean "no limit OF MY OWN", matching
    `scripts/object_query.py`. Neither means "keep forever": the store
    clamps to the window it was written under, so asking for nothing in
    particular gets the producer's promise, not the absence of one.
    """
    if days is None or days <= 0:
        return None
    return days * SECONDS_PER_DAY


def store_from_root(
    root, *, retention_days: float | None = None, clock=time.time
) -> ObservationStore:
    """Construct an `ObservationStore` for a configured root.

    Lives here, not in `tower/routes/observations.py`, so the route
    imports only this adapter -- the same rule that keeps
    `world_builder_geometry.store_from_root` where it is.
    """
    return ObservationStore(
        root, retention_seconds=retention_seconds_for(retention_days), clock=clock
    )


def _retention_view(store: ObservationStore, requested_days: float | None) -> dict:
    """What was asked for, what will be honoured, and whether they differ.

    `clamped` is True only when a caller asked for MORE than it received.
    A caller that asked for nothing has not been refused anything, and a
    caller that asked for less got exactly what it wanted.
    """
    effective = store.effective_retention_seconds()
    requested = retention_seconds_for(requested_days)
    if requested_days is None:
        clamped = False
    else:
        clamped = effective is not None and (
            requested is None or requested > effective
        )
    return {
        "requested_days": requested_days,
        # None is unbounded, and only ever reachable when the store itself
        # was written unbounded. Never 0: 0 days would mean "nothing is
        # visible", which is the opposite claim.
        "effective_days": None if effective is None else effective / SECONDS_PER_DAY,
        # A real bool. `bool` subclasses `int` in Python, and a `1` here
        # fails every Swift `as? Bool` decode.
        "clamped": bool(clamped),
        "policy": RETENTION_POLICY,
    }


def _where(observation) -> dict:
    """The only positional answer this cartridge can honestly give.

    The bounding box is nested HERE rather than beside the record on
    purpose. At the top level a box reads as a position; under
    `kind: "frame-reference"` it reads as what it is -- where in a
    picture, not where in a room.
    """
    box = observation.bounding_box
    return {
        "kind": "frame-reference",
        # Reserved, never populated. Present and null so a consumer sees
        # the field exists and is empty.
        "spatial_ref": None,
        "session_id": observation.session_id,
        "frame_seq": observation.frame_seq,
        # `source` is the camera the frame came from. Renamed on the wire
        # because "source" invites being read as a provenance system.
        "camera": observation.source,
        "bounding_box_normalized": list(box) if box is not None else None,
        # This pointer resolves into `data/captures/`, whose lifetime this
        # cartridge neither sets nor enforces. Purging every observation
        # here leaves the imagery exactly where it is.
        "imagery_retention": "capture-side",
    }


def _observation_view(observation) -> dict:
    return {
        "object_class": observation.object_class,
        "claim": CATEGORY_CLAIM,
        "identity": IDENTITY_SCOPE,
        # Three fields about strength, in the order a reader should trust
        # them. `confidence` is the interpretation and follows the best
        # look; the two raw numbers stay visible so the record is
        # auditable back to the sighting that created it.
        "confidence": observation.confidence.value,
        "detector_score": observation.detector_score,
        # None means "not tracked" -- records written before this field
        # existed. Never 0.0, which would be a claim of no evidence.
        "best_score": observation.best_score,
        "observed_at": observation.observed_at,
        # Qualified rather than implied: this slice can only know
        # tower-receipt time, never on-glasses capture time.
        "time_basis": observation.time_basis,
        "recorded_at": observation.recorded_at,
        "module_id": observation.module_id,
        "retention_tag": observation.retention_tag,
        "privacy_tags": list(observation.privacy_tags),
        "where": _where(observation),
    }


def _recorded_classes(recorded_classes) -> list[str]:
    """What this Tower will actually write, as the wire says it.

    Passed IN rather than imported from the cartridge's default, because
    the answer depends on configuration the adapter cannot see: a Tower
    with a semantic verifier records a wider set than one without, and
    naming a class here that nothing will ever write would turn "never
    looked for" -- the weaker silence, which a client words differently
    on purpose -- into "looked for and not seen".

    `None` falls back to the no-verifier set, which is the smaller and
    therefore the safer claim.
    """
    if recorded_classes is None:
        return list(recordable_classes(False))
    return list(recorded_classes)


def _envelope(
    store: ObservationStore, requested_days: float | None, recorded_classes=None
) -> dict:
    return {
        "contract": OBSERVATIONS_CONTRACT,
        "claim": CATEGORY_CLAIM,
        "identity": IDENTITY_SCOPE,
        "absence_means": ABSENCE_MEANING,
        # At the envelope too, not only per record: a client that reads
        # the header and stops must still learn there is no place here.
        "spatial_ref": None,
        # The universe of what could ever appear below. A class outside
        # this list has never been looked for, which is a different and
        # weaker kind of silence than "looked for and not seen".
        "recorded_classes": _recorded_classes(recorded_classes),
        "retention": _retention_view(store, requested_days),
    }


def build_observations(
    store: ObservationStore,
    *,
    object_class: str | None = None,
    requested_retention_days: float | None = None,
    recorded_classes=None,
) -> dict:
    """Every observation the store will still serve, newest first.

    `all_observations` filters to the clamped window by default, and the
    `include_expired` opt-out is never passed from here. It exists for
    maintenance paths -- purge counting what it deletes, an operator
    auditing the file -- and is never the right answer for anything a
    wearer will be shown, which is everything on this wire.
    """
    observations = store.all_observations()
    if object_class is not None:
        observations = [o for o in observations if o.object_class == object_class]
    # Newest first: the question this cartridge exists to answer is "when
    # did I last see", so the most recent sighting should not be at the
    # bottom of a scroll.
    observations.sort(key=lambda o: o.observed_at, reverse=True)

    payload = _envelope(store, requested_retention_days, recorded_classes)
    payload["object_class"] = object_class
    payload["observation_count"] = len(observations)
    payload["observations"] = [_observation_view(o) for o in observations]
    return payload


def build_last_seen(
    store: ObservationStore,
    object_class: str,
    *,
    requested_retention_days: float | None = None,
    recorded_classes=None,
) -> dict:
    """When a category was last in view, or an honest silence.

    There is no 404 case here and that is a product decision, not an
    oversight. "No record of a laptop" answered as Not Found reads as
    "there is no laptop", which is a claim about the world this cartridge
    cannot make. The resource -- what Object Memory knows about a class --
    exists either way; sometimes it knows nothing, and it says so with
    `observed: false` alongside `absence_means`.

    `observed`, never `present`. The record says a category was visible
    once, not that it is still there.
    """
    observation = store.last_seen(object_class)

    payload = _envelope(store, requested_retention_days, recorded_classes)
    payload["object_class"] = object_class
    # A class this Tower never writes carries no information in its
    # absence at all. Widening that list is a decision about what the
    # system is allowed to remember AND about what it is able to read
    # correctly; reporting it is how a client tells the two silences
    # apart.
    payload["recordable"] = bool(object_class in payload["recorded_classes"])
    payload["observed"] = bool(observation is not None)
    payload["observation"] = (
        _observation_view(observation) if observation is not None else None
    )
    # Hoisted to the top level as well, because "where did I leave it" is
    # the question a client will actually bind to this response.
    payload["where"] = _where(observation) if observation is not None else None
    return payload
