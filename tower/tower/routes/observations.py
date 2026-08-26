"""Object Memory's observations, over HTTP. Read-only.

Named after the question rather than the cartridge, exactly as
`geometry.py` is: a route file called `object_memory.py` would put a
cartridge's name into `main.py`'s import list, which is the boundary
`test_shared_code_does_not_import_a_cartridge` exists to hold. The
cartridge is reached only through `tower/results/object_memory.py`, the
adapter named after it.

Both handlers are declared `def` rather than `async def` on purpose.
FastAPI runs a sync endpoint in its threadpool, which keeps the JSONL
read off the event loop with no executor of our own -- the same reason
`tower/routes/geometry.py` gives for the same choice. An `async def`
here would block the frame path behind a disk read.

NOTHING HERE MUTATES.

`ObservationStore` can purge and can prune. This module reaches neither,
and `test_no_wire_module_can_reach_purge_or_prune` fails if it ever
does. Deletion stays with `scripts/object_query.py --purge-all`, where a
human types it.

RETENTION IS NARROWABLE, NEVER WIDENABLE.

`retention_days` is a request, not an authority. It travels into the
store, which clamps every read to min(persisted, requested). A caller
asking for 3650 days against a store written under the 30-day default
still gets 30 days, and the response says so in `retention.clamped`
rather than pretending the question was honoured. The clamp is the
store's, not this route's -- this file consumes the property and adds
nothing of its own that could weaken it.
"""

from fastapi import APIRouter, HTTPException, Query, Request

from tower.results.object_memory import (
    build_last_seen,
    build_observations,
    store_from_root,
)

router = APIRouter()


def _store(request: Request, retention_days: float | None):
    root = getattr(request.app.state, "object_memory_root", None)
    if root is None:
        # Unset means this Tower serves no object memory at all, which is
        # a different claim from "nothing has been observed". A 404 here
        # is about configuration; it is never the answer to a query about
        # a class, which is answered with `observed: false` instead.
        raise HTTPException(
            status_code=404, detail="no object memory root is configured"
        )
    return store_from_root(root, retention_days=retention_days)


# `ge=0` rather than an unbounded float: a negative window is meaningless
# and the store raises ValueError on it, which would surface as a 500. 0
# is allowed and means "no limit of my own" -- which still gets clamped
# to the persisted window, so it is not a back door.
_RETENTION_DAYS = Query(
    default=None,
    ge=0,
    description=(
        "Narrow the window this read may see. Clamped to "
        "min(persisted, requested); it can only ever serve less."
    ),
)


@router.get("/object-memory/observations")
def observations(
    request: Request,
    object_class: str | None = Query(default=None),
    retention_days: float | None = _RETENTION_DAYS,
) -> dict:
    return build_observations(
        _store(request, retention_days),
        object_class=object_class,
        requested_retention_days=retention_days,
    )


@router.get("/object-memory/last-seen/{object_class}")
def last_seen(
    object_class: str,
    request: Request,
    retention_days: float | None = _RETENTION_DAYS,
) -> dict:
    return build_last_seen(
        _store(request, retention_days),
        object_class,
        requested_retention_days=retention_days,
    )
