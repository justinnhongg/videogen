"""
Video assembly with Ken-Burns effects and video stitching.
"""

import subprocess
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


def ken_burns(image_path: Path, duration: float, zoom: float = 1.10) -> ImageClip:
    """
    Apply Ken-Burns effect to an image.
    
    Args:
        image_path: Path to the image file
        duration: Duration of the clip in seconds
        zoom: Zoom factor (1.0 = no zoom, >1.0 = zoom in)
    
    Returns:
        ImageClip with Ken-Burns effect
    """
    if not MOVIEPY_AVAILABLE:
        raise RenderError("moviepy is required for Ken-Burns effects")
    
    if not image_path.exists():
        raise RenderError(f"Image file not found: {image_path}")
    
    # Create base image clip
    clip = ImageClip(str(image_path), duration=duration)
    
    # Resize to ensure it's at least 1920x1080
    clip = clip.resize(height=1080)
    
    # Apply Ken-Burns zoom effect
    def make_frame(t):
        # Calculate zoom progress (0 to 1)
        progress = t / duration
        
        # Apply smooth easing (ease-in-out)
        eased_progress = _ease_in_out_sine(progress)
        
        # Calculate current zoom level
        current_zoom = 1.0 + (zoom - 1.0) * eased_progress
        
        # Get frame and apply zoom
        frame = clip.get_frame(t)
        
        if current_zoom != 1.0:
            import cv2
            h, w = frame.shape[:2]
            new_h, new_w = int(h * current_zoom), int(w * current_zoom)
            frame = cv2.resize(frame, (new_w, new_h))
            
            # Crop to maintain aspect ratio and center
            if new_h > h or new_w > w:
                start_y = max(0, int((new_h - h) / 2))
                end_y = start_y + h
                start_x = max(0, int((new_w - w) / 2))
                end_x = start_x + w
                
                frame = frame[start_y:end_y, start_x:end_x]
        
        return frame
    
    # Apply the zoom effect
    clip = clip.fl(make_frame, apply_to=["mask"])
    
    return clip


def overlay_watermark(video_clip, watermark_path: Path, position: str = "top-right",
                     padding: int = 24) -> CompositeVideoClip:
    """
    Overlay watermark on video clip.
    
    Args:
        video_clip: The video clip to overlay on
        watermark_path: Path to watermark image
        position: Position of watermark (top-right, top-left, bottom-right, bottom-left)
        padding: Padding from edges in pixels
    
    Returns:
        CompositeVideoClip with watermark overlay
    """
    if not watermark_path.exists():
        return video_clip
    
    try:
        # Create watermark clip
        watermark = ImageClip(str(watermark_path))
        
        # Resize watermark (max width 200px, maintain aspect ratio)
        watermark = watermark.resize(width=200)
        watermark = watermark.set_duration(video_clip.duration)
        watermark = watermark.set_opacity(0.8)
        
        # Position watermark
        if position == "top-right":
            watermark = watermark.set_position((
                video_clip.w - watermark.w - padding,
                padding
            ))
        elif position == "top-left":
            watermark = watermark.set_position((padding, padding))
        elif position == "bottom-right":
            watermark = watermark.set_position((
                video_clip.w - watermark.w - padding,
                video_clip.h - watermark.h - padding
            ))
        elif position == "bottom-left":
            watermark = watermark.set_position((
                padding,
                video_clip.h - watermark.h - padding
            ))
        else:
            # Default to top-right
            watermark = watermark.set_position((
                video_clip.w - watermark.w - padding,
                padding
            ))
        
        # Composite with main video
        return CompositeVideoClip([video_clip, watermark])
        
    except Exception as e:
        raise RenderError(f"Failed to overlay watermark: {e}")


def concatenate_with_intro_outro(main_clip, intro_path: Optional[Path] = None,
                                outro_path: Optional[Path] = None) -> VideoFileClip:
    """
    Concatenate intro, main video, and outro.
    
    Args:
        main_clip: The main video clip
        intro_path: Path to intro video (optional)
        outro_path: Path to outro video (optional)
    
    Returns:
        Concatenated video clip
    """
    clips = []
    
    # Add intro if provided
    if intro_path and intro_path.exists():
        try:
            intro_clip = VideoFileClip(str(intro_path))
            clips.append(intro_clip)
        except Exception as e:
            raise RenderError(f"Failed to load intro video: {e}")
    
    # Add main clip
    clips.append(main_clip)
    
    # Add outro if provided
    if outro_path and outro_path.exists():
        try:
            outro_clip = VideoFileClip(str(outro_path))
            clips.append(outro_clip)
        except Exception as e:
            raise RenderError(f"Failed to load outro video: {e}")
    
    if len(clips) == 1:
        return clips[0]
    
    try:
        return concatenate_videoclips(clips)
    except Exception as e:
        raise RenderError(f"Failed to concatenate videos: {e}")


def assemble_video(slide_images: List[Path], durations: List[float],
                  watermark_path: Optional[Path] = None,
                  intro_path: Optional[Path] = None,
                  outro_path: Optional[Path] = None,
                  output_path: Path = None,
                  fps: int = 30, zoom: float = 1.10,
                  logger=None, project: str = "") -> Path:
    """
    Assemble video from slide images with Ken-Burns effects.
    
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
        # Create Ken-Burns clips for each slide
        slide_clips = []
        
        for i, (image_path, duration) in enumerate(zip(slide_images, durations)):
            if image_path.exists():
                clip = ken_burns(image_path, duration, zoom)
                slide_clips.append(clip)
            else:
                raise RenderError(f"Slide image not found: {image_path}")
        
        # Concatenate slide clips
        main_video = concatenate_videoclips(slide_clips)
        
        # Add watermark if provided
        if watermark_path:
            main_video = overlay_watermark(main_video, watermark_path)
        
        # Add intro/outro if provided
        final_video = concatenate_with_intro_outro(
            main_video, intro_path, outro_path
        )
        
        # Write video
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
        
        return output_path


def _ease_in_out_sine(progress: float) -> float:
    """Ease-in-out sine function for smooth motion."""
    import math
    return -(math.cos(math.pi * progress) - 1) / 2


def get_slide_durations_from_timeline(timeline_path: Path) -> List[float]:
    """
    Extract slide durations from timeline JSON.
    
    Args:
        timeline_path: Path to timeline JSON file
    
    Returns:
        List of slide durations in seconds
    """
    import json
    
    if not timeline_path.exists():
        raise RenderError(f"Timeline file not found: {timeline_path}")
    
    try:
        with open(timeline_path, 'r') as f:
            timeline = json.load(f)
        
        durations = []
        for segment in timeline.get("segments", []):
            durations.append(segment.get("duration", 5.0))
        
        return durations
        
    except (json.JSONDecodeError, KeyError) as e:
        raise RenderError(f"Failed to parse timeline: {e}")


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
