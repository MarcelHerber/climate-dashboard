#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

DEFAULT_FPS = 3
PARAMETERS = ("tmean", "tmax", "tmin")


def _frame_paths(regions: Path, manifest: dict, reference: str) -> tuple[list[str], list[Path]]:
    dates = list(manifest.get("available_dates") or [])
    if not dates:
        raise RuntimeError("Keine Tagesanomalie-Frames im Manifest.")

    frames: list[Path] = []
    for day in dates:
        rel = (manifest.get("dates") or {}).get(day, {}).get(reference)
        if not rel:
            raise RuntimeError(f"Frame fehlt im Manifest: {day} · {reference}")
        path = regions / rel
        if not path.exists():
            raise RuntimeError(f"Frame fehlt: {path}")
        frames.append(path)
    return dates, frames


def _render_mp4(frames: list[Path], output: Path, fps: int, ffmpeg: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hyras-daily-anomaly-") as tmp:
        staging = Path(tmp)
        for index, source in enumerate(frames):
            target = staging / f"{index:05d}.png"
            try:
                os.symlink(source.resolve(), target)
            except OSError:
                shutil.copy2(source, target)

        temporary_output = output.with_suffix(".tmp.mp4")
        temporary_output.unlink(missing_ok=True)
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-framerate", str(fps),
            "-i", str(staging / "%05d.png"),
            "-vf",
            "scale=1080:1320:force_original_aspect_ratio=decrease:flags=lanczos,"
            "pad=1080:1320:(ow-iw)/2:(oh-ih)/2:color=white",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(temporary_output),
        ]
        subprocess.run(command, check=True)
        if not temporary_output.exists() or temporary_output.stat().st_size == 0:
            raise RuntimeError(f"FFmpeg hat keine MP4 erzeugt: {temporary_output}")
        temporary_output.replace(output)


def build_parameter(data_root: Path, output_root: Path, parameter: str, fps: int = DEFAULT_FPS) -> dict:
    if parameter not in PARAMETERS:
        raise ValueError(f"Unbekannter Parameter: {parameter}")
    if fps < 1 or fps > 30:
        raise ValueError("FPS muss zwischen 1 und 30 liegen.")

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg ist nicht installiert.")

    regions = data_root / parameter / "regions"
    manifest_path = regions / "daily_anomaly_maps.json"
    if not manifest_path.exists():
        raise RuntimeError(f"Manifest fehlt: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    references = list(manifest.get("references") or [])
    if not references:
        raise RuntimeError("Keine Referenzperioden im Tagesanomalie-Manifest.")

    reference_output: dict[str, dict] = {}
    for reference in references:
        dates, frames = _frame_paths(regions, manifest, reference)
        rel = Path(parameter) / reference / f"hyras_{parameter}_daily_anomalies.mp4"
        output = output_root / rel
        _render_mp4(frames, output, fps, ffmpeg)
        reference_output[reference] = {
            "url": rel.as_posix(),
            "format": "mp4",
            "codec": "h264",
            "fps": fps,
            "frame_count": len(frames),
            "start_date": dates[0],
            "end_date": dates[-1],
        }
        print(
            f"Animation: {parameter} · {reference} · {len(frames)} Frames · {output}",
            flush=True,
        )

    return {
        "data_through": str(manifest.get("data_through") or reference_output[references[0]]["end_date"]),
        "references": reference_output,
    }


def build_all(data_root: Path, output_root: Path, fps: int = DEFAULT_FPS) -> dict:
    output_root.mkdir(parents=True, exist_ok=True)
    parameters = {
        parameter: build_parameter(data_root, output_root, parameter, fps)
        for parameter in PARAMETERS
    }
    snapshot = {
        "schema_version": 1,
        "fps": fps,
        "parameters": parameters,
    }
    (output_root / "manifest.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--parameter", choices=PARAMETERS)
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS)
    args = parser.parse_args()

    data_root = Path(args.data_root)
    output_root = Path(args.output_root)
    if args.parameter:
        meta = build_parameter(data_root, output_root, args.parameter, args.fps)
        output_root.mkdir(parents=True, exist_ok=True)
        (output_root / f"manifest_{args.parameter}.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    else:
        build_all(data_root, output_root, args.fps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
