# Isolated loading experiment

- Reference: commit a31c742 (unmodified baseline workflow and measurements).
- Extract the generated Pages index's main classic script byte-for-byte, after
  all existing build transformations. Leave the early theme script inline.
- Defer external scripts in dependency/execution order; preserve the previously
  deferred tail relative to the former synchronous scripts.
- Remove eager export libraries only after wiring all index export consumers
  to a shared, retryable loader. Preserve the existing library versions.
- Compare cold runs on the same frozen resource snapshot, browser and Lighthouse
  configuration per device. Validate navigation, maps, exports, theme and mobile
  layouts before any decision about merging.
- No changes to main, no Pages deployment.

Date provenance: the archived reports record the runner's UTC measurement date
2026-11-20; the user reported their local date as 2026-11-16. The archived
measurement timestamps and metrics remain unchanged.
