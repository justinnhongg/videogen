"""
Video composition with Ken-Burns motion, watermarks, and intro/outro.
"""

import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

try:
    from moviepy.editor import (
        VideoFileClip, ImageClip, CompositeVideoClip, 
        TextClip, concatenate_videoclips
    )
    MOVIEPY_AVAILABLE = True
except ImportError:
    MOVIEPY_AVAILABLE = False

from .errors import RenderError


def compose_video(slide_images: List[Path], timeline: Dict[str, Any],
                 intro_path: Optional[Path], outro_path: Optional[Path],
                 watermark_path: Optional[Path], output_path: Path,
                 config: Dict[str, Any], logger=None, project: str = "") -> None:
    """
    Compose final video with slides, motion, and overlays.
    
    Args:
        slide_images: List of slide PNG paths
        timeline: Timeline data with motion parameters
        intro_path: Path to intro video (optional)
        outro_path: Path to outro video (optional)
        watermark_path: Path to watermark image (optional)
        output_path: Path to output video
        config: Project configuration
        logger: Logger instance
        project: Project name for logging
    """
    
    if not MOVIEPY_AVAILABLE:
        raise RenderError("moviepy is required for video composition")
    
    if not slide_images:
        raise RenderError("No slide images provided")
    
    # Create slide clips with Ken-Burns motion
    slide_clips = []
    
    for segment in timeline["segments"]:
        slide_num = segment["slide_num"]
        if slide_num <= len(slide_images):
            slide_path = slide_images[slide_num - 1]
            
            if slide_path.exists():
                clip = _create_slide_clip_with_motion(
                    slide_path, segment, config
                )
                slide_clips.append(clip)
    
    if not slide_clips:
        raise RenderError("No valid slide clips created")
    
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
    
    # Add watermark if provided
    if watermark_path and watermark_path.exists():
        final_video = _add_watermark(final_video, watermark_path, config)
    
    # Write video
    export_config = config.get("export", {})
    fps = export_config.get("fps", 30)
    
    final_video.write_videofile(
        str(output_path),
        fps=fps,
        codec="libx264",
        audio=False,  # Audio will be added separately
        temp_audiofile="temp-audio.m4a",
        remove_temp=True,
        verbose=False,
        logger=None
    )
    
    # Clean up
    final_video.close()
    for clip in slide_clips:
        clip.close()


def _create_slide_clip_with_motion(slide_path: Path, segment: Dict[str, Any],
                                  config: Dict[str, Any]) -> ImageClip:
    """Create a slide clip with Ken-Burns motion effect."""
    
    duration = segment["duration"]
    kenburns = segment["kenburns"]
    
    # Create base image clip
    clip = ImageClip(str(slide_path), duration=duration)
    
    # Apply Ken-Burns motion
    zoom_start = kenburns["zoom_start"]
    zoom_end = kenburns["zoom_end"]
    pan_x_start = kenburns["pan_x_start"]
    pan_x_end = kenburns["pan_x_end"]
    pan_y_start = kenburns["pan_y_start"]
    pan_y_end = kenburns["pan_y_end"]
    
    # Resize and crop to maintain aspect ratio
    clip = clip.resize(height=1080)  # Standard height
    
    # Apply zoom and pan effects
    def make_frame(t):
        # Calculate progress (0 to 1)
        progress = t / duration
        
        # Apply easing (simple ease-in-out)
        eased_progress = _ease_in_out_sine(progress)
        
        # Calculate current zoom and pan
        current_zoom = zoom_start + (zoom_end - zoom_start) * eased_progress
        current_pan_x = pan_x_start + (pan_x_end - pan_x_start) * eased_progress
        current_pan_y = pan_y_start + (pan_y_end - pan_y_start) * eased_progress
        
        # Get frame
        frame = clip.get_frame(t)
        
        # Apply zoom (resize)
        if current_zoom != 1.0:
            import cv2
            h, w = frame.shape[:2]
            new_h, new_w = int(h * current_zoom), int(w * current_zoom)
            frame = cv2.resize(frame, (new_w, new_h))
            
            # Crop to original size with pan
            if new_h > h or new_w > w:
                start_y = max(0, int((new_h - h) / 2 + pan_y * h))
                end_y = start_y + h
                start_x = max(0, int((new_w - w) / 2 + pan_x * w))
                end_x = start_x + w
                
                frame = frame[start_y:end_y, start_x:end_x]
        
        return frame
    
    # Apply the effect
    clip = clip.fl(make_frame, apply_to=["mask"])
    
    return clip


def _ease_in_out_sine(progress: float) -> float:
    """Ease-in-out sine function for smooth motion."""
    import math
    return -(math.cos(math.pi * progress) - 1) / 2


def _add_watermark(video_clip, watermark_path: Path, config: Dict[str, Any]) -> CompositeVideoClip:
    """Add watermark overlay to video."""
    
    styles = config.get("styles", {})
    logo_config = styles.get("logo", {})
    
    position = logo_config.get("position", "bottom-right")
    width = logo_config.get("width_px", 220)
    opacity = logo_config.get("opacity", 0.85)
    
    # Create watermark clip
    watermark = ImageClip(str(watermark_path))
    watermark = watermark.resize(width=width)
    watermark = watermark.set_opacity(opacity)
    watermark = watermark.set_duration(video_clip.duration)
    
    # Position watermark
    if position == "bottom-right":
        watermark = watermark.set_position(("right", "bottom"))
    elif position == "bottom-left":
        watermark = watermark.set_position(("left", "bottom"))
    elif position == "top-right":
        watermark = watermark.set_position(("right", "top"))
    elif position == "top-left":
        watermark = watermark.set_position(("left", "top"))
    else:
        watermark = watermark.set_position(("right", "bottom"))
    
    # Composite with main video
    return CompositeVideoClip([video_clip, watermark])


def burn_captions_to_video(video_path: Path, captions: List[Dict[str, Any]],
                          output_path: Path, config: Dict[str, Any]) -> None:
    """Burn captions directly into video using FFmpeg."""
    
    styles = config.get("styles", {})
    caption_config = styles.get("caption", {})
    
    font_size = caption_config.get("font_size", 40)
    font_color = styles.get("text_color", "#FFFFFF")
    stroke_color = "#000000"
    stroke_width = caption_config.get("stroke_px", 3)
    safe_bottom_pct = caption_config.get("safe_bottom_pct", 12)
    
    # Create temporary SRT file
    import tempfile
    srt_content = ""
    for i, caption in enumerate(captions, 1):
        start_time = _seconds_to_srt_time(caption["start"])
        end_time = _seconds_to_srt_time(caption["end"])
        text = caption["content"]
        
        srt_content += f"{i}\n{start_time} --> {end_time}\n{text}\n\n"
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.srt', delete=False) as f:
        f.write(srt_content)
        temp_srt_path = f.name
    
    # Create subtitle filter
    filter_str = (
        f"subtitles={temp_srt_path}:"
        f"force_style='FontSize={font_size},"
        f"PrimaryColour={font_color.replace('#', '&H')},"
        f"OutlineColour={stroke_color.replace('#', '&H')},"
        f"Outline={stroke_width},"
        f"Alignment=2'"  # Bottom center
    )
    
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vf", filter_str,
        "-c:a", "copy",
        "-c:v", "libx264",
        str(output_path)
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise RenderError(f"Failed to burn captions: {e}")
    finally:
        # Clean up temp file
        Path(temp_srt_path).unlink(missing_ok=True)


def _seconds_to_srt_time(seconds: float) -> str:
    """Convert seconds to SRT time format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millisecs = int((seconds % 1) * 1000)
    
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millisecs:03d}"
