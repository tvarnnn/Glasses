"""A pure-torch stand-in for the three `torch_scatter` ops DPVO actually uses.

`torch-scatter` does not build against torch 2.13 here (it is a separate CUDA
extension with its own version bounds). DPVO only needs `scatter_sum`,
`scatter_softmax` and -- in the optional long-term loop closure --
`scatter_max`. All three are expressible exactly in stock torch:

    scatter_sum      index_add_ (exact; same float accumulation order caveat
                                 as torch_scatter's own atomic add)
    scatter_max      scatter_reduce_ with reduce="amax"
    scatter_softmax  max-subtracted exp, normalised by a scatter_sum
                     (the standard numerically-stable formulation, which is
                      what torch_scatter itself does)

Install by copying this file to `torch_scatter.py` somewhere early on
sys.path. Self-test: `python torch_scatter_shim.py`.
"""

from __future__ import annotations

import torch

__version__ = "0.0.0-shim"


def _broadcast(index: torch.Tensor, src: torch.Tensor, dim: int) -> torch.Tensor:
    if dim < 0:
        dim = src.dim() + dim
    if index.dim() == 1:
        shape = [1] * src.dim()
        shape[dim] = -1
        index = index.view(shape)
    return index.expand_as(src)


def scatter_sum(src, index, dim=-1, out=None, dim_size=None):
    idx = _broadcast(index, src, dim)
    if out is None:
        size = list(src.shape)
        if dim_size is not None:
            size[dim if dim >= 0 else src.dim() + dim] = dim_size
        elif index.numel() > 0:
            size[dim if dim >= 0 else src.dim() + dim] = int(index.max()) + 1
        else:
            size[dim if dim >= 0 else src.dim() + dim] = 0
        out = torch.zeros(size, dtype=src.dtype, device=src.device)
    return out.scatter_add_(dim if dim >= 0 else src.dim() + dim, idx, src)


def scatter_add(src, index, dim=-1, out=None, dim_size=None):
    return scatter_sum(src, index, dim, out, dim_size)


def scatter_max(src, index, dim=-1, out=None, dim_size=None):
    d = dim if dim >= 0 else src.dim() + dim
    idx = _broadcast(index, src, d)
    size = list(src.shape)
    size[d] = (dim_size if dim_size is not None
               else (int(index.max()) + 1 if index.numel() else 0))
    res = torch.full(size, float("-inf"), dtype=src.dtype, device=src.device)
    res = res.scatter_reduce_(d, idx, src, reduce="amax", include_self=True)
    # torch_scatter returns (values, argmax); DPVO only reads [0]
    return res, None


def scatter_softmax(src, index, dim=-1, dim_size=None):
    d = dim if dim >= 0 else src.dim() + dim
    mx, _ = scatter_max(src, index, d, dim_size=dim_size)
    idx = _broadcast(index, src, d)
    src_max = mx.gather(d, idx)
    ex = (src - src_max).exp()
    denom = scatter_sum(ex, index, d, dim_size=dim_size).gather(d, idx)
    return ex / denom.clamp(min=1e-12)


def scatter_mean(src, index, dim=-1, out=None, dim_size=None):
    s = scatter_sum(src, index, dim, out, dim_size)
    ones = torch.ones_like(src)
    c = scatter_sum(ones, index, dim, None, dim_size).clamp(min=1)
    return s / c


if __name__ == "__main__":
    torch.manual_seed(0)
    src = torch.randn(1, 12, 5)
    index = torch.tensor([0, 0, 1, 1, 1, 2, 2, 3, 3, 3, 3, 4])
    got = scatter_sum(src, index, dim=1, dim_size=5)
    ref = torch.zeros(1, 5, 5)
    for i, g in enumerate(index.tolist()):
        ref[0, g] += src[0, i]
    print("scatter_sum max abs err", (got - ref).abs().max().item())

    sm = scatter_softmax(src, index, dim=1)
    tot = scatter_sum(sm, index, dim=1, dim_size=5)
    print("scatter_softmax group sums (should all be 1.0):",
          tot[0].sum(-1).tolist())

    mx, _ = scatter_max(src, index, dim=1, dim_size=5)
    ref_mx = torch.full((1, 5, 5), float("-inf"))
    for i, g in enumerate(index.tolist()):
        ref_mx[0, g] = torch.maximum(ref_mx[0, g], src[0, i])
    print("scatter_max max abs err", (mx - ref_mx).abs().max().item())
