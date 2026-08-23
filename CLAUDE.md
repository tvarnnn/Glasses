# Glasses Monorepo Agent Rules

Default to your assigned subsystem.

`ios/` owns Swift/iOS/DAT/UI/runtime work.

`tower/` owns Python/Tower/CV/ML/storage work.

Cross-read the other subsystem only when needed for integration,
contract reconciliation, debugging, or compatibility analysis.

Do not modify the other subsystem unless the task explicitly authorizes
cross-subsystem changes.

Shared protocol truth lives under `docs/contracts/`.

Shared current-state handoffs live under `docs/agent-handoffs/`.

Never solve a cross-system mismatch by importing implementation details
across subsystem boundaries.