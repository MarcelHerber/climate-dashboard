#!/usr/bin/env bash
# GitHub Releases occasionally return transient "release not found" or 5xx
# during long ERA5 upload sequences. Retry reads and idempotent writes.
# Usage: source scripts/era5_gh_retry.sh; gh_retry gh release view "$TAG"
#
# For release upload, always pass --clobber so a retry is safe if the server
# completed the upload before the client lost the connection.
gh_retry() {
  local attempt rc=0 delay
  for attempt in 1 2 3 4 5 6; do
    if "$@"; then
      return 0
    else
      rc=$?
    fi
    if (( attempt == 6 )); then
      echo "::error::GitHub Release operation failed after $attempt attempts (exit $rc): $*" >&2
      return "$rc"
    fi
    delay=$((attempt * 5))
    echo "::warning::GitHub Release temporarily unavailable (attempt $attempt/6). Retry in ${delay}s: $*" >&2
    sleep "$delay"
  done
}
gh_release_assets() {
  local tag="$1"
  gh_retry gh release view "$tag" --json assets --jq '.assets[].name'
}
