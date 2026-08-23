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

from dataclasses import dataclass

from tower.results.contracts import (
    CARTRIDGE_DOCUMENT_MEMORY,
    CARTRIDGE_EXPERIMENTAL_CV,
    CARTRIDGE_SCENE_UNDERSTANDING,
    CARTRIDGE_WORLD_BUILDER,
    ENVELOPE_CONTRACT,
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
        "cartridge": CARTRIDGE_EXPERIMENTAL_CV,
        "reason": (
            "results already reach the client on frame_result; a typed "
            "contract awaits the experiment-registry and provenance work "
            "described in IOS-to-Tower.md 2.1-2.3"
        ),
    },
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


def declare(world_root: str | None) -> dict:
    """The full capability declaration.

    Takes the world root rather than reading configuration itself so the
    declaration is a pure function of its inputs -- which is what lets one
    test assert that the HTTP route and the WebSocket message produce
    byte-identical output.
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

    offers = (
        CartridgeOffer(
            cartridge=CARTRIDGE_WORLD_BUILDER,
            result_type=RESULT_TYPE_STATUS,
            contract=WORLD_BUILDER_STATUS_CONTRACT,
            available=available,
            unavailable_reason=reason,
        ),
    )

    return {
        "type": "cartridges",
        "envelope_contract": ENVELOPE_CONTRACT,
        "cartridges": [offer.to_json_dict() for offer in offers],
        "not_offered": [dict(entry) for entry in NOT_OFFERED],
    }


def find_offer(world_root: str | None, cartridge: str, result_type: str):
    """The offer matching a subscribe request, or None.

    None covers both "no such cartridge" and "no such result type on a
    cartridge that exists". The caller distinguishes them for the error
    message; this returns one thing so there is one lookup path.
    """
    for entry in declare(world_root)["cartridges"]:
        if entry["cartridge"] == cartridge and entry["result_type"] == result_type:
            return entry
    return None


def known_cartridges(world_root: str | None) -> set:
    return {entry["cartridge"] for entry in declare(world_root)["cartridges"]}
