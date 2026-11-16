# Live recovery reliability

> **For agentic workers:** Use superpowers:executing-plans or subagent-driven-development; validate before publishing.

**Goal:** Keep live meteorological status accurate and recover missed GitHub schedules.

**Architecture:** Retain the existing guarded GitHub recovery workflow. Add an independent hourly backup invocation via the connected automation scheduler; the existing workflow decides which products need a restart. The browser reads verified MTG metadata directly. A dedicated Cloudflare 15-minute trigger would require a durable narrowly scoped GitHub Actions write credential, which is not assumed to be present.

**Global constraints:** Never expose credentials, weaken data-age thresholds, or fabricate measurement timestamps. Never cancel active imports. Use UTC in data and real observation/model initialization times. Keep the existing public/private separation.

## Tasks

- [x] Regression test the SYNOP read-only fetch against force-replaced archive refs; use explicit forced *local remote-tracking fetches* for the two archive branches. No extra force-push.
- [x] Test and implement MTG live browser merge from `main/data/satellite_wms_times.json`, retaining actual oldest verified core observation time and flagging partial/absent coverage; reject future or older reports. Add browser tests to CI.
- [x] Test and implement Europe Tmax as a guarded recovery source: strict schema-2, complete five-day 00 UTC manifest, >24 hours old and only from 05 UTC onward. Respect active run checks and 180-minute cooldown.
- [ ] Verify with actual source manifests and regression tests. Publish reviewed changes and confirm recovery/Pages runs. Configure the independent hourly backup to rerun only the latest completed recovery job when stale and not already running; report limits honestly.
