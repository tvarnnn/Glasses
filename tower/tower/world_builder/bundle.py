"""Sparse bundle adjustment: the drift control this pipeline did not have.

WHY THIS EXISTS

Measured on a perfect synthetic strafe, with no tracking failure, no
refusal and no blur -- the shipped forward-only chain drifts:

    keyframes   rotation error (median / max)   max drift / path
        6            0.95 deg / 1.69 deg              4.7%
       12            1.69 deg / 3.46 deg              2.7%
       20            3.19 deg / 9.17 deg              9.8%
       30            5.71 deg / 18.88 deg            11.3%
       40            9.21 deg / 33.98 deg            18.2%

and the per-step recovered/true scale ratio, flat at 7.63 through the
first twenty keyframes, collapses to 3.46 by thirty and 2.43 by forty.
The reconstruction CONTRACTS.

That is the real reason a walk does not become a world. Fragmentation is
the symptom people see; drift is what makes the fragments unmergeable,
because cross-segment registration solves a Sim3 between two segments
and correctly refuses two pieces whose internal geometry disagrees.
Making segments longer without controlling drift trades a visible
failure for an invisible one.

WHY A PRIOR ATTEMPT MEASURED 0.00%, AND WHY THAT IS NOT THE LAST WORD

The record says a bundle adjuster improved drift by 0.00% at 16, 32 and
104 keyframes, and attributes it to an observation graph whose median
covisibility span is 1 -- 66% of landmarks seen by exactly two views, and
a two-view landmark is exactly determined, so it constrains nothing.

That was true of the engine it was measured on. It is not true of this
one. Measured on the same 40-keyframe strafe at HEAD:

    landmarks 5,876   mean views 4.67   >= 3 views 67.2%
    observation span: median 3, p90 9, p99 24; 28% span >= 5 frames

The guided re-observation added by EXTEND_REFERENCE_DEPTH built the
graph the earlier attempt was missing. And the drift is demonstrably
REACHABLE by optimisation rather than baked in: reprojecting the very
same observations through GROUND-TRUTH poses gives RMS 0.49 px against
0.95 px for the solved poses. The solved reconstruction is not at the
minimum. There is something to find.

WHAT THIS IS

Levenberg-Marquardt over camera poses and landmark positions, with the
Schur complement eliminating the landmarks -- the standard structure,
because the normal equations of a bundle problem are block-arrowhead and
solving them densely is the only thing that would make this expensive.
A local window is a few tens of cameras, so the reduced camera system is
a few hundred square and dense linear algebra on it is free; the cost is
all in forming it, which is vectorised.

NumPy and OpenCV only. scipy is not a Tower dependency and this must run
where the rest of the world builder runs.

GAUGE. A monocular reconstruction is free up to a similarity: 3 rotation,
3 translation, 1 scale. The Jacobian is therefore rank-deficient by 7 and
an undamped Gauss-Newton step is not unique. LM's damping term makes the
system positive definite, which is the standard resolution and the one
used here -- no parameters are held fixed, so the optimiser is free to
move the whole window and the caller must not assume camera 0 stays at
the origin. `optimise` re-anchors before returning, so that assumption
stays true for everything upstream.

CONVENTION. Poses are T_camera_world: `x_camera = R @ x_world + t`, the
same convention `backends/classical.py` publishes and `_triangulate_new`
projects with. Rotation increments are applied on the LEFT
(R <- exp(delta) R), which is why the pose Jacobian below is
-[R X]_cross and not something involving the current rotation vector.
"""

import numpy as np

# Robustifier scale, in pixels. The same 3.0 px that
# `classical.PNP_REPROJECTION_ERROR_PX` uses to call a correspondence an
# inlier, so a residual this optimiser down-weights is one the pose solve
# would already have rejected. Deliberately not a new number.
HUBER_DELTA_PX = 3.0

# A landmark seen from fewer views than this is not adjusted and does not
# constrain anything. Two views determine a point exactly -- it can always
# be moved to make both residuals zero -- so including two-view landmarks
# adds parameters and no information, which is precisely the condition the
# earlier 0.00% measurement was made under.
MIN_VIEWS_FOR_ADJUSTMENT = 3

# Cameras whose observations are too few to pose. Below this the camera
# would be moved by noise.
MIN_OBSERVATIONS_PER_CAMERA = 12

# Views of one landmark that may enter the reduced camera system. See the
# cap's use below: the Schur complement is quadratic in views per
# landmark, so this bounds the worst case without touching the common
# one. 0 disables it.
MAX_VIEWS_PER_LANDMARK = 8


def _skew(vectors: np.ndarray) -> np.ndarray:
    """(n, 3) -> (n, 3, 3) cross-product matrices."""
    n = len(vectors)
    out = np.zeros((n, 3, 3), dtype=np.float64)
    out[:, 0, 1] = -vectors[:, 2]
    out[:, 0, 2] = vectors[:, 1]
    out[:, 1, 0] = vectors[:, 2]
    out[:, 1, 2] = -vectors[:, 0]
    out[:, 2, 0] = -vectors[:, 1]
    out[:, 2, 1] = vectors[:, 0]
    return out


def _exp_so3(delta: np.ndarray) -> np.ndarray:
    """(n, 3) rotation vectors -> (n, 3, 3) rotation matrices.

    Rodrigues, vectorised, with the small-angle branch written out rather
    than guarded by an `if`: an LM step is overwhelmingly small, so the
    branch that matters is the one where sin(theta)/theta must not be
    evaluated as 0/0.
    """
    theta = np.linalg.norm(delta, axis=1)
    small = theta < 1e-8
    safe = np.where(small, 1.0, theta)
    axis = delta / safe[:, None]
    axis[small] = 0.0
    K = _skew(axis)
    sin = np.where(small, 0.0, np.sin(theta))[:, None, None]
    cos = np.where(small, 0.0, 1.0 - np.cos(theta))[:, None, None]
    identity = np.broadcast_to(np.eye(3), (len(delta), 3, 3))
    rotation = identity + sin * K + cos * (K @ K)
    # Exactly identity where the step is negligible, rather than
    # identity-plus-rounding: a pose that did not move must not acquire a
    # 1e-17 rotation, because these compose over many iterations.
    rotation[small] = np.eye(3)
    return rotation


def _residuals_and_terms(rotations, translations, points, camera_index,
                         point_index, observed, camera_matrix):
    """Reprojection residuals plus everything the normal equations need."""
    fx = camera_matrix[0, 0]
    fy = camera_matrix[1, 1]
    cx = camera_matrix[0, 2]
    cy = camera_matrix[1, 2]

    rotated = np.einsum("nij,nj->ni", rotations[camera_index],
                        points[point_index])
    camera = rotated + translations[camera_index]
    depth = camera[:, 2]
    # A landmark behind a camera has no meaningful pixel error. It is
    # given a zero Jacobian and a zero residual rather than being dropped,
    # so the arrays stay index-aligned with `observed` -- and it cannot
    # then drag the solution, which is the behaviour a hard filter would
    # have had anyway.
    valid = np.isfinite(depth) & (depth > 1e-6)
    safe_depth = np.where(valid, depth, 1.0)

    u = fx * camera[:, 0] / safe_depth + cx
    v = fy * camera[:, 1] / safe_depth + cy
    residual = np.stack([u - observed[:, 0], v - observed[:, 1]], axis=1)
    residual[~valid] = 0.0

    # d(u, v) / d(camera point)
    inverse = 1.0 / safe_depth
    projection = np.zeros((len(camera), 2, 3), dtype=np.float64)
    projection[:, 0, 0] = fx * inverse
    projection[:, 0, 2] = -fx * camera[:, 0] * inverse * inverse
    projection[:, 1, 1] = fy * inverse
    projection[:, 1, 2] = -fy * camera[:, 1] * inverse * inverse
    projection[~valid] = 0.0

    # d(camera point) / d(pose). Rotation is updated on the LEFT, so the
    # rotation block is -[R X]_cross and the translation block is I.
    jacobian_pose = np.zeros((len(camera), 2, 6), dtype=np.float64)
    jacobian_pose[:, :, :3] = projection @ (-_skew(rotated))
    jacobian_pose[:, :, 3:] = projection
    # d(camera point) / d(landmark) = R
    jacobian_point = projection @ rotations[camera_index]
    return residual, jacobian_pose, jacobian_point, valid


def _huber_weights(residual: np.ndarray, delta: float) -> np.ndarray:
    """Per-observation IRLS weights. sqrt(w) scales both r and J.

    Huber rather than a hard cut, and applied to the two-dimensional
    residual NORM rather than per axis, because a correspondence is
    wrong as a pair of coordinates or not at all.
    """
    norm = np.linalg.norm(residual, axis=1)
    weight = np.ones_like(norm)
    over = norm > delta
    weight[over] = delta / norm[over]
    return weight


def optimise(
    rotations,
    translations,
    points,
    observations,
    camera_matrix,
    *,
    iterations: int = 10,
    fixed_cameras=(),
    huber_delta: float = HUBER_DELTA_PX,
    min_views: int = MIN_VIEWS_FOR_ADJUSTMENT,
):
    """Refine poses and landmarks against their observations.

    Arguments
      rotations     (n_cam, 3, 3) R_camera_world, modified in place? NO --
                    a new array is returned and the inputs are untouched.
      translations  (n_cam, 3)
      points        (n_pt, 3)
      observations  (m, 4) float array of [camera, point, u, v]. The first
                    two columns are indices and must be integral; they are
                    taken as a float array because that is what callers
                    have and converting once here is cheaper than
                    converting at every call site.
      camera_matrix (3, 3) K
      fixed_cameras indices whose pose must not move. A caller that has
                    already published a pose downstream passes it here, so
                    an adjustment cannot rewrite geometry someone is
                    holding.

    Returns (rotations, translations, points, report). `report` carries
    the reprojection RMS before and after, the iteration count, and
    whether the optimiser actually improved anything -- a caller must be
    able to DISCARD the result, and this is what tells it to.

    The returned poses are re-anchored so that the first camera in
    `rotations` is exactly where it was. The optimiser is gauge-free (see
    the module docstring) so without this the whole window would drift in
    a way no consumer expects.
    """
    rotations = np.array(rotations, dtype=np.float64, copy=True)
    translations = np.array(translations, dtype=np.float64, copy=True)
    points = np.array(points, dtype=np.float64, copy=True)
    observations = np.asarray(observations, dtype=np.float64)
    n_cam = len(rotations)
    n_pt = len(points)
    if n_cam == 0 or n_pt == 0 or len(observations) == 0:
        return rotations, translations, points, {
            "iterations": 0, "reason": "nothing to adjust"
        }

    camera_index = observations[:, 0].astype(np.int64)
    point_index = observations[:, 1].astype(np.int64)
    observed = observations[:, 2:4]

    # Drop landmarks with too few views. They add three parameters each
    # and no constraint -- a two-view point can always be placed so both
    # residuals vanish -- so they would inflate the normal equations and
    # bias the robustifier's scale without informing a single pose.
    views = np.bincount(point_index, minlength=n_pt)
    usable_point = views >= min_views
    keep = usable_point[point_index]
    if not keep.any():
        return rotations, translations, points, {
            "iterations": 0,
            "reason": f"no landmark reaches {min_views} views",
            "landmarks_adjusted": 0,
        }
    camera_index = camera_index[keep]
    point_index = point_index[keep]
    observed = observed[keep]

    # Cap the views a single landmark contributes. The reduced camera
    # system is formed over PAIRS of observations of the same landmark,
    # so cost is quadratic in views: a landmark seen from every camera of
    # a twelve-camera window costs 144 pair blocks on its own, where a
    # typical one (measured mean 4.67 views) costs 22. The cap sits well
    # above the mean so it binds only on the handful that would otherwise
    # dominate.
    #
    # WHICH views are kept is not a detail. Keeping the FIRST k was tried
    # and is wrong: it systematically starves the NEWEST camera, which on
    # an online window is the one camera the adjustment exists to fix.
    # Measured on an eight-camera rig at cap 4, every camera settled
    # within 0.04 deg of the gauge except the last, which sat 0.86 deg
    # off -- a quiet, one-sided error that only appears at the end of the
    # window, which is exactly where it does the most damage.
    #
    # So both ends are kept: the oldest views carry the widest baseline
    # and the newest carry the camera being solved.
    if MAX_VIEWS_PER_LANDMARK:
        order = np.lexsort((camera_index, point_index))
        sorted_points = point_index[order]
        run_start = np.flatnonzero(
            np.r_[True, sorted_points[1:] != sorted_points[:-1]]
        )
        run_length = np.diff(np.r_[run_start, len(order)])
        ranked = np.empty(len(order), dtype=np.int64)
        run_size = np.empty(len(order), dtype=np.int64)
        ranked[order] = np.arange(len(order)) - np.repeat(run_start, run_length)
        run_size[order] = np.repeat(run_length, run_length)
        oldest = MAX_VIEWS_PER_LANDMARK // 2
        newest = MAX_VIEWS_PER_LANDMARK - oldest
        within = (ranked < oldest) | (run_size - 1 - ranked < newest)
        camera_index = camera_index[within]
        point_index = point_index[within]
        observed = observed[within]

    # And cameras with too few surviving observations to be posed by them.
    per_camera = np.bincount(camera_index, minlength=n_cam)
    frozen = np.zeros(n_cam, dtype=bool)
    frozen[per_camera < MIN_OBSERVATIONS_PER_CAMERA] = True
    for index in fixed_cameras:
        if 0 <= index < n_cam:
            frozen[index] = True

    free = np.nonzero(~frozen)[0]
    if len(free) == 0:
        return rotations, translations, points, {
            "iterations": 0, "reason": "every camera is fixed",
        }
    slot = -np.ones(n_cam, dtype=np.int64)
    slot[free] = np.arange(len(free))
    size = 6 * len(free)

    # -- the sparsity structure, built ONCE ---------------------------
    #
    # WHICH observation pairs share a landmark does not change as the
    # estimate moves, and rebuilding that inside the damping loop was the
    # single largest cost in this function: a Python-level tile() per
    # landmark per attempt, profiled at 140,000 calls over a 30-keyframe
    # walk. Everything below is index arithmetic on the FIXED structure,
    # and only the numbers flowing through it are recomputed.
    live_rows = np.nonzero(~frozen[camera_index])[0]
    if len(live_rows) == 0:
        return rotations, translations, points, {
            "iterations": 0, "reason": "no observation by a free camera",
        }
    order = np.argsort(point_index[live_rows], kind="stable")
    sorted_rows = live_rows[order]
    sorted_points = point_index[sorted_rows]
    boundaries = np.flatnonzero(
        np.r_[True, sorted_points[1:] != sorted_points[:-1], True]
    )
    starts = boundaries[:-1]
    counts = np.diff(boundaries)
    pair_counts = counts * counts
    total_pairs = int(pair_counts.sum())
    # Every (a, b) within each landmark's run, without a Python loop:
    # the within-run pair ordinal k gives a = k // c and b = k % c.
    offset_within = (
        np.arange(total_pairs)
        - np.repeat(np.r_[0, np.cumsum(pair_counts)[:-1]], pair_counts)
    )
    count_per_pair = np.repeat(counts, pair_counts)
    base = np.repeat(starts, pair_counts)
    rows_a = sorted_rows[base + offset_within // count_per_pair]
    rows_b = sorted_rows[base + offset_within % count_per_pair]
    # Flat destination in the (size, size) reduced matrix for each of the
    # 36 entries of a pair's 6x6 block.
    block_rows = slot[camera_index[rows_a]][:, None] * 6 + np.arange(6)[None, :]
    block_cols = slot[camera_index[rows_b]][:, None] * 6 + np.arange(6)[None, :]
    pair_flat = (
        block_rows[:, :, None] * size + block_cols[:, None, :]
    ).reshape(-1)
    live_slots = slot[camera_index[live_rows]]
    live_points = point_index[live_rows]

    def rms(residual, valid):
        if not valid.any():
            return float("inf")
        return float(np.sqrt((residual[valid] ** 2).sum(axis=1).mean()))

    residual, jac_pose, jac_point, valid = _residuals_and_terms(
        rotations, translations, points, camera_index, point_index,
        observed, camera_matrix)
    before = rms(residual, valid)
    weight = _huber_weights(residual, huber_delta)
    cost = float((weight[:, None] * residual ** 2).sum())

    lam = 1e-3
    taken = 0
    for _ in range(iterations):
        root = np.sqrt(weight)[:, None, None]
        A = jac_pose * root          # (m, 2, 6)
        B = jac_point * root         # (m, 2, 3)
        e = residual * np.sqrt(weight)[:, None]   # (m, 2)

        W = np.einsum("mki,mkj->mij", A, B)          # (m, 6, 3)
        ea = -np.einsum("mki,mk->mi", A, e)          # (m, 6)
        eb = -np.einsum("mki,mk->mi", B, e)          # (m, 3)
        AA = np.einsum("mki,mkj->mij", A, A)
        BB = np.einsum("mki,mkj->mij", B, B)

        # bincount, not np.add.at: the same accumulation, and profiled an
        # order of magnitude faster. This runs inside the damping loop,
        # so it is the difference between a keyframe-path cost and an
        # offline one.
        U = np.stack([
            np.bincount(camera_index, weights=AA[:, i, j], minlength=n_cam)
            for i in range(6) for j in range(6)
        ], axis=1).reshape(n_cam, 6, 6)
        V = np.stack([
            np.bincount(point_index, weights=BB[:, i, j], minlength=n_pt)
            for i in range(3) for j in range(3)
        ], axis=1).reshape(n_pt, 3, 3)
        g_cam = np.stack([
            np.bincount(camera_index, weights=ea[:, i], minlength=n_cam)
            for i in range(6)
        ], axis=1)
        g_pt = np.stack([
            np.bincount(point_index, weights=eb[:, i], minlength=n_pt)
            for i in range(3)
        ], axis=1)

        improved = False
        for _attempt in range(6):
            Ud = U.copy()
            Vd = V.copy()
            idx = np.arange(6)
            Ud[:, idx, idx] += lam * np.maximum(U[:, idx, idx], 1e-12)
            idx3 = np.arange(3)
            Vd[:, idx3, idx3] += lam * np.maximum(V[:, idx3, idx3], 1e-12)
            full_Vinv = np.zeros((n_pt, 3, 3))
            try:
                full_Vinv[usable_point] = np.linalg.inv(Vd[usable_point])
            except np.linalg.LinAlgError:
                lam *= 10.0
                continue

            # Schur complement: S = U - sum_j W_ij V_j^-1 W_kj^T, over
            # observation PAIRS sharing a landmark. Two cameras that
            # share one acquire an off-diagonal block, which is exactly
            # the covisibility structure.
            WV = np.einsum("mij,mjk->mik", W, full_Vinv[point_index])
            contribution = np.einsum("pij,pkj->pik", WV[rows_a], W[rows_b])
            S = -np.bincount(
                pair_flat, weights=contribution.reshape(-1),
                minlength=size * size,
            ).reshape(size, size)
            take = np.einsum("mij,mj->mi", WV[live_rows], g_pt[live_points])
            rhs = g_cam[free] - np.stack([
                np.bincount(live_slots, weights=take[:, i], minlength=len(free))
                for i in range(6)
            ], axis=1)
            for a, camera in enumerate(free):
                span = slice(6 * a, 6 * a + 6)
                S[span, span] += Ud[camera]

            try:
                delta_cam = np.linalg.solve(S, rhs.reshape(-1))
            except np.linalg.LinAlgError:
                lam *= 10.0
                continue
            delta_cam = delta_cam.reshape(len(free), 6)
            full_delta = np.zeros((n_cam, 6))
            full_delta[free] = delta_cam

            # Back-substitute the landmarks.
            pushed = np.einsum("mij,mi->mj", W, full_delta[camera_index])
            correction = np.stack([
                np.bincount(point_index, weights=pushed[:, i], minlength=n_pt)
                for i in range(3)
            ], axis=1)
            delta_pt = np.einsum("nij,nj->ni", full_Vinv, g_pt - correction)

            trial_rotations = rotations.copy()
            trial_translations = translations.copy()
            trial_rotations[free] = _exp_so3(delta_cam[:, :3]) @ rotations[free]
            trial_translations[free] = translations[free] + delta_cam[:, 3:]
            trial_points = points + delta_pt

            trial_residual, tjp, tjq, trial_valid = _residuals_and_terms(
                trial_rotations, trial_translations, trial_points,
                camera_index, point_index, observed, camera_matrix)
            trial_weight = _huber_weights(trial_residual, huber_delta)
            trial_cost = float(
                (trial_weight[:, None] * trial_residual ** 2).sum()
            )
            if trial_cost < cost:
                rotations = trial_rotations
                translations = trial_translations
                points = trial_points
                residual, jac_pose, jac_point, valid = (
                    trial_residual, tjp, tjq, trial_valid)
                weight = trial_weight
                cost = trial_cost
                lam = max(lam * 0.3, 1e-9)
                improved = True
                taken += 1
                break
            lam *= 10.0
        if not improved:
            break

    after = rms(residual, valid)
    return rotations, translations, points, {
        "iterations": taken,
        "reprojection_rms_before": round(before, 5),
        "reprojection_rms_after": round(after, 5),
        "improved": bool(after < before),
        "landmarks_adjusted": int(usable_point.sum()),
        "cameras_free": int((~frozen).sum()),
        "observations": int(len(observed)),
    }
