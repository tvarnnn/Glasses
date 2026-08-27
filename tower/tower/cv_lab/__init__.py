"""The Experimental CV Lab as a product surface rather than a variable.

Before this package, choosing an experiment meant editing
`TOWER_CV_EXPERIMENT`, restarting the Tower, starting a generic recording
from somewhere else in the app, and reading an unlabelled number off a
debug panel. Every one of those steps follows from a single fact: the
experiment was decided at process start, and nothing on the wire said
which one it was.

Four modules, in dependency order:

    contracts.py   the strings a phone switches on -- identifiers,
                   lifecycle states, refusal reasons, bounds
    catalog.py     the registry, rendered as the list iOS displays
    run.py         one run's identity and its constant-memory measurements
    lab.py         the slot: lifecycle, selection, the frame path, and the
                   one status document every surface serves

Nothing here persists anything, writes a file, or holds imagery. The
module descriptor this Lab lives behind declares `persists_data=False`
and `retains_raw_imagery=False`, and that declaration is what the privacy
policy is enforced against -- so it has to stay true of this package too.

Nothing here imports a cartridge, and a test says so.
"""

from tower.cv_lab.lab import CommandOutcome, CVLab

__all__ = ["CVLab", "CommandOutcome"]
