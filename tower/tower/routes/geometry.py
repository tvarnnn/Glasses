"""World Builder geometry, over HTTP.

HTTP and not the WebSocket, for a reason that is in the code rather than
in taste: `tower/routes/ws.py` gives the result sender and the frame path
one shared `asyncio.Lock`. One session's `points.json` is 1.07 MB against
a 3,884-byte status snapshot, so pushing geometry down that socket would
hold the lock and starve `frame_result` -- the exact thing
`CARTRIDGE-RESULTS.md` forbids in Tower responsibility #3.

Both handlers are declared `def` rather than `async def` on purpose.
FastAPI runs a sync endpoint in its threadpool, which keeps the disk read
and the hash off the event loop with no executor of our own.
"""

from fastapi import APIRouter, HTTPException, Query, Request

# Imported as a submodule of the package, not as `from
# tower.results.world_builder_geometry import ...`: this route is not in
# `_RESULT_CHANNEL_ADAPTERS`, and must not be -- it reaches the adapter's
# functions, never a `world_builder` record. Going through the package
# keeps that reach visible as "the geometry adapter", not as a second path
# into the cartridge itself.
from tower.results import world_builder_geometry

router = APIRouter()


def _store(request: Request):
    root = getattr(request.app.state, "world_root", None)
    if root is None:
        raise HTTPException(status_code=404, detail="no world root is configured")
    return world_builder_geometry.store_from_root(root)


@router.get("/worlds/{world_id}/geometry/manifest")
def geometry_manifest(world_id: str, session_id: str, request: Request) -> dict:
    manifest = world_builder_geometry.build_manifest(_store(request), world_id, session_id)
    if manifest is None:
        # Absent and stale are deliberately the same answer: both mean
        # "there is nothing here you may render".
        raise HTTPException(status_code=404, detail="no current geometry")
    return manifest


@router.get("/worlds/{world_id}/geometry/segment/{segment_index}")
def geometry_segment(
    world_id: str, segment_index: int, session_id: str, request: Request,
    max_points: int | None = Query(default=None, ge=1),
) -> dict:
    chunk = world_builder_geometry.build_segment(
        _store(request), world_id, session_id, segment_index, max_points=max_points
    )
    if chunk is None:
        raise HTTPException(status_code=404, detail="no such segment")
    return chunk
