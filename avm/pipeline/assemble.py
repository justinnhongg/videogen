"""Video assembly using FFmpeg-generated slide clips."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .errors import RenderError
from .logging import Timer
from .timeline import load_timeline_from_json
from .video import ken_burns

logger = logging.getLogger("avm")


def get_slide_images_from_directory(slides_dir: Path) -> List[Path]:
    if not slides_dir.exists():
        raise RenderError(f"Slides directory not found: {slides_dir}")

    slide_paths = sorted(slides_dir.glob("slide_*.png"))
    if not slide_paths:
        slide_paths = sorted(slides_dir.glob("*.png"))
    if not slide_paths:
        raise RenderError(f"No slide images found in {slides_dir}")
    return slide_paths


def assemble_video_from_timeline(
    timeline_path: Path,
    slides_dir: Path,
    watermark_cfg: Dict[str, Any],
    intro_path: Optional[Path] = None,
    outro_path: Optional[Path] = None,
    output_path: Optional[Path] = None,
    config: Optional[Dict[str, Any]] = None,
    logger=None,
    project: str = "",
    project_path: Optional[Path] = None,
) -> Path:
    config = config or {}
    if output_path is None:
        raise RenderError("Output path is required for video assembly")

    slides = get_slide_images_from_directory(slides_dir)
    timeline = load_timeline_from_json(timeline_path)
    fps = _resolve_fps(config)

    build_dir = output_path.parent
    temp_dir = build_dir / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    slide_segments = timeline.get("segments", [])
    if not slide_segments:
        raise RenderError("Timeline contains no segments")

    generated_clips: List[Tuple[Path, float]] = []

    with Timer(logger, "assemble", project, f"Generating Ken Burns clips for {len(slide_segments)} segments"):
        for segment in slide_segments:
            idx = segment.get("index")
            if idx is None:
                idx = segment.get("slide_num", 1) - 1
            if idx is None or idx < 0 or idx >= len(slides):
                raise RenderError(f"Timeline references missing slide index: {segment}")

            duration = segment.get("duration")
            if duration is None:
                duration = float(segment.get("end", 0.0)) - float(segment.get("start", 0.0))
            if duration <= 0:
                raise RenderError(f"Invalid duration for segment {segment}")

            zoom_from = segment.get("zoom_from")
            zoom_to = segment.get("zoom_to")
            pan = segment.get("pan")
            if "kenburns" in segment:
                kb = segment["kenburns"] or {}
                zoom_from = kb.get("zoom_start", zoom_from)
                zoom_to = kb.get("zoom_end", zoom_to)
                pan = kb.get("pan", pan)

            zoom_from = zoom_from if zoom_from is not None else 1.05
            zoom_to = zoom_to if zoom_to is not None else 1.12
            pan = pan or "auto"

            slide_path = slides[idx]
            if logger:
                logger.info(f"Applying Ken Burns effect to {slide_path.name} ({duration:.2f}s, pan={pan})")

            clip_path = ken_burns(
                slide_path,
                duration=duration,
                zoom_from=zoom_from,
                zoom_to=zoom_to,
                pan=pan,
                fps=fps,
                output_dir=temp_dir / "frames",
            )
            generated_clips.append((clip_path, duration))

    try:
        slide_video = _combine_slide_clips(generated_clips, config, temp_dir, fps, logger)
        master_video = _attach_intro_outro(slide_video, intro_path, outro_path, temp_dir, fps, logger)
        final_video = _apply_watermark_if_needed(master_video, watermark_cfg, temp_dir, fps, logger)
        shutil.move(str(final_video), str(output_path))
        if logger:
            logger.info(f"Visual track saved to {output_path}")
        return output_path
    finally:
        _cleanup_temp(temp_dir)


def _combine_slide_clips(
    clips: List[Tuple[Path, float]],
    config: Dict[str, Any],
    temp_dir: Path,
    fps: int,
    logger=None,
) -> Path:
    if not clips:
        raise RenderError("No slide clips generated")

    if len(clips) == 1:
        if logger:
            logger.info("Single slide clip generated; skipping concatenation stage")
        return clips[0][0]

    gap_sec = float(config.get("timeline", {}).get("gap_sec", 0.0))
    if gap_sec > 0:
        if logger:
            logger.info("Applying crossfades between slide clips")
        return _apply_crossfades(clips, min(0.4, gap_sec), temp_dir, fps, logger)

    concat_target = temp_dir / "slides_concat.mp4"
    if logger:
        logger.info(f"Concatenating {len(clips)} segments -> {concat_target.name}")
    _concat_with_demuxer([clip for clip, _ in clips], concat_target)
    return concat_target


def _apply_crossfades(
    clips: List[Tuple[Path, float]],
    fade_duration: float,
    temp_dir: Path,
    fps: int,
    logger=None,
) -> Path:
    current_path, current_duration = clips[0]

    for index, (next_path, next_duration) in enumerate(clips[1:], start=1):
        output_path = temp_dir / f"xfade_{index:03d}.mp4"
        usable_duration = max(min(fade_duration, current_duration - 0.05, next_duration - 0.05), 0.1)
        offset = max(current_duration - usable_duration, 0.0)

        filter_complex = (
            f"[0:v][1:v]xfade=transition=fade:duration={usable_duration:.3f}:offset={offset:.3f}"
        )

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(current_path),
            "-i",
            str(next_path),
            "-filter_complex",
            filter_complex,
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
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
        except subprocess.CalledProcessError as exc:
            stderr_tail = (exc.stderr or "")[-800:]
            raise RenderError(f"Failed to apply crossfade\n{stderr_tail}") from exc

        current_duration = current_duration + next_duration - usable_duration
        current_path = output_path

    return current_path


def _concat_with_demuxer(clips: Sequence[Path], destination: Path) -> None:
    filelist = destination.parent / "concat.txt"
    filelist.write_text("\n".join(f"file '{clip}'" for clip in clips), encoding="utf-8")

    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(filelist),
        "-c",
        "copy",
        str(destination),
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        stderr_tail = (exc.stderr or "")[-800:]
        raise RenderError(f"Failed to concatenate slide clips\n{stderr_tail}") from exc
    finally:
        filelist.unlink(missing_ok=True)


def _attach_intro_outro(
    slide_clip: Path,
    intro: Optional[Path],
    outro: Optional[Path],
    temp_dir: Path,
    fps: int,
    logger=None,
) -> Path:
    segments: List[Path] = []

    for candidate in (intro, slide_clip, outro):
        if candidate and candidate.exists():
            if candidate is slide_clip:
                segments.append(candidate)
            else:
                prepared = temp_dir / f"prepared_{candidate.stem}.mp4"
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(candidate),
                    "-an",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "medium",
                    "-crf",
                    "18",
                    "-pix_fmt",
                    "yuv420p",
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
                    str(prepared),
                ]
                try:
                    subprocess.run(cmd, check=True, capture_output=True, text=True)
                except subprocess.CalledProcessError as exc:
                    stderr_tail = (exc.stderr or "")[-800:]
                    raise RenderError(f"Failed to normalise intro/outro clip\n{stderr_tail}") from exc
                segments.append(prepared)

    if len(segments) == 1:
        return segments[0]

    target = temp_dir / "with_bookends.mp4"
    if logger:
        logger.info(f"Concatenating intro/slide/outro segments -> {target.name}")
    _concat_with_demuxer(segments, target)
    return target


def _apply_watermark_if_needed(
    video_path: Path,
    watermark_cfg: Dict[str, Any],
    temp_dir: Path,
    fps: int,
    logger=None,
) -> Path:
    if not watermark_cfg.get("enabled"):
        return video_path

    watermark_path = watermark_cfg.get("path")
    if not watermark_path:
        return video_path

    watermark_file = Path(watermark_path)
    if not watermark_file.exists():
        if logger:
            logger.warning(f"Watermark file not found: {watermark_file}")
        return video_path

    position = (watermark_cfg.get("position") or "bottom-right").lower()
    opacity = float(watermark_cfg.get("opacity", 0.85))
    width = int(watermark_cfg.get("width_px", 220))
    padding = 24

    x_expr, y_expr = _overlay_position(position, padding)

    target = temp_dir / "watermarked.mp4"
    if logger:
        logger.info(f"Overlaying watermark in {position} corner")
    filter_complex = (
        f"[1:v]scale={width}:-1,format=rgba,colorchannelmixer=aa={opacity}[wm];"
        f"[0:v][wm]overlay={x_expr}:{y_expr}:format=auto"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(watermark_file),
        "-filter_complex",
        filter_complex,
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
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
        str(target),
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return target
    except subprocess.CalledProcessError as exc:
        stderr_tail = (exc.stderr or "")[-800:]
        raise RenderError(f"Failed to apply watermark\n{stderr_tail}") from exc


def _overlay_position(position: str, padding: int) -> Tuple[str, str]:
    if position == "top-left":
        return str(padding), str(padding)
    if position == "top-right":
        return f"W-w-{padding}", str(padding)
    if position == "bottom-left":
        return str(padding), f"H-h-{padding}"
    # default bottom-right
    return f"W-w-{padding}", f"H-h-{padding}"


def _resolve_fps(config: Dict[str, Any]) -> int:
    export_cfg = config.get("export", {})
    return int(export_cfg.get("fps", 30))


def _cleanup_temp(temp_dir: Path) -> None:
    if not temp_dir.exists():
        return
    for item in temp_dir.iterdir():
        try:
            if item.is_file():
                item.unlink()
            else:
                shutil.rmtree(item)
        except Exception:  # pragma: no cover - best effort cleanup
            pass


# Legacy compatibility -----------------------------------------------------


def compose_visual_track(*args, **kwargs):  # pragma: no cover - compatibility
    raise RenderError("compose_visual_track is no longer supported. Use assemble_video_from_timeline instead.")


def assemble_video(
    slide_images: List[Path],
    durations: List[float],
    watermark_path: Optional[Path] = None,
    intro_path: Optional[Path] = None,
    outro_path: Optional[Path] = None,
    output_path: Optional[Path] = None,
    fps: int = 30,
    zoom: float = 1.10,
    logger=None,
    project: str = "",
    project_path: Optional[Path] = None,
    config: Optional[Dict[str, Any]] = None,
):  # pragma: no cover - compatibility wrapper
    if project_path is None or output_path is None:
        raise RenderError("Project path and output path are required for assembly")

    timeline_path = project_path / "build" / "timeline.json"
    if not timeline_path.exists():
        raise RenderError(f"Timeline not found at {timeline_path}")

    watermark_cfg = {
        "enabled": watermark_path is not None,
        "path": str(watermark_path) if watermark_path else None,
        "position": (config or {}).get("watermark", {}).get("position", "bottom-right") if config else "bottom-right",
        "width_px": (config or {}).get("watermark", {}).get("width_px", 220) if config else 220,
        "opacity": (config or {}).get("watermark", {}).get("opacity", 0.85) if config else 0.85,
    }

    return assemble_video_from_timeline(
        timeline_path,
        project_path / "build" / "slides",
        watermark_cfg,
        intro_path=intro_path,
        outro_path=outro_path,
        output_path=output_path,
        config=config,
        logger=logger,
        project=project,
        project_path=project_path,
    )
