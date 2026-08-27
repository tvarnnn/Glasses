"""The capability declaration: which cartridges the Tower can serve.

`IOS-to-Tower.md` section 7 makes this the single most valuable thing the
Tower can build first:

    "Without it, every cartridge is stuck at 'the Tower says nothing',
     and no other work on this list can be shown at all. It is also the
     smallest."

Section 0.1 names the three states iOS must be able to keep apart,
because they call for opposite user responses:

    the Tower says nothing about this cartridge   -> "not built yet"
    the Tower offers a contract this build
        does not implement                        -> "update the app"
    the Tower offers a contract this build
        implements, but is unreachable            -> "connect"

That third state is why `available` is separate from `contract`. A
World Builder with no world root configured still OFFERS the contract --
this build knows how to speak it -- it just has nothing to serve. Folding
that into "no contract" would tell a person to update an app that is
already correct.

This is NOT dynamic module discovery. `04-MODULE-SYSTEM.md` forbids that
before V1.0, and iOS says so itself: it "caches a declaration rather than
fetching a registry". The set below is a static, hand-maintained
declaration compiled into this build. Nothing here enumerates loaded
modules, and nothing here can grow at runtime.
"""

import logging
from dataclasses import dataclass

from tower.results.contracts import (
    CARTRIDGE_DOCUMENT_MEMORY,
    CARTRIDGE_EXPERIMENTAL_CV,
    CARTRIDGE_SCENE_UNDERSTANDING,
    CARTRIDGE_WORLD_BUILDER,
    ENVELOPE_CONTRACT,
    EXPERIMENTAL_CV_STATUS_CONTRACT,
    RESULT_TYPE_STATUS,
    WORLD_BUILDER_STATUS_CONTRACT,
)

# Cartridges that exist in this repository but offer NO wire contract,
# with the reason. Deliberately reported in a separate list from the
# offers, and deliberately reported at all.
#
# A client must not treat presence here as an offer of anything -- these
# are iOS's "the Tower says nothing about this cartridge" case, and the
# names are here so an operator can see the difference between "Tower
# does not know what document_memory is" and "Tower knows and is not
# serving it yet". iOS keys on `cartridges`; this list is for humans.
NOT_OFFERED = (
    {
        "cartridge": CARTRIDGE_DOCUMENT_MEMORY,
        "reason": (
            "implemented on Tower and queryable by CLI, but no typed "
            "contract is offered yet; see IOS-to-Tower.md 3"
        ),
    },
    {
        "cartridge": CARTRIDGE_SCENE_UNDERSTANDING,
        "reason": (
            "implemented on Tower as a live in-process state with no "
            "persistence; nothing in the web process observes it, so "
            "there is no state for this channel to read. See "
            "IOS-to-Tower.md 4"
        ),
    },
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CartridgeOffer:
    """One (cartridge, result_type) pair this build can serve."""

    cartridge: str
    result_type: str
    contract: str
    available: bool
    unavailable_reason: str | None = None
    # Whether results arrive as complete snapshots or as deltas that must
    # be merged. Stated rather than implied: IOS-to-Tower.md 1.3 warns
    # that "a UI that assumes incremental updates will draw a partial
    # world as a complete one".
    snapshot_only: bool = True

    def to_json_dict(self) -> dict:
        return {
            "cartridge": self.cartridge,
            "result_type": self.result_type,
            "contract": self.contract,
            "available": self.available,
            "unavailable_reason": self.unavailable_reason,
            "snapshot_only": self.snapshot_only,
        }


def declare(world_root: str | None, cv_lab=None) -> dict:
    """The full capability declaration.

    Takes its inputs rather than reading configuration itself, so the
    declaration is a pure function of them -- which is what lets one test
    assert that the HTTP route and the WebSocket message produce
    byte-identical output. `cv_lab` joined `world_root` for exactly that
    reason: both surfaces now have two things to pass, and passing the app
    instead would have made the function impure again.

    DUCK-TYPED, never imported. `cv_lab` is anything with an
    `availability()` returning `(available, reason)`. This module is part
    of the result channel cartridge-blind core and
    `test_the_result_channel_core_is_cartridge_blind` keeps it that way;
    an import of the Lab here would bake one cartridge into the shared
    surface, and this time the surface is a WIRE CONTRACT.
    """
    if world_root is None:
        available = False
        reason = (
            "no world root is configured on this Tower (TOWER_WORLD_ROOT "
            "is unset), so there is no persisted world state to read"
        )
    else:
        available = True
        reason = None

    cv_available, cv_reason = _cv_lab_availability(cv_lab)

    offers = (
        CartridgeOffer(
            cartridge=CARTRIDGE_WORLD_BUILDER,
            result_type=RESULT_TYPE_STATUS,
            contract=WORLD_BUILDER_STATUS_CONTRACT,
            available=available,
            unavailable_reason=reason,
        ),
        CartridgeOffer(
            cartridge=CARTRIDGE_EXPERIMENTAL_CV,
            result_type=RESULT_TYPE_STATUS,
            contract=EXPERIMENTAL_CV_STATUS_CONTRACT,
            available=cv_available,
            unavailable_reason=cv_reason,
        ),
    )

    return {
        "type": "cartridges",
        "envelope_contract": ENVELOPE_CONTRACT,
        "cartridges": [offer.to_json_dict() for offer in offers],
        "not_offered": [dict(entry) for entry in NOT_OFFERED],
    }


def _cv_lab_availability(cv_lab) -> tuple[bool, str | None]:
    """Whether this build can serve the CV Lab contract, and why not.

    A Tower with no Lab still OFFERS the contract -- this build knows how
    to speak it -- and reports it unavailable, which is the third state in
    IOS-to-Tower.md 0.1 ("offered, implemented, unreachable -> connect")
    rather than the first ("the Tower says nothing -> not built yet").
    Those call for opposite instructions to a person, which is why they
    cannot be one state.

    Never raises. A declaration is how a client learns what is possible;
    it must not fail because a subsystem is unwell.
    """
    if cv_lab is None:
        return False, (
            "this Tower is running without a CV Lab module, so no "
            "experiment can be enumerated or started"
        )
    try:
        available, reason = cv_lab.availability()
    except Exception:
        logger.exception("[Tower][Results] could not read CV Lab availability")
        return False, "the CV Lab could not report whether it is available"
    return bool(available), reason


def find_offer(
    world_root: str | None, cartridge: str, result_type: str, cv_lab=None
):
    """The offer matching a subscribe request, or None.

    None covers both "no such cartridge" and "no such result type on a
    cartridge that exists". The caller distinguishes them for the error
    message; this returns one thing so there is one lookup path.
    """
    for entry in declare(world_root, cv_lab)["cartridges"]:
        if entry["cartridge"] == cartridge and entry["result_type"] == result_type:
            return entry
    return None


def known_cartridges(world_root: str | None, cv_lab=None) -> set:
    return {
        entry["cartridge"] for entry in declare(world_root, cv_lab)["cartridges"]
    }
