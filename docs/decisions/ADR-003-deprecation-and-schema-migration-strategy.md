# ADR-003: Deprecation and Schema Migration Strategy

## Status
Accepted

## Context
As the Comic Crawler & Sync Pipeline expands with new database tables (Supabase), R2 storage structures, and API signatures, we require a clear lifecycle discipline for deprecating legacy interfaces and applying zero-downtime database migrations.

## Decisions

### 1. Zero-Downtime Database Migrations (Expand / Contract)
When modifying Supabase tables (`stories`, `chapters`, `authors`, `categories`, `genres`):
- **Never rename or drop columns in place.**
- **Phase 1 (Expand):** Add new column / table as nullable with default values.
- **Phase 2 (Dual-Write / Backfill):** Sync pipeline writes both old and new representations during sync runs.
- **Phase 3 (Contract):** Once no active consumers or crawlers query the old column, remove the legacy column in a subsequent dedicated deploy.

### 2. Backward-Compatible API Deprecations
- Legacy function signatures and parameter names (such as `format` in `LibraryManager.add_or_update_comic`) must remain functional across minor releases (`v1.x.x`).
- Emit standard Python `DeprecationWarning` with clear migration guidance.
- Removal of deprecated shims is strictly reserved for major version boundaries (`v2.0.0`).

### 3. Zombie Code Audit Cadence
- Any unused batch scripts or orphaned functions are reviewed on minor version releases.
- Unreferenced legacy dependencies must be pruned to maintain low attack surface and minimal maintenance overhead.

## Consequences
- **Positive:** Zero sync downtime, seamless consumer upgrades without breaking changes.
- **Negative:** Requires temporary maintenance of deprecation shims until major releases.
