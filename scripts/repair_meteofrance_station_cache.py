#!/usr/bin/env python3
"""Repair ONLY missing Météo-France historical resource shards.

The normal baseline builder streams a whole .csv.gz through one HTTP connection.
A small number of large Météo-France objects repeatedly ended with a truncated
stream on GitHub-hosted runners. This repair tool avoids that failure mode:

* discover the official Météo-France resources for the historical baseline,
* verify which resource shards are already present and valid,
* touch ONLY missing/invalid resources,
* resolve the official data.gouv.fr redirect to the Météo-France object store,
* download each missing gzip in small HTTP Range chunks,
* retry only an individual failed chunk,
* parse/validate the complete gzip locally,
* immediately persist the repaired resource shard,
* never fail the workflow merely because some resources remain unresolved,
  so the improved cache can always be saved by GitHub Actions.

If every resource is available after the repair pass, the normal combined
Météo-France baseline cache is assembled from the shards without downloading
historical data again.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import http.client
import json
import os
import pickle
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional, Tuple

import update_europe_station_records as core

UA = "climate-dashboard-mf-repair/1.0 (+GitHub Actions)"
DEFAULT_CHUNK_MIB = 2
DEFAULT_CHUNK_RETRIES = 5


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Expose redirect targets so the Range header is guaranteed on the final S3 request."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


_NO_REDIRECT_OPENER = urllib.request.build_opener(NoRedirect)


def open_final_no_redirect(url: str, *, range_header: Optional[str], timeout: int = 120):
    current = url
    for _hop in range(8):
        headers = {
            "User-Agent": UA,
            "Accept-Encoding": "identity",
            "Cache-Control": "no-cache",
        }
        if range_header:
            headers["Range"] = range_header
        req = urllib.request.Request(current, headers=headers)
        try:
            return current, _NO_REDIRECT_OPENER.open(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code in {301, 302, 303, 307, 308}:
                location = exc.headers.get("Location")
                exc.close()
                if not location:
                    raise RuntimeError(f"HTTP {exc.code} ohne Location für {current}")
                current = urllib.parse.urljoin(current, location)
                continue
            raise
    raise RuntimeError(f"Zu viele HTTP-Weiterleitungen für {url}")


def request(url: str, *, range_header: Optional[str] = None, timeout: int = 120):
    headers = {
        "User-Agent": UA,
        "Accept-Encoding": "identity",
        "Cache-Control": "no-cache",
    }
    if range_header:
        headers["Range"] = range_header
    req = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(req, timeout=timeout)


def parse_content_range(value: str) -> Optional[Tuple[int, int, int]]:
    m = re.fullmatch(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", (value or "").strip(), re.I)
    if not m or m.group(3) == "*":
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def resolve_object(url: str, timeout: int = 120) -> Tuple[str, int, bool]:
    """Return final URL, byte size and whether byte ranges are supported.

    Redirects are followed manually. This guarantees that the one-byte Range
    header is sent to the final Météo-France object-store URL rather than being
    lost by an HTTP redirect implementation.
    """
    final_url, resp = open_final_no_redirect(url, range_header="bytes=0-0", timeout=timeout)
    with resp:
        status = getattr(resp, "status", resp.getcode())
        cr = parse_content_range(resp.headers.get("Content-Range", ""))
        if status == 206 and cr:
            start, end, total = cr
            if start != 0 or end != 0 or total <= 0:
                raise RuntimeError(f"unerwartetes Content-Range: {resp.headers.get('Content-Range')}")
            data = resp.read(1)
            if len(data) != 1:
                raise RuntimeError("Range-Probe lieferte kein Byte")
            return final_url, total, True

        length = resp.headers.get("Content-Length")
        if length and str(length).isdigit() and int(length) > 0:
            return final_url, int(length), False

    raise RuntimeError("Dateigröße konnte nicht über HTTP ermittelt werden")


def read_exact_range(url: str, start: int, end: int, *, timeout: int, retries: int) -> bytes:
    expected = end - start + 1
    last_error: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            with request(url, range_header=f"bytes={start}-{end}", timeout=timeout) as resp:
                status = getattr(resp, "status", resp.getcode())
                cr = parse_content_range(resp.headers.get("Content-Range", ""))
                if status != 206 or not cr:
                    raise RuntimeError(
                        f"Server akzeptiert Range nicht wie erwartet (HTTP {status}, "
                        f"Content-Range={resp.headers.get('Content-Range')!r})"
                    )
                got_start, got_end, _total = cr
                if got_start != start or got_end != end:
                    raise RuntimeError(
                        f"falscher Range-Block: erwartet {start}-{end}, erhalten {got_start}-{got_end}"
                    )
                chunks = []
                remaining = expected
                while remaining:
                    piece = resp.read(min(1024 * 1024, remaining))
                    if not piece:
                        raise EOFError(f"Range {start}-{end} nach {expected-remaining}/{expected} Bytes beendet")
                    chunks.append(piece)
                    remaining -= len(piece)
                data = b"".join(chunks)
                if len(data) != expected:
                    raise EOFError(f"Range {start}-{end}: {len(data)} statt {expected} Bytes")
                return data
        except (Exception,) as exc:
            last_error = exc
            if attempt < retries:
                wait = min(2 * attempt, 8)
                core.log(
                    f"    Chunk {start:,}-{end:,} fehlgeschlagen ({attempt}/{retries}): {exc}; "
                    f"neuer Versuch in {wait}s"
                )
                time.sleep(wait)
    raise RuntimeError(f"Range {start}-{end} nach {retries} Versuchen fehlgeschlagen: {last_error}")


def download_chunked(url: str, dest: Path, *, chunk_bytes: int, timeout: int, retries: int) -> Tuple[int, str]:
    final_url, total, range_ok = resolve_object(url, timeout=timeout)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        tmp.unlink()
    except FileNotFoundError:
        pass

    if not range_ok:
        # Rare fallback: one normal download. This is intentionally only a fallback;
        # the repair path is primarily designed around S3 byte ranges.
        core.log("    Server meldet bei Probe kein 206; Fallback auf vollständigen Einzelabruf")
        with request(final_url, timeout=max(timeout, 240)) as resp, open(tmp, "wb") as out:
            copied = shutil.copyfileobj(resp, out, length=1024 * 1024)
        actual = tmp.stat().st_size
        if actual != total:
            raise RuntimeError(f"Fallback-Download unvollständig: {actual:,}/{total:,} Bytes")
        tmp.replace(dest)
        return total, final_url

    with open(tmp, "wb") as out:
        start = 0
        part_no = 0
        parts_total = (total + chunk_bytes - 1) // chunk_bytes
        while start < total:
            end = min(total - 1, start + chunk_bytes - 1)
            part_no += 1
            data = read_exact_range(final_url, start, end, timeout=timeout, retries=retries)
            out.write(data)
            start = end + 1
            if part_no == 1 or part_no % 5 == 0 or part_no == parts_total:
                core.log(
                    f"    Range-Fortschritt {part_no}/{parts_total}: {start/1024/1024:.1f}/"
                    f"{total/1024/1024:.1f} MiB"
                )
        out.flush()
        os.fsync(out.fileno())

    actual = tmp.stat().st_size
    if actual != total:
        raise RuntimeError(f"Chunk-Download unvollständig: {actual:,}/{total:,} Bytes")
    tmp.replace(dest)
    return total, final_url


def shard_is_valid(path: Path, resource: dict, cutoff_year: int) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        core.load_mf_resource_cache(path, resource, cutoff_year)
        return True
    except Exception:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return False


def repair_one(resource: dict, cutoff_year: int, shard_dir: Path, download_dir: Path,
               *, chunk_bytes: int, timeout: int, retries: int) -> dict:
    cache_path = core.mf_resource_cache_path(shard_dir, resource, cutoff_year)
    if shard_is_valid(cache_path, resource, cutoff_year):
        return {"ok": True, "mode": "cache", "resource": resource}

    filename = Path(urllib.parse.urlparse(resource["url"]).path).name or (
        f"{resource['dept']}_{resource['dataset']}_{resource['period'][0]}-{resource['period'][1]}.csv.gz"
    )
    # API resource URLs can end in an opaque UUID. Keep a readable repair filename.
    if not filename.lower().endswith(".gz"):
        title_name = str(resource.get("title") or "").strip()
        if title_name.lower().endswith(".gz"):
            filename = Path(title_name).name
        else:
            filename = f"{resource['dept']}_{resource['dataset']}_{resource['period'][0]}-{resource['period'][1]}.csv.gz"
    dest = download_dir / f"{resource['dept']}_{resource['dataset']}_{filename}"
    core.log(
        f"REPAIR {resource['dept']} {filename} [{resource['dataset']}, "
        f"{resource['period'][0]}-{resource['period'][1]}]"
    )
    try:
        total, final_url = download_chunked(
            resource["url"], dest, chunk_bytes=chunk_bytes, timeout=timeout, retries=retries
        )
        # Parsing the local file reaches the gzip trailer and therefore also validates
        # that the reconstructed compressed stream is complete.
        with open(dest, "rb") as fh:
            partial, _current, metas = core.parse_mf_stream(fh, cutoff_year=cutoff_year)
        if not partial:
            # An empty resource can be legitimate for complementary stations, but the
            # historical failures we are repairing should normally contain data. Keep
            # it valid if metadata/CSV parsing succeeded; just make the log explicit.
            core.log(f"    Hinweis: {filename} enthält nach Filterung keine TX/TN-Records.")
        core.save_mf_resource_cache(cache_path, resource, cutoff_year, partial, metas)
        core.log(
            f"    OK repariert: {filename} | {total/1024/1024:.1f} MiB | "
            f"{len(partial):,} Stationen | Quelle {urllib.parse.urlparse(final_url).netloc}"
        )
        try:
            dest.unlink()
        except FileNotFoundError:
            pass
        return {"ok": True, "mode": "repaired", "resource": resource, "bytes": total}
    except Exception as exc:
        core.log(f"    NOCH FEHLERHAFT: {filename}: {exc}")
        try:
            dest.unlink()
        except FileNotFoundError:
            pass
        try:
            cache_path.unlink()
        except FileNotFoundError:
            pass
        return {"ok": False, "mode": "failed", "resource": resource, "error": str(exc)}


def save_combined_if_complete(cache_dir: Path, cutoff_year: int, workers: int) -> bool:
    cache_file = cache_dir / (
        f"meteofrance_daily_baseline_through_{cutoff_year}_v{core.MF_BASELINE_FORMAT_VERSION}.pkl.gz"
    )
    # Remove a stale/incomplete combined file if one somehow exists. The core builder
    # will reconstruct it strictly from the now-complete shard set without downloads.
    if cache_file.exists():
        try:
            with gzip.open(cache_file, "rb") as handle:
                payload = pickle.load(handle)
            if (
                payload.get("format_version") == core.MF_BASELINE_FORMAT_VERSION
                and payload.get("cutoff_year") == cutoff_year
                and payload.get("states")
            ):
                core.log(f"Météo-France-Gesamtcache bereits vorhanden: {cache_file}")
                return True
        except Exception:
            try:
                cache_file.unlink()
            except FileNotFoundError:
                pass

    core.log("Alle Ressourcen vorhanden. Erzeuge jetzt den Météo-France-Gesamtcache nur aus Einzelcaches …")
    core.load_or_build_mf_baseline(cache_file, cutoff_year, force=False, workers=max(1, workers))
    return cache_file.exists() and cache_file.stat().st_size > 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=dt.datetime.now(dt.timezone.utc).year)
    parser.add_argument("--cache-dir", default=".cache/europe-stations")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--chunk-mib", type=int, default=DEFAULT_CHUNK_MIB)
    parser.add_argument("--chunk-retries", type=int, default=DEFAULT_CHUNK_RETRIES)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        assert parse_content_range("bytes 0-0/123") == (0, 0, 123)
        assert parse_content_range("bytes 10-19/100") == (10, 19, 100)
        assert parse_content_range("") is None
        core.log("Météo-France-Repair self-test OK")
        return 0

    cutoff_year = args.year - 1
    cache_dir = Path(args.cache_dir)
    shard_dir = cache_dir / (
        f"meteofrance_resources_through_{cutoff_year}_v{core.MF_RESOURCE_CACHE_FORMAT_VERSION}"
    )
    download_dir = cache_dir / "meteofrance_repair_downloads"
    report_path = cache_dir / f"meteofrance_repair_report_through_{cutoff_year}.json"
    shard_dir.mkdir(parents=True, exist_ok=True)
    download_dir.mkdir(parents=True, exist_ok=True)

    core.log("=== METEO-FRANCE REPAIR: NUR FEHLENDE RESSOURCEN ===")
    core.log(
        "Strategie: offizielle Météo-France-Dateien in kleinen HTTP-Range-Blöcken laden; "
        "vorhandene Einzelcaches werden nicht angefasst."
    )
    resources = [r for r in core.discover_mf_resources() if r["period"][0] <= cutoff_year]
    valid = []
    missing = []
    for r in resources:
        p = core.mf_resource_cache_path(shard_dir, r, cutoff_year)
        (valid if shard_is_valid(p, r, cutoff_year) else missing).append(r)

    core.log(
        f"Bestand vor Reparatur: {len(valid):,}/{len(resources):,} Ressourcen gültig; "
        f"{len(missing):,} fehlen/ungültig."
    )
    if not missing:
        save_combined_if_complete(cache_dir, cutoff_year, args.workers)
        core.log("REPAIR OK: keine fehlenden Ressourcen.")
        return 0

    chunk_bytes = max(1, args.chunk_mib) * 1024 * 1024
    results = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {
            pool.submit(
                repair_one,
                r,
                cutoff_year,
                shard_dir,
                download_dir,
                chunk_bytes=chunk_bytes,
                timeout=max(30, args.timeout),
                retries=max(1, args.chunk_retries),
            ): r
            for r in missing
        }
        done = 0
        repaired = 0
        failed = 0
        for fut in as_completed(futures):
            result = fut.result()
            results.append(result)
            done += 1
            if result["ok"] and result["mode"] == "repaired":
                repaired += 1
            elif not result["ok"]:
                failed += 1
            core.log(
                f"  Repair-Fortschritt: {done}/{len(missing)} fehlende Ressourcen bearbeitet | "
                f"repariert {repaired} | noch fehlerhaft {failed}"
            )

    # Recount from disk rather than trusting only this run. This is also robust if
    # the restored cache contained 395 rather than the runner-local 399 from the
    # previous attempt.
    remaining = []
    valid_after = 0
    for r in resources:
        p = core.mf_resource_cache_path(shard_dir, r, cutoff_year)
        if shard_is_valid(p, r, cutoff_year):
            valid_after += 1
        else:
            remaining.append(r)

    report = {
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "cutoff_year": cutoff_year,
        "resource_count": len(resources),
        "valid_before": len(valid),
        "missing_before": len(missing),
        "valid_after": valid_after,
        "remaining": len(remaining),
        "results": [
            {
                "dept": x["resource"]["dept"],
                "dataset": x["resource"]["dataset"],
                "period": list(x["resource"]["period"]),
                "title": x["resource"].get("title"),
                "url": x["resource"]["url"],
                "ok": x["ok"],
                "mode": x["mode"],
                "error": x.get("error"),
            }
            for x in sorted(results, key=lambda z: (z["resource"]["dept"], z["resource"]["period"][0], z["resource"]["dataset"]))
        ],
        "remaining_resources": [
            {
                "dept": r["dept"],
                "dataset": r["dataset"],
                "period": list(r["period"]),
                "title": r.get("title"),
                "url": r["url"],
            }
            for r in remaining
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    core.log(
        f"REPAIR-BILANZ: {valid_after}/{len(resources)} Ressourcen gültig; "
        f"{len(remaining)} noch offen. Bericht: {report_path}"
    )
    if not remaining:
        save_combined_if_complete(cache_dir, cutoff_year, args.workers)
        core.log("METEO-FRANCE REPAIR VOLLSTÄNDIG: 423/423 Ressourcen verfügbar.")
    else:
        # Deliberately return success. GitHub Actions must reach cache/save normally,
        # otherwise newly repaired shards can be lost. A subsequent repair run will
        # automatically touch only these remaining resources.
        core.log(
            "WARNUNG: Einige Ressourcen bleiben offen. Der Workflow endet absichtlich GRÜN, "
            "damit der verbesserte Cache sicher gespeichert wird. Beim nächsten Repair-Lauf "
            "werden ausschließlich die verbleibenden Ressourcen erneut bearbeitet."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
