"""Line segments and Manhattan vanishing directions from a calibrated frame.

Research code. Nothing here is wired into the Tower; it exists to measure
whether the cue is present in real Ray-Ban imagery at all, before anything
is designed around it.

The representation is deliberately the calibrated one. A line segment with
endpoints p1, p2 in pixels has homogeneous line l = p1_h x p2_h, and the
plane through the camera centre containing that line has normal
n = K^T l in camera coordinates. A 3-D direction d is a vanishing
direction for that line iff n . d = 0. So everything below is angles
between unit vectors, never pixel distances -- a pixel threshold on a
vanishing point is meaningless when the point is at infinity.
"""
import numpy as np
import cv2


def detect_segments(gray, min_length_px=20.0):
    """LSD segments, short ones dropped.

    Short segments are dropped rather than down-weighted: a 6 px segment's
    direction is dominated by quantisation, and it is exactly those that
    outvote real structure in a RANSAC that counts segments.
    """
    lsd = cv2.createLineSegmentDetector()
    out = lsd.detect(gray)
    lines = out[0] if isinstance(out, tuple) else out
    if lines is None or len(lines) == 0:
        return np.empty((0, 4), np.float64)
    seg = np.asarray(lines, np.float64).reshape(-1, 4)
    length = np.hypot(seg[:, 2] - seg[:, 0], seg[:, 3] - seg[:, 1])
    return seg[length >= min_length_px]


def segment_normals(seg, K):
    """Interpretation-plane normals, unit length, one per segment."""
    if len(seg) == 0:
        return np.empty((0, 3))
    p1 = np.hstack([seg[:, 0:2], np.ones((len(seg), 1))])
    p2 = np.hstack([seg[:, 2:4], np.ones((len(seg), 1))])
    l = np.cross(p1, p2)
    n = l @ K            # (K^T l)^T  ==  l @ K
    norm = np.linalg.norm(n, axis=1, keepdims=True)
    norm[norm < 1e-12] = 1.0
    return n / norm


def _orthonormalise(d1, d2):
    d1 = d1 / np.linalg.norm(d1)
    d2 = d2 - (d2 @ d1) * d1
    nrm = np.linalg.norm(d2)
    if nrm < 1e-6:
        return None
    d2 = d2 / nrm
    return np.stack([d1, d2, np.cross(d1, d2)])


def manhattan_frame(normals, lengths, tol_deg=1.5, iters=500, rng=None,
                    min_inlier_length=0.0):
    """Best mutually-orthogonal direction triplet, by RANSAC over line pairs.

    Scored by total INLIER LENGTH, not inlier count. A wall's edge and a
    window frame's mullion are one vote each by count, and the wall edge
    is worth far more evidence; scoring by count lets clusters of short
    clutter segments beat the structure that actually defines the room.

    Returns (R_cw, per-axis inlier length, assignment) or None. R_cw's rows
    are the three directions expressed in camera coordinates, so it maps a
    Manhattan-frame vector into the camera frame by R_cw.T @ v.
    """
    if len(normals) < 6:
        return None
    rng = rng or np.random.default_rng(0)
    cos_tol = np.sin(np.radians(tol_deg))   # |n.d| below this = inlier
    best = None
    best_score = -1.0
    n = len(normals)
    for _ in range(iters):
        i, j, k, m = rng.integers(0, n, 4)
        if i == j or k == m:
            continue
        d1 = np.cross(normals[i], normals[j])
        if np.linalg.norm(d1) < 1e-6:
            continue
        d2 = np.cross(normals[k], normals[m])
        if np.linalg.norm(d2) < 1e-6:
            continue
        R = _orthonormalise(d1, d2 / np.linalg.norm(d2))
        if R is None:
            continue
        cos = np.abs(normals @ R.T)          # (n, 3)
        inlier = cos < cos_tol
        # A segment may only support ONE axis -- its best. Otherwise a
        # near-degenerate triplet double-counts.
        axis = np.argmin(cos, axis=1)
        owned = inlier[np.arange(n), axis]
        score = float(lengths[owned].sum())
        if score > best_score:
            best_score = score
            best = (R, axis, owned)
    if best is None:
        return None
    R, axis, owned = best
    per_axis = np.array([lengths[owned & (axis == a)].sum() for a in range(3)])
    if per_axis.min() < min_inlier_length:
        return None
    return R, per_axis, (axis, owned)


def refine_manhattan(normals, lengths, R, tol_deg=1.5, rounds=3):
    """Re-fit each axis to its inliers, re-orthogonalising each round.

    Each axis is the direction most orthogonal to its supporting normals:
    the smallest eigenvector of sum(w_i n_i n_i^T), length-weighted for the
    same reason the RANSAC score is.

    The sign alignment is load-bearing and was a bug before it was there.
    `eigh` returns eigenvectors with an arbitrary sign; polar-decomposing a
    set of axes whose signs have flipped independently returns a rotation
    unrelated to the one being refined, and the refined score collapsed --
    measured 0.767 -> 0.210 inlier share, and to 0.000 on one frame. Each
    refitted axis is therefore signed to agree with the axis it replaces
    BEFORE the three are orthogonalised. A refinement that can move the
    estimate further from the data is not a refinement, and it only
    presented as "lines are a weak cue".
    """
    cos_tol = np.sin(np.radians(tol_deg))
    for _ in range(rounds):
        cos = np.abs(normals @ R.T)
        axis = np.argmin(cos, axis=1)
        owned = cos[np.arange(len(normals)), axis] < cos_tol
        new_axes = []
        for a in range(3):
            sel = owned & (axis == a)
            if sel.sum() < 2:
                new_axes.append(R[a])
                continue
            N = normals[sel]
            w = lengths[sel][:, None]
            M = (N * w).T @ N
            _, vecs = np.linalg.eigh(M)
            d = vecs[:, 0]
            if d @ R[a] < 0:      # see docstring
                d = -d
            new_axes.append(d)
        A = np.stack(new_axes)
        U, _, Vt = np.linalg.svd(A)
        Rn = U @ Vt
        if np.linalg.det(Rn) < 0:
            U[:, -1] *= -1
            Rn = U @ Vt
        # A refinement round that loses inlier length is rejected. The
        # orthogonality projection can overshoot when one axis is weakly
        # supported, and there is no reason to accept a worse estimate.
        if _score(normals, lengths, Rn, cos_tol) < _score(normals, lengths, R, cos_tol):
            return R
        R = Rn
    return R


def _score(normals, lengths, R, cos_tol):
    cos = np.abs(normals @ R.T)
    axis = np.argmin(cos, axis=1)
    owned = cos[np.arange(len(normals)), axis] < cos_tol
    return float(lengths[owned].sum())


def canonicalise(R):
    """Fix the sign/permutation gauge so two frames' triplets are comparable.

    A Manhattan triplet is only defined up to axis permutation and sign --
    24 equivalent rotations. Comparing two frames without fixing this
    yields spurious 90-degree "rotations". Axes are ordered by how close
    they are to the camera's own x, y, z, and each is signed to have a
    positive dot with the axis it was matched to.
    """
    R = R.copy()
    used, order = set(), []
    for cam_axis in range(3):
        best, best_c = None, -1
        for a in range(3):
            if a in used:
                continue
            c = abs(R[a, cam_axis])
            if c > best_c:
                best_c, best = c, a
        used.add(best)
        order.append(best)
    R = R[order]
    for a in range(3):
        if R[a, a] < 0:
            R[a] *= -1
    if np.linalg.det(R) < 0:
        R[2] *= -1
    return R


def relative_rotation_deg(Ra, Rb):
    """Angle of the rotation taking frame a's camera to frame b's.

    Both R are camera<-Manhattan. If the room is the same, the relative
    camera rotation is Rb.T @ Ra applied appropriately; the ANGLE is what
    is compared, so the gauge only has to be consistent, not absolute.
    """
    dR = Rb.T @ Ra
    c = (np.trace(dR) - 1.0) / 2.0
    return float(np.degrees(np.arccos(np.clip(c, -1.0, 1.0))))
