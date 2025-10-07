"""Video clip generation utilities using FFmpeg."""

from __future__ import annotations

import logging
import random
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from .errors import RenderError

logger = logging.getLogger("avm")

_LAST_AUTO_PAN: Optional[str] = None


def ken_burns(
    image_path: Path,
    duration: float,
    zoom_from: float = 1.05,
    zoom_to: float = 1.12,
    pan: str = "auto",
    fps: int = 30,
    output_dir: Optional[Path] = None,
) -> Path:
    """Create a Ken Burns animation for a single slide using FFmpeg."""

    if duration <= 0:
        raise RenderError("Ken Burns duration must be positive")

    if not image_path.exists():
        raise RenderError(f"Slide image not found: {image_path}")

    target_dir = output_dir or image_path.parent / "frames"
    target_dir.mkdir(parents=True, exist_ok=True)

    output_path = target_dir / f"{image_path.stem}_{abs(hash((duration, zoom_from, zoom_to, pan, fps))) & 0xFFFF:04x}.mp4"

    frames = max(int(round(duration * fps)), fps)
    frames_den = max(frames - 1, 1)

    chosen_pan = _select_pan_direction(pan)
    zoom_expr = _build_zoom_expression(zoom_from, zoom_to, frames_den)
    x_expr, y_expr = _build_pan_expressions(chosen_pan, frames_den)

    filter_chain = (
        "scale=1920:1080:force_original_aspect_ratio=increase,"  # cover the canvas
        "crop=1920:1080,"  # ensure 16:9
        f"zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}':d={frames}:s=1920x1080:fps={fps},"
        "format=yuv420p"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        str(image_path),
        "-t",
        f"{duration:.3f}",
        "-filter_complex",
        filter_chain,
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-r",
        str(fps),
        "-colorspace",
        "bt709",
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        logger.debug(f"Generated Ken Burns clip at {output_path} ({duration:.2f}s, pan={chosen_pan})")
        return output_path
    except subprocess.CalledProcessError as exc:
        stderr_tail = (exc.stderr or "")[-800:]
        raise RenderError(f"Failed to generate Ken Burns clip\n{stderr_tail}") from exc
    except Exception as exc:
        raise RenderError(f"Failed to generate Ken Burns clip: {exc}") from exc


def _select_pan_direction(pan: str) -> str:
    global _LAST_AUTO_PAN

    pan = (pan or "auto").lower()
    valid = {"left", "right", "up", "down"}

    if pan == "auto" or pan not in valid:
        choices = list(valid)
        if _LAST_AUTO_PAN in choices and len(choices) > 1:
            choices.remove(_LAST_AUTO_PAN)
        pan = random.choice(choices)
        _LAST_AUTO_PAN = pan
    return pan


def _build_zoom_expression(zoom_from: float, zoom_to: float, frames_den: int) -> str:
    if frames_den <= 0 or abs(zoom_to - zoom_from) < 1e-3:
        return f"{zoom_from}"
    return f"{zoom_from}+({zoom_to - zoom_from})*on/{frames_den}"


def _build_pan_expressions(pan: str, frames_den: int) -> Tuple[str, str]:
    if frames_den <= 0:
        frames_den = 1

    x_expr = "(iw-ow)/2"
    y_expr = "(ih-oh)/2"

    if pan == "left":
        x_expr = "(iw-ow) - (iw-ow)*on/%d" % frames_den
    elif pan == "right":
        x_expr = "(iw-ow)*on/%d" % frames_den
    elif pan == "up":
        y_expr = "(ih-oh) - (ih-oh)*on/%d" % frames_den
    elif pan == "down":
        y_expr = "(ih-oh)*on/%d" % frames_den

    return x_expr, y_expr
