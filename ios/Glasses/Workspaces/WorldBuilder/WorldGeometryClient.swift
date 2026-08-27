//
//  WorldGeometryClient.swift
//  Glasses
//

import Foundation

/// Cached segment geometry, keyed by `(content_hash, placement_hash)`.
///
/// Keyed by hash rather than by segment index on purpose: a re-solved segment
/// keeps its index and changes its contents, so an index key would serve stale
/// geometry under a fresh revision. A hash key cannot.
///
/// ## Why the key is a pair, and what keying on content alone cost
///
/// Because the Tower freezes a segment when tracking is lost, a closed
/// segment's **geometry** never changes again — so its points and poses cross
/// the wire once and are kept for the life of the world, and only the open
/// segment churns.
///
/// **Its geometry. Not its identity, and not where it sits.** Registration is a
/// layer *above* frozen segments: geometry immutable, placements mutable. A
/// later pass places a segment an earlier one could not, and loop closure moves
/// placements rather than points — so `content_hash`, which covers poses and
/// points only, deliberately does **not** move when a segment gains a
/// placement. That is what keeps every cached chunk valid across a registration
/// pass, and it is safe only because `placement_hash` moves instead.
///
/// Keyed on `content_hash` alone this cache therefore never refetches a
/// re-placed segment. It keeps the chunk it has and the client draws an
/// **unplaced** version of a segment the world now knows how to place. Nothing
/// throws, nothing logs, no tile goes blank: the fragment simply sits in the
/// wrong place, permanently. `geometry_revision` rolls up both hashes so the
/// change signal does fire — the entire risk was in this dictionary.
///
/// The key is built by `WorldGeometryCacheKey` and nowhere else, so the two
/// halves cannot drift apart at a call site.
actor WorldGeometryStore {
    private var chunks: [String: WorldSegmentChunk] = [:]

    /// Filed under the chunk's **own** key, never under the key it was asked
    /// for. See the call site in `WorldBuilderViewModel`.
    func insert(_ chunk: WorldSegmentChunk) {
        chunks[chunk.cacheKey] = chunk
    }

    /// Takes a composite key, not a content hash — and is named so that a
    /// caller reaching for `summary.contentHash` out of habit does not
    /// typecheck into a silent cache hit on a stale placement.
    func chunk(forKey key: String) -> WorldSegmentChunk? {
        chunks[key]
    }

    func keysMissing(from wanted: [String]) -> [String] {
        wanted.filter { chunks[$0] == nil }
    }

    /// Drop everything not named by the current manifest. Called after a
    /// manifest arrives so a long walk does not accumulate superseded
    /// segments forever.
    ///
    /// Composite keys, so a segment whose placement moved has its old chunk
    /// dropped here as well as missed by the lookup above — one registration
    /// pass over 51 segments would otherwise leave 51 orphans behind.
    func retainOnly(_ wanted: Set<String>) {
        chunks = chunks.filter { wanted.contains($0.key) }
    }
}

nonisolated enum WorldGeometryFetchError: Error, Equatable {
    case notFound
    case undecodable
    case transport(String)
}

/// Fetches geometry over HTTP. Deliberately not on the WebSocket.
nonisolated struct WorldGeometryClient {
    var baseURL: URL = TowerConfiguration.httpBaseURL
    var session: URLSession = .shared

    func manifest(worldID: String, sessionID: String) async throws -> WorldGeometryManifest {
        let url = baseURL
            .appendingPathComponent("worlds/\(worldID)/geometry/manifest")
        let json = try await get(url, query: [URLQueryItem(name: "session_id", value: sessionID)])
        guard let manifest = WorldGeometryDecoder.manifest(from: json) else {
            throw WorldGeometryFetchError.undecodable
        }
        return manifest
    }

    func segment(
        worldID: String, sessionID: String, index: Int, maxPoints: Int? = nil
    ) async throws -> WorldSegmentChunk {
        let url = baseURL
            .appendingPathComponent("worlds/\(worldID)/geometry/segment/\(index)")
        var query = [URLQueryItem(name: "session_id", value: sessionID)]
        if let maxPoints {
            query.append(URLQueryItem(name: "max_points", value: String(maxPoints)))
        }
        let json = try await get(url, query: query)
        guard let chunk = WorldGeometryDecoder.chunk(from: json) else {
            throw WorldGeometryFetchError.undecodable
        }
        return chunk
    }

    private func get(_ url: URL, query: [URLQueryItem]) async throws -> [String: Any] {
        var components = URLComponents(url: url, resolvingAgainstBaseURL: false)!
        components.queryItems = query
        do {
            let (data, response) = try await session.data(from: components.url!)
            if let http = response as? HTTPURLResponse, http.statusCode == 404 {
                throw WorldGeometryFetchError.notFound
            }
            guard
                let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
            else { throw WorldGeometryFetchError.undecodable }
            return json
        } catch let error as WorldGeometryFetchError {
            throw error
        } catch {
            throw WorldGeometryFetchError.transport(error.localizedDescription)
        }
    }
}
