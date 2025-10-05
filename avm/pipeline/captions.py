"""
Caption handling and SRT processing.
"""

import re
import tempfile
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

try:
    import srt
    SRT_AVAILABLE = True
except ImportError:
    SRT_AVAILABLE = False

from .errors import RenderError


def load_captions_srt(srt_path: Path) -> List[Dict[str, Any]]:
    """
    Load captions from SRT file using python-srt.
    
    Args:
        srt_path: Path to SRT file
    
    Returns:
        List of caption dictionaries with index, start, end, content
    """
    if not SRT_AVAILABLE:
        raise RenderError("python-srt library is required for caption processing")
    
    if not srt_path.exists():
        raise RenderError(f"SRT file not found: {srt_path}")
    
    try:
        with open(srt_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        subs = list(srt.parse(content))
        
        # Convert to our format
        captions = []
        for sub in subs:
            captions.append({
                "index": sub.index,
                "start": sub.start.total_seconds(),
                "end": sub.end.total_seconds(),
                "content": sub.content.strip()
            })
        
        return captions
        
    except Exception as e:
        raise RenderError(f"Failed to load SRT file: {e}")


def save_captions_srt(captions: List[Dict[str, Any]], srt_path: Path) -> None:
    """
    Save captions to SRT file using python-srt.
    
    Args:
        captions: List of caption dictionaries
        srt_path: Path to output SRT file
    """
    if not SRT_AVAILABLE:
        raise RenderError("python-srt library is required for caption processing")
    
    try:
        # Convert to srt.Subtitle objects
        subs = []
        for caption in captions:
            sub = srt.Subtitle(
                index=caption.get("index", 0),
                start=srt.timedelta(seconds=caption["start"]),
                end=srt.timedelta(seconds=caption["end"]),
                content=caption["content"]
            )
            subs.append(sub)
        
        # Write SRT file
        with open(srt_path, 'w', encoding='utf-8') as f:
            f.write(srt.compose(subs))
            
    except Exception as e:
        raise RenderError(f"Failed to save SRT file: {e}")


def wrap_captions_by_pixel_width(text: str, font_size: int, max_width_px: int) -> List[str]:
    """
    Wrap captions by pixel width using greedy break on spaces.
    
    Args:
        text: Text to wrap
        font_size: Font size in pixels
        max_width_px: Maximum width in pixels
    
    Returns:
        List of wrapped lines (max 2 lines)
    """
    # Approximate character width based on font size
    # This is a rough estimate - actual width varies by font and character
    approx_char_width = font_size * 0.6  # Rough estimate: 60% of font size
    max_chars_per_line = int(max_width_px / approx_char_width)
    
    # Clean up text
    text = re.sub(r'\s+', ' ', text.strip())
    
    if len(text) <= max_chars_per_line:
        return [text]
    
    # Split into words
    words = text.split()
    lines = []
    current_line = ""
    
    for word in words:
        # Check if adding this word would exceed max_chars_per_line
        test_line = current_line + (" " if current_line else "") + word
        
        if len(test_line) <= max_chars_per_line:
            current_line = test_line
        else:
            # Save current line and start new one
            if current_line:
                lines.append(current_line)
                current_line = word
            else:
                # Single word longer than max_chars_per_line, split it
                lines.append(word[:max_chars_per_line])
                current_line = word[max_chars_per_line:]
    
    # Add final line
    if current_line:
        lines.append(current_line)
    
    # Enforce ≤2 lines limit
    if len(lines) > 2:
        lines = lines[:2]
        # Truncate second line and append "..." if needed
        if len(lines[1]) > max_chars_per_line - 3:
            lines[1] = lines[1][:max_chars_per_line - 3] + "..."
    
    return lines


def position_captions_above_safe_bottom(captions: List[Dict[str, Any]], 
                                      styles: Dict[str, Any],
                                      watermark_config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Position captions above safe bottom area, avoiding watermark collision.
    
    Args:
        captions: List of caption dictionaries
        styles: Styles configuration
        watermark_config: Optional watermark configuration for collision avoidance
    
    Returns:
        List of positioned captions
    """
    caption_config = styles.get("caption", {})
    safe_bottom_pct = caption_config.get("safe_bottom_pct", 12)
    max_lines = caption_config.get("max_lines", 2)
    
    # Check for watermark collision
    if watermark_config and watermark_config.get("enabled", False):
        watermark_position = watermark_config.get("position", "bottom-right")
        if watermark_position.startswith("bottom"):
            # Increase bottom margin to avoid watermark
            safe_bottom_pct = max(safe_bottom_pct, 20)  # Minimum 20% from bottom
    
    positioned_captions = []
    
    for caption in captions:
        # Wrap text to max_lines
        wrapped_text = wrap_captions_by_pixel_width(
            [caption["content"]], 
            caption_config.get("font_size", 40),
            1200  # Approximate width for 1920px video
        )
        
        positioned_caption = caption.copy()
        positioned_caption["content"] = "\n".join(wrapped_text)
        positioned_caption["safe_bottom_pct"] = safe_bottom_pct
        positioned_caption["max_lines"] = max_lines
        
        positioned_captions.append(positioned_caption)
    
    return positioned_captions


def burn_captions(video_in: Path, srt: Path, video_out: Path, 
                 font: str, size: int, outline: int, safe_bottom_pct: int, 
                 styles: Optional[Dict[str, Any]] = None) -> None:
    """
    Burn captions into video using ffmpeg subtitles filter with force_style.
    
    Args:
        video_in: Input video file
        srt: SRT file with captions
        video_out: Output video file
        font: Font name (fallback if not in styles)
        size: Font size in pixels
        outline: Outline width in pixels
        safe_bottom_pct: Safe bottom percentage (e.g., 12% of 1080)
        styles: Styles configuration for watermark collision detection
    """
    
    if not video_in.exists():
        raise RenderError(f"Input video not found: {video_in}")
    
    if not srt.exists():
        raise RenderError(f"SRT file not found: {srt}")
    
    # Calculate MarginV from safe_bottom_pct of 1080
    margin_v = int(1080 * safe_bottom_pct / 100)
    
    # Increase MarginV by ~5% if watermark uses bottom corner
    if styles:
        watermark_config = styles.get("watermark", {})
        if watermark_config.get("enabled", False):
            watermark_position = watermark_config.get("position", "bottom-right")
            if watermark_position in ["bottom-right", "bottom-left"]:
                margin_v = int(margin_v * 1.05)
    
    # Get font from styles if available, otherwise use fallback
    caption_font = font
    if styles:
        caption_config = styles.get("caption", {})
        caption_font = caption_config.get("font", font)
    
    # Create subtitle filter with force_style
    filter_str = (
        f"subtitles={srt}:"
        f"force_style='FontName={caption_font},FontSize={size},"
        f"PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
        f"Outline={outline},BorderStyle=1,"
        f"Alignment=2,MarginV={margin_v}'"
    )
    
    cmd = [
        "ffmpeg", "-y", "-i", str(video_in),
        "-vf", filter_str,
        "-c:a", "copy",
        "-c:v", "libx264",
        str(video_out)
    ]
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        stderr_output = e.stderr if e.stderr else "No stderr captured"
        raise RenderError(f"Failed to burn captions: {stderr_output}")
    except Exception as e:
        raise RenderError(f"Caption burning error: {e}")


def attach_soft_subs(video_in: Path, srt: Path, video_out: Path) -> None:
    """
    Attach soft subtitles using mov_text or keep as sidecar .srt when incompatible.
    
    Args:
        video_in: Input video file
        srt: SRT file with captions
        video_out: Output video file
    """
    
    if not video_in.exists():
        raise RenderError(f"Input video not found: {video_in}")
    
    if not srt.exists():
        raise RenderError(f"SRT file not found: {srt}")
    
    # Try to attach mov_text subtitles
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_in),
        "-i", str(srt),
        "-c", "copy",
        "-c:s", "mov_text",
        "-metadata:s:s:0", "language=eng",
        str(video_out)
    ]
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        # Success - mov_text subtitles attached
        
    except subprocess.CalledProcessError as e:
        # mov_text failed, emit sidecar SRT
        try:
            cmd_copy = [
                "ffmpeg", "-y",
                "-i", str(video_in),
                "-c", "copy",
                str(video_out)
            ]
            result = subprocess.run(cmd_copy, check=True, capture_output=True, text=True)
            
            # Copy SRT file as sidecar
            sidecar_srt = video_out.with_suffix('.srt')
            import shutil
            shutil.copy2(srt, sidecar_srt)
            
        except subprocess.CalledProcessError as copy_error:
            stderr_output = copy_error.stderr if copy_error.stderr else "No stderr captured"
            raise RenderError(f"Failed to attach soft subtitles and create sidecar: {stderr_output}")
        except Exception as copy_error:
            raise RenderError(f"Failed to create sidecar SRT: {copy_error}")


def create_caption_overlay_filter(captions: List[Dict[str, Any]], 
                                 styles: Dict[str, Any],
                                 watermark_config: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
    """
    Create FFmpeg subtitle filter for burning captions.
    
    Args:
        captions: List of caption dictionaries
        styles: Styles configuration
        watermark_config: Optional watermark configuration
    
    Returns:
        Tuple of (filter_string, temp_srt_path)
    """
    
    if not captions:
        return "", ""
    
    # Position captions to avoid watermark collision
    positioned_captions = position_captions_above_safe_bottom(captions, styles, watermark_config)
    
    # Create temporary SRT file content
    srt_content = ""
    for i, caption in enumerate(positioned_captions, 1):
        start_time = _seconds_to_srt_time(caption["start"])
        end_time = _seconds_to_srt_time(caption["end"])
        text = caption["content"]
        
        srt_content += f"{i}\n{start_time} --> {end_time}\n{text}\n\n"
    
    # Write temporary SRT file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.srt', delete=False, encoding='utf-8') as f:
        f.write(srt_content)
        temp_srt_path = f.name
    
    # Create subtitle filter
    caption_config = styles.get("caption", {})
    font_size = caption_config.get("font_size", 40)
    font_color = styles.get("text_color", "#FFFFFF")
    stroke_color = "#000000"
    stroke_width = caption_config.get("stroke_px", 3)
    safe_bottom_pct = caption_config.get("safe_bottom_pct", 12)
    
    # Adjust for watermark collision
    if watermark_config and watermark_config.get("enabled", False):
        watermark_position = watermark_config.get("position", "bottom-right")
        if watermark_position.startswith("bottom"):
            safe_bottom_pct = max(safe_bottom_pct, 20)
    
    filter_str = (
        f"subtitles={temp_srt_path}:"
        f"force_style='FontSize={font_size},"
        f"PrimaryColour={font_color.replace('#', '&H')},"
        f"OutlineColour={stroke_color.replace('#', '&H')},"
        f"Outline={stroke_width},"
        f"Alignment=2,MarginV={safe_bottom_pct}'"  # Bottom center with margin
    )
    
    return filter_str, temp_srt_path


def _seconds_to_srt_time(seconds: float) -> str:
    """
    Convert seconds to SRT time format (HH:MM:SS,mmm).
    
    Args:
        seconds: Time in seconds (negative values will be clamped to 0)
    
    Returns:
        SRT time format string
    """
    # Clamp negative values to 0
    seconds = max(0.0, seconds)
    
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millisecs = int((seconds % 1) * 1000)
    
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millisecs:03d}"


def load_captions_words(words_path: Path) -> List[Dict[str, Any]]:
    """
    Load word-level captions from JSON file.
    
    Args:
        words_path: Path to words JSON file
    
    Returns:
        List of word dictionaries
    """
    import json
    
    if not words_path.exists():
        raise RenderError(f"Words file not found: {words_path}")
    
    try:
        with open(words_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        return data.get("words", [])
        
    except Exception as e:
        raise RenderError(f"Failed to load words file: {e}")


def adjust_caption_timing(captions: List[Dict[str, Any]], 
                         slide_transitions: List[float]) -> List[Dict[str, Any]]:
    """
    Adjust caption timing to avoid overlap with slide transitions.
    
    Args:
        captions: List of caption dictionaries
        slide_transitions: List of transition times
    
    Returns:
        List of adjusted captions
    """
    
    adjusted = []
    transition_margin = 0.5  # 0.5 second margin around transitions
    
    for caption in captions:
        start = caption["start"]
        end = caption["end"]
        
        # Check for conflicts with transitions
        for transition_time in slide_transitions:
            # If caption overlaps with transition, adjust timing
            if start < transition_time + transition_margin and end > transition_time - transition_margin:
                # Move caption to avoid transition
                if start < transition_time:
                    # Caption starts before transition, end it early
                    end = min(end, transition_time - transition_margin)
                else:
                    # Caption starts after transition, delay start
                    start = max(start, transition_time + transition_margin)
                
                # Ensure valid timing
                if start >= end:
                    start = end - 0.1
        
        if start < end:  # Only add valid captions
            adjusted_caption = caption.copy()
            adjusted_caption["start"] = start
            adjusted_caption["end"] = end
            adjusted.append(adjusted_caption)
    
    return adjusted


def generate_caption_overlay_spec(caption: Dict[str, Any], 
                                 styles: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate overlay specification for burning captions into video.
    
    Args:
        caption: Caption dictionary
        styles: Styles configuration
    
    Returns:
        Overlay specification dictionary
    """
    
    caption_config = styles.get("caption", {})
    safe_bottom_pct = caption_config.get("safe_bottom_pct", 12)
    font_size = caption_config.get("font_size", 40)
    stroke_px = caption_config.get("stroke_px", 3)
    max_lines = caption_config.get("max_lines", 2)
    
    # Wrap text
    wrapped_text = wrap_captions_by_pixel_width(
        [caption["content"]], 
        font_size,
        1200  # Approximate width for 1920px video
    )
    
    # Calculate position (bottom safe area)
    text_color = styles.get("text_color", "#FFFFFF")
    stroke_color = "#000000"  # Black stroke for contrast
    
    # Position calculation
    y_pos = f"h-h*{safe_bottom_pct}/100"
    
    return {
        "text": "\n".join(wrapped_text),
        "start_time": caption["start"],
        "end_time": caption["end"],
        "font_size": font_size,
        "font_color": text_color,
        "stroke_color": stroke_color,
        "stroke_width": stroke_px,
        "x": "w/2",  # Center horizontally
        "y": y_pos,  # Bottom safe area
        "alignment": "center"
    }


# Legacy functions for backward compatibility
def wrap_caption_text(text: str, max_chars: int = 52, max_lines: int = 2) -> str:
    """
    Legacy function for backward compatibility.
    
    Args:
        text: Text to wrap
        max_chars: Maximum characters per line
        max_lines: Maximum number of lines
    
    Returns:
        Wrapped text
    """
    wrapped_lines = wrap_captions_by_pixel_width([text], 40, max_chars * 8)  # Rough pixel conversion
    return "\n".join(wrapped_lines)


def attach_soft_captions(video_path: Path, srt_path: Path, 
                        output_path: Path) -> None:
    """
    Legacy function for backward compatibility.
    
    Args:
        video_path: Input video file
        srt_path: SRT file with captions
        output_path: Output video file
    """
    attach_soft_subs(video_path, srt_path, output_path)