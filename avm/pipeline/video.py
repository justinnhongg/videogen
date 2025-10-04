"""
Video composition with Ken-Burns motion, watermarks, and intro/outro.
"""

import math
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

try:
    from moviepy.editor import (
        VideoFileClip, ImageClip, CompositeVideoClip, 
        TextClip, concatenate_videoclips
    )
    MOVIEPY_AVAILABLE = True
except ImportError:
    MOVIEPY_AVAILABLE = False

from .errors import RenderError


def ken_burns(image_path: Path, duration: float, zoom_from: float = 1.05, zoom_to: float = 1.12, pan: str = "auto"):
    """
    Apply Ken-Burns effect to an image with smooth zoom and pan.
    
    Args:
        image_path: Path to the image file
        duration: Duration of the clip in seconds
        zoom_from: Starting zoom factor (1.0 = no zoom, >1.0 = zoom in)
        zoom_to: Ending zoom factor
        pan: Pan direction ("auto", "left", "right", "up", "down")
    
    Returns:
        ImageClip with Ken-Burns effect
    """
    if not MOVIEPY_AVAILABLE:
        raise RenderError("moviepy is required for Ken-Burns effects")
    
    if not image_path.exists():
        raise RenderError(f"Image file not found: {image_path}")
    
    try:
        # Create base image clip
        clip = ImageClip(str(image_path), duration=duration)
        
        # Resize to ensure it's at least 1920x1080, maintaining aspect ratio
        clip = clip.resize(height=1080)
        
        # Ensure minimum width of 1920
        if clip.w < 1920:
            clip = clip.resize(width=1920)
        
        # Calculate pan offsets based on direction
        pan_x_start, pan_x_end, pan_y_start, pan_y_end = _calculate_pan_offsets(pan, zoom_from, zoom_to)
        
        # Apply Ken-Burns effect with smooth easing
        def make_frame(t):
            # Calculate progress (0 to 1)
            progress = t / duration
            
            # Apply smooth easeInOut cosine easing
            eased_progress = _ease_in_out_cosine(progress)
            
            # Calculate current zoom and pan
            current_zoom = zoom_from + (zoom_to - zoom_from) * eased_progress
            current_pan_x = pan_x_start + (pan_x_end - pan_x_start) * eased_progress
            current_pan_y = pan_y_start + (pan_y_end - pan_y_start) * eased_progress
            
            # Get frame
            frame = clip.get_frame(t)
            
            # Apply zoom and pan
            if current_zoom != 1.0:
                import cv2
                h, w = frame.shape[:2]
                new_h, new_w = int(h * current_zoom), int(w * current_zoom)
                frame = cv2.resize(frame, (new_w, new_h))
                
                # Crop to 1920x1080 with pan offset
                if new_h > 1080 or new_w > 1920:
                    # Calculate crop area with pan offset
                    crop_h, crop_w = 1080, 1920
                    
                    # Center crop with pan offset
                    start_y = max(0, int((new_h - crop_h) / 2 + current_pan_y * crop_h))
                    end_y = start_y + crop_h
                    start_x = max(0, int((new_w - crop_w) / 2 + current_pan_x * crop_w))
                    end_x = start_x + crop_w
                    
                    # Ensure we don't go out of bounds
                    start_y = max(0, min(start_y, new_h - crop_h))
                    end_y = start_y + crop_h
                    start_x = max(0, min(start_x, new_w - crop_w))
                    end_x = start_x + crop_w
                    
                    frame = frame[start_y:end_y, start_x:end_x]
                
                # Ensure final frame is exactly 1920x1080
                if frame.shape[:2] != (1080, 1920):
                    frame = cv2.resize(frame, (1920, 1080))
            
            return frame
        
        # Apply the effect
        clip = clip.fl(make_frame, apply_to=["mask"])
        
        return clip
        
    except Exception as e:
        raise RenderError(f"Failed to create Ken-Burns effect: {e}")


def _calculate_pan_offsets(pan: str, zoom_from: float, zoom_to: float) -> Tuple[float, float, float, float]:
    """
    Calculate pan offset values based on direction and zoom.
    
    Args:
        pan: Pan direction
        zoom_from: Starting zoom factor
        zoom_to: Ending zoom factor
    
    Returns:
        Tuple of (pan_x_start, pan_x_end, pan_y_start, pan_y_end)
    """
    # Pan offset as fraction of frame size
    max_pan_offset = 0.1  # 10% of frame
    
    if pan == "left":
        return (max_pan_offset, -max_pan_offset, 0.0, 0.0)
    elif pan == "right":
        return (-max_pan_offset, max_pan_offset, 0.0, 0.0)
    elif pan == "up":
        return (0.0, 0.0, max_pan_offset, -max_pan_offset)
    elif pan == "down":
        return (0.0, 0.0, -max_pan_offset, max_pan_offset)
    else:  # "auto" - use left for now
        return (max_pan_offset, -max_pan_offset, 0.0, 0.0)


def _ease_in_out_cosine(progress: float) -> float:
    """
    Cosine ease-in-out function for smooth motion.
    
    Args:
        progress: Progress from 0.0 to 1.0
    
    Returns:
        Eased progress from 0.0 to 1.0
    """
    return 0.5 * (1 - math.cos(math.pi * progress))


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
    
    try:
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
            
    except Exception as e:
        raise RenderError(f"Failed to compose video: {e}")


def _create_slide_clip_with_motion(slide_path: Path, segment: Dict[str, Any],
                                  config: Dict[str, Any]):
    """Create a slide clip with Ken-Burns motion effect."""
    
    duration = segment["duration"]
    kenburns = segment["kenburns"]
    
    # Extract Ken-Burns parameters
    zoom_from = kenburns.get("zoom_start", 1.05)
    zoom_to = kenburns.get("zoom_end", 1.12)
    pan = kenburns.get("pan", "auto")
    
    # Use the new ken_burns function
    return ken_burns(slide_path, duration, zoom_from, zoom_to, pan)


def _add_watermark(video_clip, watermark_path: Path, config: Dict[str, Any]):
    """Add watermark overlay to video."""
    
    try:
        styles = config.get("styles", {})
        logo_config = styles.get("logo", {})
        
        position = logo_config.get("position", "bottom-right")
        width = logo_config.get("width_px", 220)
        opacity = logo_config.get("opacity", 0.85)
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
        raise RenderError(f"Failed to add watermark: {e}")


def burn_captions_to_video(video_path: Path, captions: List[Dict[str, Any]],
                          output_path: Path, config: Dict[str, Any]) -> None:
    """Burn captions directly into video using FFmpeg."""
    
    try:
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
        
        import subprocess
        cmd = [
            "ffmpeg", "-y", "-i", str(video_path),
            "-vf", filter_str,
            "-c:a", "copy",
            "-c:v", "libx264",
            str(output_path)
        ]
        
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        
        # Clean up temp file
        Path(temp_srt_path).unlink(missing_ok=True)
        
    except subprocess.CalledProcessError as e:
        raise RenderError(f"Failed to burn captions: {e.stderr}")
    except Exception as e:
        raise RenderError(f"Failed to burn captions: {e}")


def _seconds_to_srt_time(seconds: float) -> str:
    """Convert seconds to SRT time format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millisecs = int((seconds % 1) * 1000)
    
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millisecs:03d}"