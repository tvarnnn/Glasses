# Verified contract findings for the Tower lane (from the Mac/iOS lane, 2026-08-27)
All four verified against the RUNNING unified Tower (e2ca9b2) on a Mac, not read from docs.

## F1. §9.1 documents a `limit` parameter that does not exist
`docs/contracts/TOWER-UNIFIED-CARTRIDGES.md` §9.1 states:
    GET /object-memory/observations?object_class=&retention_days=&limit=
The route declares only `object_class` and `retention_days`. Verified via GET /openapi.json:
    /object-memory/observations -> ['object_class', 'retention_days']
    /documents                  -> ['limit', 'retention_days']
    /documents/search           -> ['text', 'limit', 'retention_days']
So `limit` is real on Document Memory and absent on Object Memory. `?limit=1` is SILENTLY
IGNORED rather than refused. Either implement it or strike it from §9.1 -- a client that
paginates on it gets the full clamped set and no error.

## F2. §4.1's refusal table disagrees with the wire
§4.1 says `resume` from `stopped` is refused 409 `not-active`.
The wire answers 409 `not-paused`. (`pause` from `stopped` does answer `not-active`.)
Both words are inside §10's vocabulary so neither is wrong per se, but the table is not
what shipped. iOS keys its copy on action + reached state rather than the reason word, so it
is correct against either -- but the table should match the build.

## F3. Every refusal body is wrapped in FastAPI's `detail`, and no contract says so
409 / 404 / 410 / 503 bodies all arrive as {"detail": {...}} rather than the flat object the
field tables imply. Undocumented in every section. A client decoding to the documented shape
finds nothing and renders a generic failure. Worth one sentence in §10.

## F4. `world_builder.geometry/2026-08-25` gained fields without moving
`placement_hash`, `registration_state` and `registration_refusal_reason` are now emitted
unconditionally (tower/results/world_builder_geometry.py:319, :411, _placement_fields) and the
identifier did not change. Additive, so decode does not break -- but the identifier is the ONLY
signal a client gets, and a client caching on `content_hash` alone is now WRONG with no way to
learn it. The Tower's own comment says as much: "every cached content_hash stays valid -- which
is safe only because placement_hash exists to change instead." That safety is a property of the
CLIENT, not the wire, and the wire currently cannot tell the client to acquire it.
iOS decodes placement_hash as OPTIONAL for this reason (old verbatim fixtures predate it).
Recommend the WB lane decide: bump the identifier, or state in the contract that placement_hash
is required-from-this-date.

## F5 (not a defect, a decision owed) Object Memory's socket declaration
Tower §8 says declaring it is ~4 lines but breaks a pinned iOS test, and that it is
"a decision for a human -- do not close it by noticing the gap."
THE iOS LANE DID NOT CLOSE IT. Object Memory is integrated entirely over HTTP and learns
nothing from the declaration, exactly as §9 instructs. The iOS test that pins it
(testTheTowerDeclaresOnlyTheWorldBuilderContract) HAS been widened for the four declared
cartridges, so the iOS half is no longer the blocker -- but the socket declaration itself
remains unmade, deliberately, pending a human ruling.
