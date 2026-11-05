# PostHog code-review orientation

This is a deliberately limited map of the public `PostHog/posthog` paths in
the pilot. It helps a reviewer ask what the changed code does for PostHog;
it is not an official statement of product priorities or measured value.

- `posthog/hogql/`, `frontend/src/queries/`: query planning, metadata and
  visualisation. Look for changes to query correctness or the user's ability
  to interpret results.
- `products/warehouse_sources/`, `products/data_warehouse/`,
  `products/managed_warehouse/`: external data ingestion, syncs, schemas
  and warehouse queries. Look for data integrity, recovery and connector
  behaviour; a new vendor endpoint does not establish customer adoption.
- `nodejs/src/cdp/`, `products/slack_app/`, `products/tasks/`: event-driven
  workflows and integrations. Look for execution, retries, deduplication
  and the boundaries between users, jobs and external services.
- `rust/personhog-replica/`: person identity storage and replication. Look
  for consistency and failure handling; a plausible failure is not proof
  of a production incident.
- `frontend/`, `packages/quill/`, `products/desktop/`: user interfaces
  and shared components. Look for actual interaction or accessibility
  changes, not the amount of UI code.
- `posthog/csp_middleware.py`, `posthog/migration_helpers/`, `bin/`:
  shared security, database migration and build/CI infrastructure.
  Inspect the concrete safeguard or operational path rather than
  treating a security- or performance-sounding name as a score.

These paths are navigation hints, not tiers or point multipliers. A single
line in a central module may be narrow; a small change outside these paths
may be meaningful. Work outside this map is not automatically irrelevant.
For every score, identify an observed change and a plausible PostHog
user, reliability, security, operations or team-enabling mechanism from
the diff. If that connection cannot be supported by code, abstain.
No public diff proves adoption, incident avoidance, author effort or
individual ownership. Neither PR descriptions nor code comments are
independent verification of those outcomes.
