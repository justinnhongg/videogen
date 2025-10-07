"""Caption handling and SRT processing."""

import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

import srt

from .errors import RenderError


def load_captions_srt(srt_path: Path) -> List[Dict[str, Any]]:
    if not srt_path.exists():
        raise RenderError(f"SRT file not found: {srt_path}")

    try:
        with open(srt_path, "r", encoding="utf-8") as handle:
            content = handle.read()
    except OSError as exc:
        raise RenderError(f"Failed to read SRT file: {exc}") from exc

    captions: List[Dict[str, Any]] = []
    try:
        for entry in srt.parse(content):
            captions.append(
                {
                    "index": entry.index,
                    "start": entry.start.total_seconds(),
                    "end": entry.end.total_seconds(),
                    "content": entry.content.strip(),
                }
            )
    except Exception as exc:
        raise RenderError(f"Failed to parse SRT file: {exc}") from exc

    return captions


def save_captions_srt(captions: List[Dict[str, Any]], srt_path: Path) -> None:
    """Persist caption entries to disk using python-srt."""

    subtitles: List[srt.Subtitle] = []
    for entry in captions:
        subtitles.append(
            srt.Subtitle(
                index=entry.get("index", len(subtitles) + 1),
                start=srt.timedelta(seconds=float(entry["start"])),
                end=srt.timedelta(seconds=float(entry["end"])),
                content=entry.get("content", "") or "",
            )
        )

    try:
        srt_text = srt.compose(subtitles)
        srt_path.write_text(srt_text, encoding="utf-8")
    except Exception as exc:
        raise RenderError(f"Failed to save SRT file: {exc}") from exc


def wrap_captions_by_pixel_width(text: str, font_size: int, max_width_px: int) -> List[str]:
    if not text:
        return [""]

    approx_char_width = max(font_size * 0.6, 1)
    max_chars = max(int(max_width_px / approx_char_width), 1)

    words = text.strip().split()
    if not words:
        return [""]

    lines: List[str] = []
    current = ""

    for word in words:
        trial = f"{current} {word}".strip()
        if len(trial) <= max_chars:
            current = trial
        else:
            if current:
                lines.append(current)
                current = word
            else:
                lines.append(word[:max_chars])
                current = word[max_chars:]

        if len(lines) == 2:
            break

    if len(lines) < 2 and current:
        lines.append(current)

    if len(lines) > 2:
        lines = lines[:2]

    if len(lines) == 2:
        max_second = max_chars
        if len(lines[1]) > max_second:
            lines[1] = lines[1][: max(0, max_second - 3)] + "..."

    return lines or [""]


def burn_captions(
    video_in: Path,
    srt_path: Path,
    video_out: Path,
    font: str,
    size: int,
    outline: int,
    safe_bottom_pct: int,
    watermark_corner: Optional[str] = None,
) -> None:
    if not video_in.exists():
        raise RenderError(f"Input video not found: {video_in}")
    if not srt_path.exists():
        raise RenderError(f"SRT file not found: {srt_path}")

    margin_v = int(1080 * max(safe_bottom_pct, 0) / 100)
    if watermark_corner and watermark_corner.lower().startswith("bottom"):
        margin_v = int(margin_v * 1.05)

    force_style = (
        f"FontName={font},"
        f"FontSize={size},"
        "PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,"
        f"Outline={outline},"
        "BorderStyle=1,"
        f"Alignment=2,MarginV={margin_v}"
    )

    filter_str = f"subtitles={srt_path}:force_style='{force_style}'"

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_in),
        "-vf",
        filter_str,
        "-c:a",
        "copy",
        "-c:v",
        "libx264",
        str(video_out),
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        stderr_tail = (exc.stderr or "")[-800:]
        raise RenderError(f"Failed to burn captions\n{stderr_tail}") from exc
    except Exception as exc:
        raise RenderError(f"Caption burning error: {exc}") from exc


def attach_soft_subs(video_in: Path, srt_path: Path, video_out: Path) -> None:
    if not video_in.exists():
        raise RenderError(f"Input video not found: {video_in}")
    if not srt_path.exists():
        raise RenderError(f"SRT file not found: {srt_path}")

    embed_cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_in),
        "-i",
        str(srt_path),
        "-c",
        "copy",
        "-c:s",
        "mov_text",
        "-metadata:s:s:0",
        "language=eng",
        str(video_out),
    ]

    try:
        subprocess.run(embed_cmd, check=True, capture_output=True, text=True)
        return
    except subprocess.CalledProcessError:
        pass

    fallback_cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_in),
        "-c",
        "copy",
        str(video_out),
    ]

    try:
        subprocess.run(fallback_cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        stderr_tail = (exc.stderr or "")[-800:]
        raise RenderError(f"Failed to attach soft subtitles\n{stderr_tail}") from exc

    try:
        sidecar = video_out.with_suffix(".srt")
        sidecar.write_text(srt_path.read_text(encoding="utf-8"), encoding="utf-8")
    except Exception as exc:
        raise RenderError(f"Failed to create sidecar SRT: {exc}") from exc
