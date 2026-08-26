//
//  WorldGeometryClient.swift
//  Glasses
//

import Foundation

/// Cached segment geometry, keyed by content hash.
///
/// Keyed by hash rather than by segment index on purpose: a re-solved segment
/// keeps its index and changes its contents, so an index key would serve stale
/// geometry under a fresh revision. A hash key cannot.
///
/// Because the Tower freezes a segment when tracking is lost, a closed
/// segment's hash never changes again — so it is fetched exactly once and kept
/// for the life of the world, and only the open segment churns.
actor WorldGeometryStore {
    private var chunks: [String: WorldSegmentChunk] = [:]

    func insert(_ chunk: WorldSegmentChunk) {
        chunks[chunk.contentHash] = chunk
    }

    func chunk(forHash hash: String) -> WorldSegmentChunk? {
        chunks[hash]
    }

    func hashesMissing(from wanted: [String]) -> [String] {
        wanted.filter { chunks[$0] == nil }
    }

    /// Drop everything not named by the current manifest. Called after a
    /// manifest arrives so a long walk does not accumulate superseded
    /// segments forever.
    func retainOnly(_ wanted: Set<String>) {
        chunks = chunks.filter { wanted.contains($0.key) }
    }
}

enum WorldGeometryFetchError: Error, Equatable {
    case notFound
    case undecodable
    case transport(String)
}

/// Fetches geometry over HTTP. Deliberately not on the WebSocket.
struct WorldGeometryClient {
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
