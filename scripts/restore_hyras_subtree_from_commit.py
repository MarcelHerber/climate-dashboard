#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.github.com"
USER_AGENT = "climate-dashboard-hyras-restore/1.0"


def api_json(url: str, token: str, *, attempts: int = 4) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": USER_AGENT,
    }
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            last = exc
            if attempt >= attempts:
                break
            time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"GitHub-API-Aufruf fehlgeschlagen: {url}: {last}")


def restore(repo: str, commit: str, subtree: str, output: Path, token: str) -> int:
    subtree = subtree.strip("/")
    if not subtree:
        raise SystemExit("--subtree darf nicht leer sein")

    commit_obj = api_json(f"{API}/repos/{repo}/git/commits/{commit}", token)
    tree_sha = commit_obj["tree"]["sha"]
    tree = api_json(f"{API}/repos/{repo}/git/trees/{tree_sha}?recursive=1", token)
    if tree.get("truncated"):
        raise RuntimeError("GitHub lieferte einen abgeschnittenen Repository-Baum; Wiederherstellung abgebrochen.")

    prefix = subtree + "/"
    blobs = [
        item for item in tree.get("tree", [])
        if item.get("type") == "blob" and str(item.get("path", "")).startswith(prefix)
    ]
    if not blobs:
        raise RuntimeError(f"Im Commit {commit} wurde kein Blob unter {subtree}/ gefunden.")

    target_root = output / subtree
    if target_root.exists():
        import shutil
        shutil.rmtree(target_root)
    target_root.mkdir(parents=True, exist_ok=True)

    print(f"Quelle: {repo}@{commit}", flush=True)
    print(f"Stelle nur {subtree}/ wieder her: {len(blobs)} Dateien", flush=True)

    total_bytes = 0
    for pos, item in enumerate(blobs, 1):
        rel = Path(item["path"])
        blob = api_json(f"{API}/repos/{repo}/git/blobs/{item['sha']}", token)
        if blob.get("encoding") != "base64":
            raise RuntimeError(f"Unerwartete Blob-Kodierung für {rel}: {blob.get('encoding')}")
        raw = base64.b64decode(blob.get("content", ""), validate=False)
        target = output / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        total_bytes += len(raw)
        if pos == 1 or pos % 10 == 0 or pos == len(blobs):
            print(f"  {pos}/{len(blobs)} Dateien · {total_bytes / 1024 / 1024:.1f} MB", flush=True)

    print(f"Wiederherstellung fertig: {len(blobs)} Dateien · {total_bytes / 1024 / 1024:.1f} MB", flush=True)
    return len(blobs)


def main() -> int:
    parser = argparse.ArgumentParser(description="Einen einzelnen Unterordner aus einem alten GitHub-Commit wiederherstellen.")
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--commit", required=True)
    parser.add_argument("--subtree", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise SystemExit("GITHUB_TOKEN fehlt")

    count = restore(args.repo, args.commit, args.subtree, Path(args.output), token)
    if count < 1:
        raise SystemExit("Keine Dateien wiederhergestellt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
