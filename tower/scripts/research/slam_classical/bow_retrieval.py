"""Would a DBoW2-style keyframe database actually FIND our revisits?

The census answers "do covisible pairs exist" by brute force -- all 104,196
pairs, 144 s. A shipping system cannot do that: the cost is O(N^2) in
keyframes and a real session has thousands. That is the entire reason
ORB-SLAM2/3 carry a vocabulary tree and an inverted index instead of
matching everything against everything.

So there are two separable questions and the census only answered the first:

  1. Do geometrically-verifiable revisits EXIST in this corpus?   (census)
  2. Can a SCALABLE retrieval stage surface them as candidates?   (here)

If (2) fails, the Atlas/loop-closure recommendation still needs a different
retrieval front end, and DBoW2's specific design is not the answer.

This is an INDEPENDENT reimplementation of the published vocabulary-tree
idea (Nister & Stewenius 2006; Galvez-Lopez & Tardos 2012), not a port of
DBoW2 source -- hierarchical k-means over binary ORB descriptors with
majority-vote centroids, tf-idf weights, and DBoW2's L1 similarity score.
Written to measure the IDEA's fitness on our data, and incidentally to
price what reimplementing it costs (this file is the answer).

Ground truth for retrieval is the census's own geometrically VERIFIED
edges. That is self-consistency, not external ground truth: it measures
whether BoW retrieval agrees with brute-force geometric verification on
the same frames, nothing more.

Usage:  python scripts/research/slam_classical/bow_retrieval.py
"""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOWER_ROOT = HERE.parents[2]
sys.path.insert(0, str(TOWER_ROOT))

import cv2
import numpy as np

from tower.world_builder.frontend import decode_gray
from tower.world_builder.geometry import detect_and_describe

SESS = (TOWER_ROOT / 'data/world_builder/worlds/3dd986b1c2364d4b85de97152f2e39f4'
        / 'sessions/dd5d13a2381e430db9b27c7da2cf2928')

# DBoW2's ORB vocabulary ships k=10, L=6 -> 1e6 words, trained on a large
# external image corpus. That file is 42.5 MB compressed (MEASURED from the
# ORB_SLAM3 clone). Nothing that size is trainable or shippable here, so
# this uses k=10, L=4 -> 10,000 words trained on the corpus itself, and the
# report must say the vocabulary is IN-DOMAIN, which flatters retrieval.
K_BRANCH = 10
DEPTH = 4
SEED = 0

# A place-recognition database MUST refuse to index feature-starved
# keyframes. MEASURED here: under DBoW2's L1 score s = 1 - 0.5*|v-w|_1 on
# L1-normalised vectors, two ZERO vectors score 1.00 -- the maximum
# possible -- and a normal keyframe against a zero vector scores 0.50,
# while two genuinely similar keyframes typically score well below that.
# So a featureless keyframe outranks every real match and becomes a
# universal attractor. The first run of this file reported Recall@1 = 0.0%
# for exactly this reason, and the cause is the database, not the corpus.
#
# ORB-SLAM3 never has this problem because it will not even attempt
# initialisation on a frame with <=100 keypoints (Tracking.cc:2454, :2483).
# Same constant used here.
#
# NOTE this is a real gap in OUR pipeline: the shipped keyframe selector
# gates on blur and motion, not on feature count, and MEASURED on the
# canonical session 24 of 457 accepted keyframes have <=100 ORB features
# and one has ZERO.
MIN_FEATURES = 100


def hamming_assign(X, C):
    """Nearest centroid by Hamming distance, X and C unpacked to bits."""
    # (n, 256) uint8 bits vs (k, 256) -> use matrix algebra on +-1.
    a = X.astype(np.int16) * 2 - 1
    b = C.astype(np.int16) * 2 - 1
    # dot = 256 - 2*hamming  ->  maximise dot
    return np.argmax(a @ b.T, axis=1)


def kmeans_binary(X, k, rng, iters=8):
    """k-means on binary vectors with MAJORITY-VOTE centroids (DBoW2's
    kmeans++-seeded Hamming clustering, reimplemented from the paper)."""
    n = len(X)
    if n <= k:
        return X.copy()
    idx = rng.choice(n, k, replace=False)
    C = X[idx].copy()
    for _ in range(iters):
        lab = hamming_assign(X, C)
        newC = C.copy()
        for c in range(k):
            m = lab == c
            if m.any():
                newC[c] = (X[m].mean(axis=0) >= 0.5).astype(np.uint8)
        if np.array_equal(newC, C):
            break
        C = newC
    return C


class Vocab:
    """Hierarchical k-means tree; leaves are visual words."""

    def __init__(self):
        self.nodes = []   # (centroids array, child_offset) per level path

    def train(self, X, rng):
        self.levels = []
        # Level 0: cluster everything.
        assign = np.zeros(len(X), np.int64)
        n_groups = 1
        for d in range(DEPTH):
            cents, next_assign = [], np.zeros(len(X), np.int64)
            for g in range(n_groups):
                m = assign == g
                sub = X[m]
                if len(sub) == 0:
                    cents.append(np.zeros((K_BRANCH, X.shape[1]), np.uint8))
                    continue
                C = kmeans_binary(sub, K_BRANCH, rng)
                if len(C) < K_BRANCH:  # pad
                    C = np.vstack([C, np.tile(C[-1], (K_BRANCH - len(C), 1))])
                cents.append(C)
                lab = hamming_assign(sub, C)
                next_assign[m] = g * K_BRANCH + lab
            self.levels.append(np.stack(cents))     # (n_groups, K, bits)
            assign = next_assign
            n_groups *= K_BRANCH
        self.n_words = n_groups

    def words(self, D):
        """Descriptor block (n, 32) uint8 -> word ids."""
        X = np.unpackbits(D, axis=1)
        g = np.zeros(len(X), np.int64)
        for d in range(DEPTH):
            cents = self.levels[d]
            out = np.empty(len(X), np.int64)
            for gid in np.unique(g):
                m = g == gid
                out[m] = gid * K_BRANCH + hamming_assign(X[m], cents[gid])
            g = out
        return g


def main():
    rng = np.random.default_rng(SEED)
    kfs = [json.loads(x) for x in (SESS / 'keyframes.jsonl').read_text().splitlines()
           if x.strip()]
    n = len(kfs)
    seg = np.array([k['segment_index'] for k in kfs])

    descs = []
    for k in kfs:
        _kp, d = detect_and_describe(decode_gray((SESS / k['image_relpath']).read_bytes()))
        descs.append(d if d is not None else np.empty((0, 32), np.uint8))
    total = sum(len(d) for d in descs)
    print(f"keyframes={n}  descriptors={total}")

    pool = np.vstack([d for d in descs if len(d)])
    take = rng.choice(len(pool), min(120_000, len(pool)), replace=False)
    Xb = np.unpackbits(pool[take], axis=1)
    t0 = time.perf_counter()
    voc = Vocab()
    voc.train(Xb, rng)
    t_train = time.perf_counter() - t0
    print(f"vocabulary: k={K_BRANCH} L={DEPTH} -> {voc.n_words} words, "
          f"trained on {len(take)} descriptors in {t_train:.1f}s")

    # tf-idf, DBoW2 style: idf = log(N / n_i), tf = count/total, L1-normalised.
    t0 = time.perf_counter()
    wordsets = [voc.words(d) if len(d) else np.empty(0, np.int64) for d in descs]
    t_assign = time.perf_counter() - t0
    df = np.zeros(voc.n_words)
    for w in wordsets:
        df[np.unique(w)] += 1
    idf = np.log(n / np.maximum(df, 1))
    V = np.zeros((n, voc.n_words), np.float32)
    for a, w in enumerate(wordsets):
        if len(w) == 0:
            continue
        cnt = np.bincount(w, minlength=voc.n_words).astype(np.float32)
        v = cnt * idf
        s = v.sum()
        if s > 0:
            V[a] = v / s
    print(f"BoW vectors built in {t_assign:.1f}s "
          f"({t_assign / n * 1000:.1f} ms/keyframe to assign words)")

    indexed = np.array([len(d) >= MIN_FEATURES for d in descs])
    print(f"indexable keyframes (>= {MIN_FEATURES} ORB features): "
          f"{int(indexed.sum())}/{n}  -- {int((~indexed).sum())} refused entry "
          f"to the database")

    # DBoW2 L1 score: s(v,w) = 1 - 0.5 * |v - w|_1, in [0,1].
    t0 = time.perf_counter()
    S = np.zeros((n, n), np.float32)
    for a in range(n):
        S[a] = 1.0 - 0.5 * np.abs(V - V[a]).sum(axis=1)
    t_score = time.perf_counter() - t0
    np.fill_diagonal(S, -1)
    # Un-indexed keyframes are neither queries nor candidates.
    S[~indexed, :] = -1
    S[:, ~indexed] = -1
    print(f"all-pairs BoW scoring: {t_score:.2f}s "
          f"({t_score / (n * n) * 1e6:.2f} us/pair)")

    # Retrieval quality against the census's geometrically verified edges.
    cen = json.loads((HERE / 'covisibility_census.json').read_text())
    edges = set()
    for p in cen['pairs']:
        if p['f_inliers'] >= cen['meta']['covis_edge_th'] and not p.get('f_failed'):
            edges.add((p['i'], p['j']))
    print(f"\nverified edges from census: {len(edges)}")

    seqs = np.array([k['source_seq'] for k in kfs])
    neigh = [set() for _ in range(n)]
    for (a, b) in edges:
        neigh[a].add(b)
        neigh[b].add(a)

    def report(title, truth_of, exclude_recent=None):
        """Standard place-recognition Recall@K: for each QUERY that has at
        least one true match, does the top-K contain AT LEAST ONE?

        The first version of this file scored `|truth & topK| / |truth|`
        summed over queries, which is capped at K/degree and reported
        recall@1 = 0.0% as an artefact of the definition rather than a
        property of the data. Fixed, and both numbers kept in the report.
        """
        print(f"\n{title}")
        order_l = np.argsort(-S, axis=1)
        for topk in (1, 5, 10, 20, 50):
            hitq = totq = 0
            for a in range(n):
                if not indexed[a]:
                    continue
                truth = {b for b in truth_of(a) if indexed[b]}
                if not truth:
                    continue
                cand = []
                for b in order_l[a]:
                    b = int(b)
                    if exclude_recent is not None and abs(seqs[b] - seqs[a]) <= exclude_recent:
                        continue
                    cand.append(b)
                    if len(cand) >= topk:
                        break
                totq += 1
                if truth & set(cand):
                    hitq += 1
            print(f"  Recall@{topk:<3} (>=1 correct in top-K): "
                  f"{hitq / max(1, totq) * 100:5.1f}%   ({hitq}/{totq} queries)")

    report("RETRIEVAL vs ALL verified covisible neighbours",
           lambda a: neigh[a])

    # The loop-closure case: exclude the temporal neighbourhood, exactly as
    # ORB-SLAM3 excludes directly-connected keyframes before proposing a
    # loop candidate (LoopClosing.cc:628-641).
    GAP = 30 * 11.99
    far = [set() for _ in range(n)]
    for (a, b) in edges:
        if abs(seqs[b] - seqs[a]) > GAP:
            far[a].add(b)
            far[b].add(a)
    print(f"\nlong-gap (>30s) verified edges: "
          f"{sum(len(x) for x in far) // 2}")
    report("RETRIEVAL of LONG-GAP REVISITS "
           "(temporal neighbourhood excluded from candidates)",
           lambda a: far[a], exclude_recent=GAP)

    cross = [set() for _ in range(n)]
    for (a, b) in edges:
        if seg[a] != seg[b]:
            cross[a].add(b)
            cross[b].add(a)
    print(f"\ncross-segment verified edges: {sum(len(x) for x in cross) // 2}")
    report("RETRIEVAL of CROSS-SEGMENT edges (the Atlas merge case)",
           lambda a: cross[a])

    # Precision of the raw retrieval stage: how much junk does geometric
    # verification have to throw away? This is the false-loop-closure load.
    order = np.argsort(-S, axis=1)
    print()
    for topk in (5, 10, 20):
        good = bad = 0
        for a in range(n):
            if not indexed[a]:
                continue
            for b in order[a, :topk]:
                if not indexed[int(b)]:
                    continue
                if int(b) in neigh[a]:
                    good += 1
                else:
                    bad += 1
        print(f"  precision@{topk:<3}: {good / max(1, good + bad) * 100:5.1f}% "
              f"({good} verified / {good + bad} proposed) -- the rest is what "
              f"geometric verification must reject")


if __name__ == '__main__':
    main()
