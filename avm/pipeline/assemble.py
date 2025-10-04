"""
Video assembly with Ken-Burns effects and video stitching.
"""

import json
import math
from pathlib import Path
from typing import List, Dict, Any, Optional

try:
    from moviepy.editor import (
        VideoFileClip, ImageClip, CompositeVideoClip, 
        concatenate_videoclips
    )
    MOVIEPY_AVAILABLE = True
except ImportError:
    MOVIEPY_AVAILABLE = False

from .errors import RenderError
from .logging import Timer
from .video import ken_burns


def compose_visual_track(slide_pngs: List[Path], timeline: Dict[str, Any], 
                        watermark_cfg: Dict[str, Any], intro_path: Optional[Path] = None,
                        outro_path: Optional[Path] = None, fps: int = 30,
                        config: Optional[Dict[str, Any]] = None,
                        logger=None, project: str = "", project_path: Optional[Path] = None) -> Path:
    """
    Build ImageClips with Ken-Burns per timeline segment.
    
    Args:
        slide_pngs: List of slide PNG paths
        timeline: Timeline data with segments
        watermark_cfg: Watermark configuration
        intro_path: Optional path to intro video
        outro_path: Optional path to outro video
        fps: Video frame rate
        config: Project configuration
        logger: Logger instance
        project: Project name for logging
    
    Returns:
        Path to temporary video_nocap.mp4 file
    """
    if not MOVIEPY_AVAILABLE:
        raise RenderError("moviepy is required for video assembly")
    
    if not slide_pngs:
        raise RenderError("No slide images provided")
    
    config = config or {}
    # Write video_nocap.mp4 to the build directory
    if project_path:
        build_dir = project_path / "build"
        temp_dir = build_dir / "temp"
    else:
        build_dir = Path("build")
        temp_dir = build_dir / "temp"
    
    build_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    video_nocap_path = build_dir / "video_nocap.mp4"
    
    try:
        with Timer(logger, "compose_visual", project, f"Composing visual track with {len(slide_pngs)} slides"):
            # Create Ken-Burns clips for each timeline segment
            slide_clips = []
            
            for segment in timeline.get("segments", []):
                slide_index = segment.get("index", 0)
                duration = segment.get("end", 0.0) - segment.get("start", 0.0)
                
                # Get Ken-Burns parameters
                zoom_from = segment.get("zoom_from", 1.05)
                zoom_to = segment.get("zoom_to", 1.12)
                pan = segment.get("pan", "auto")
                
                # Get corresponding slide image
                if slide_index < len(slide_pngs):
                    slide_path = slide_pngs[slide_index]
                    
                    if slide_path.exists():
                        # Create Ken-Burns clip
                        clip = ken_burns(slide_path, duration, zoom_from, zoom_to, pan)
                        slide_clips.append(clip)
                    else:
                        raise RenderError(f"Slide image not found: {slide_path}")
                else:
                    raise RenderError(f"Slide index {slide_index} out of range for {len(slide_pngs)} slides")
            
            if not slide_clips:
                raise RenderError("No valid slide clips created")
            
            # Add crossfade between slides if configured
            timeline_config = config.get("timeline", {})
            gap_sec = timeline_config.get("gap_sec", 0.0)
            
            if gap_sec > 0:
                slide_clips = _add_crossfades(slide_clips, gap_sec, fps)
            
            # Concatenate slide clips
            main_video = concatenate_videoclips(slide_clips)
            
            # Add intro/outro if provided
            final_clips = []
            
            if intro_path and intro_path.exists():
                intro_clip = VideoFileClip(str(intro_path))
                final_clips.append(intro_clip)
            
            final_clips.append(main_video)
            
            if outro_path and outro_path.exists():
                outro_clip = VideoFileClip(str(outro_path))
                final_clips.append(outro_clip)
            
            if len(final_clips) > 1:
                final_video = concatenate_videoclips(final_clips)
            else:
                final_video = main_video
            
            # Add watermark if configured
            if watermark_cfg.get("enabled", False):
                watermark_path = watermark_cfg.get("path")
                if watermark_path and Path(watermark_path).exists():
                    final_video = _add_watermark_overlay(final_video, watermark_cfg, config)
            
            # Write temporary video without audio (H.264)
            final_video.write_videofile(
                str(video_nocap_path),
                fps=fps,
                codec="libx264",
                audio=False,
                temp_audiofile="temp-audio.m4a",
                remove_temp=True,
                verbose=False,
                logger=None
            )
            
            # Clean up
            final_video.close()
            for clip in slide_clips:
                clip.close()
            
            return video_nocap_path
            
    except Exception as e:
        raise RenderError(f"Failed to compose visual track: {e}")


def _add_crossfades(slide_clips, gap_sec: float, fps: int):
    """
    Add 12-frame crossfade between slides.
    
    Args:
        slide_clips: List of slide clips
        gap_sec: Gap duration in seconds (not used for crossfade timing)
        fps: Video frame rate
    
    Returns:
        List of clips with crossfades
    """
    if len(slide_clips) <= 1:
        return slide_clips
    
    # Fixed crossfade duration (exactly 12 frames)
    crossfade_duration = 12.0 / fps
    
    result_clips = []
    
    for i, clip in enumerate(slide_clips):
        if i == 0:
            # First clip: no crossfade
            result_clips.append(clip)
        else:
            # Subsequent clips: add crossfade with previous clip
            prev_clip = result_clips[-1]
            
            # Create crossfade
            crossfade_start = prev_clip.duration - crossfade_duration
            
            # Fade out previous clip
            prev_clip_fade = prev_clip.fadeout(crossfade_duration)
            
            # Fade in current clip
            current_clip_fade = clip.fadein(crossfade_duration)
            
            # Composite crossfade
            crossfade_clip = CompositeVideoClip([
                prev_clip_fade.set_start(crossfade_start),
                current_clip_fade.set_start(crossfade_start)
            ]).set_duration(crossfade_duration)
            
            # Replace previous clip with faded version
            result_clips[-1] = prev_clip.set_end(crossfade_start)
            
            # Add crossfade and remaining clip
            result_clips.append(crossfade_clip)
            
            # Add remaining part of current clip
            remaining_clip = clip.set_start(crossfade_duration)
            if gap_sec > crossfade_duration:
                remaining_clip = remaining_clip.set_duration(
                    remaining_clip.duration + gap_sec - crossfade_duration
                )
            result_clips.append(remaining_clip)
    
    return result_clips


def _add_watermark_overlay(video_clip, watermark_cfg: Dict[str, Any], config: Dict[str, Any]):
    """
    Add watermark overlay to video clip.
    
    Args:
        video_clip: The video clip to overlay on
        watermark_cfg: Watermark configuration
        config: Project configuration
    
    Returns:
        CompositeVideoClip with watermark overlay
    """
    try:
        watermark_path = watermark_cfg.get("path")
        if not watermark_path or not Path(watermark_path).exists():
            return video_clip
        
        # Get watermark settings
        position = watermark_cfg.get("position", "bottom-right")
        width = watermark_cfg.get("width_px", 220)
        opacity = watermark_cfg.get("opacity", 0.85)
        padding = 24  # Fixed 24px padding as requested
        
        # Create watermark clip
        watermark = ImageClip(str(watermark_path))
        watermark = watermark.resize(width=width)
        watermark = watermark.set_opacity(opacity)
        watermark = watermark.set_duration(video_clip.duration)
        
        # Position watermark with 24px padding
        if position == "bottom-right":
            watermark = watermark.set_position((
                video_clip.w - watermark.w - padding,
                video_clip.h - watermark.h - padding
            ))
        elif position == "bottom-left":
            watermark = watermark.set_position((
                padding,
                video_clip.h - watermark.h - padding
            ))
        elif position == "top-right":
            watermark = watermark.set_position((
                video_clip.w - watermark.w - padding,
                padding
            ))
        elif position == "top-left":
            watermark = watermark.set_position((padding, padding))
        else:
            # Default to bottom-right
            watermark = watermark.set_position((
                video_clip.w - watermark.w - padding,
                video_clip.h - watermark.h - padding
            ))
        
        # Composite with main video
        return CompositeVideoClip([video_clip, watermark])
        
    except Exception as e:
        raise RenderError(f"Failed to add watermark overlay: {e}")


def load_timeline_from_json(timeline_path: Path) -> Dict[str, Any]:
    """
    Load timeline from JSON file.
    
    Args:
        timeline_path: Path to timeline JSON file
    
    Returns:
        Timeline data dictionary
    """
    if not timeline_path.exists():
        raise RenderError(f"Timeline file not found: {timeline_path}")
    
    try:
        with open(timeline_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise RenderError(f"Failed to parse timeline JSON: {e}")
    except Exception as e:
        raise RenderError(f"Failed to load timeline: {e}")


def get_slide_images_from_directory(slides_dir: Path) -> List[Path]:
    """
    Get list of slide images from directory.
    
    Args:
        slides_dir: Directory containing slide images
    
    Returns:
        List of slide image paths, sorted by name
    """
    if not slides_dir.exists():
        raise RenderError(f"Slides directory not found: {slides_dir}")
    
    # Look for PNG files
    slide_files = list(slides_dir.glob("*.png"))
    slide_files.sort()  # Sort by filename
    
    if not slide_files:
        raise RenderError(f"No PNG files found in slides directory: {slides_dir}")
    
    return slide_files


def assemble_video_from_timeline(timeline_path: Path, slides_dir: Path,
                                watermark_cfg: Dict[str, Any],
                                intro_path: Optional[Path] = None,
                                outro_path: Optional[Path] = None,
                                output_path: Optional[Path] = None,
                                config: Optional[Dict[str, Any]] = None,
                                logger=None, project: str = "", project_path: Optional[Path] = None) -> Path:
    """
    Assemble video from timeline and slide images.
    
    Args:
        timeline_path: Path to timeline JSON file
        slides_dir: Directory containing slide images
        watermark_cfg: Watermark configuration
        intro_path: Optional path to intro video
        outro_path: Optional path to outro video
        output_path: Optional output path (defaults to temp video_nocap.mp4)
        config: Project configuration
        logger: Logger instance
        project: Project name for logging
    
    Returns:
        Path to output video file
    """
    config = config or {}
    
    # Load timeline
    timeline = load_timeline_from_json(timeline_path)
    
    # Get slide images
    slide_pngs = get_slide_images_from_directory(slides_dir)
    
    # Set default output path
    if output_path is None:
        if project_path:
            temp_dir = project_path / "build" / "temp"
        else:
            temp_dir = Path("build/temp")
        temp_dir.mkdir(parents=True, exist_ok=True)
        output_path = temp_dir / "video_nocap.mp4"
    
    # Get frame rate from config
    export_config = config.get("export", {})
    fps = export_config.get("fps", 30)
    
    # Compose visual track
    return compose_visual_track(
        slide_pngs, timeline, watermark_cfg,
        intro_path, outro_path, fps, config,
        logger, project, project_path
    )


# Legacy functions for backward compatibility
def ken_burns(image_path: Path, duration: float, zoom: float = 1.10):
    """
    Legacy Ken-Burns function for backward compatibility.
    
    Args:
        image_path: Path to the image file
        duration: Duration of the clip in seconds
        zoom: Zoom factor (1.0 = no zoom, >1.0 = zoom in)
    
    Returns:
        ImageClip with Ken-Burns effect
    """
    # Convert legacy zoom parameter to new format
    zoom_from = 1.0
    zoom_to = zoom
    
    return ken_burns(image_path, duration, zoom_from, zoom_to, "auto")


def overlay_watermark(video_clip, watermark_path: Path, position: str = "top-right",
                     padding: int = 24):
    """
    Legacy watermark function for backward compatibility.
    
    Args:
        video_clip: The video clip to overlay on
        watermark_path: Path to watermark image
        position: Position of watermark
        padding: Padding from edges in pixels
    
    Returns:
        CompositeVideoClip with watermark overlay
    """
    watermark_cfg = {
        "enabled": True,
        "path": str(watermark_path),
        "position": position,
        "width_px": 200,
        "opacity": 0.8
    }
    
    return _add_watermark_overlay(video_clip, watermark_cfg, {})


def assemble_video(slide_images: List[Path], durations: List[float],
                  watermark_path: Optional[Path] = None,
                  intro_path: Optional[Path] = None,
                  outro_path: Optional[Path] = None,
                  output_path: Path = None,
                  fps: int = 30, zoom: float = 1.10,
                  logger=None, project: str = "", project_path: Optional[Path] = None):
    """
    Legacy assemble video function for backward compatibility.
    
    Args:
        slide_images: List of slide image paths
        durations: List of durations for each slide
        watermark_path: Path to watermark image (optional)
        intro_path: Path to intro video (optional)
        outro_path: Path to outro video (optional)
        output_path: Path to output video
        fps: Video frame rate
        zoom: Ken-Burns zoom factor
        logger: Logger instance
        project: Project name for logging
    
    Returns:
        Path to output video
    """
    if not MOVIEPY_AVAILABLE:
        raise RenderError("moviepy is required for video assembly")
    
    if len(slide_images) != len(durations):
        raise RenderError("Number of slide images must match number of durations")
    
    with Timer(logger, "assemble", project, f"Assembling video with {len(slide_images)} slides"):
        # Create simple timeline from durations
        timeline = {
            "segments": []
        }
        
        current_time = 0.0
        for i, duration in enumerate(durations):
            segment = {
                "index": i,
                "start": current_time,
                "end": current_time + duration,
                "zoom_from": 1.05,
                "zoom_to": 1.10 + (zoom - 1.10),
                "pan": ["left", "right", "up", "down"][i % 4]
            }
            timeline["segments"].append(segment)
            current_time += duration
        
        # Create watermark config
        watermark_cfg = {
            "enabled": watermark_path is not None,
            "path": str(watermark_path) if watermark_path else None,
            "position": "bottom-right",
            "width_px": 200,
            "opacity": 0.8
        }
        
        # Use new compose function
        return compose_visual_track(
            slide_images, timeline, watermark_cfg,
            intro_path, outro_path, fps, {},
            logger, project, project_path
        )


def get_slide_durations_from_timeline(timeline_path: Path) -> List[float]:
    """
    Legacy function to extract slide durations from timeline JSON.
    
    Args:
        timeline_path: Path to timeline JSON file
    
    Returns:
        List of slide durations in seconds
    """
    timeline = load_timeline_from_json(timeline_path)
    
    durations = []
    for segment in timeline.get("segments", []):
        duration = segment.get("end", 0.0) - segment.get("start", 0.0)
        durations.append(duration)
    
    return durations


def create_simple_timeline(total_duration: float, num_slides: int) -> List[float]:
    """
    Create simple even-duration timeline.
    
    Args:
        total_duration: Total duration in seconds
        num_slides: Number of slides
    
    Returns:
        List of durations for each slide
    """
    if num_slides <= 0:
        return []
    
    duration_per_slide = total_duration / num_slides
    return [duration_per_slide] * num_slides