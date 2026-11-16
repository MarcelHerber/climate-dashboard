# GitHub Pages artifact readiness implementation plan

> **For agentic workers:** use superpowers:executing-plans and test-driven development.

**Goal:** Prevent transient artifact visibility failures from terminating Pages deployment.

**Architecture:** Check the exact uploaded artifact ID and name through the run-scoped Actions REST API before deploying; require two consecutive confirmations. If the official deploy action fails, recheck readiness and retry once, preserving failure on exhaustion.

**Tech stack:** GitHub Actions, Node.js built-in fetch and test runner.

**Scope:** Only the Pages workflow and its readiness helper/test; no weather data changes. Preserve concurrency, build, environment URL, and existing triggers. Never publish a different artifact, hide final failures, or retry indefinitely.

- [ ] Add tests for delayed visibility, mismatched/expired artifacts, transient API errors, permanent authorization failures, and timeout.
- [ ] Run tests before implementing the helper.
- [ ] Implement bounded polling and wire it into the workflow before first deploy and one retry. Use the upload's returned artifact ID.
- [ ] Run tests and check YAML, review the diff, then publish via GitHub pull request.
