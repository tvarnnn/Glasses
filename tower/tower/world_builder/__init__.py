"""World Builder: incremental spatial mapping from monocular RGB.

Public surface is deliberately small. See
docs/superpowers/plans/2026-08-22-world-builder-v1.md for the architecture
and, importantly, for what this deliberately does NOT do.
"""

from tower.world_builder.schema import SCHEMA_VERSION

__all__ = ["SCHEMA_VERSION"]
