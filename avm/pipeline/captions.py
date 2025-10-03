"""
Caption handling and SRT processing.
"""

import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

try:
    import srt
    SRT_AVAILABLE = True
except ImportError:
    SRT_AVAILABLE = False

from .errors import RenderError


def load_captions_srt(srt_path: Path) -> List[Dict[str, Any]]:
    """Load captions from SRT file."""
    if not SRT_AVAILABLE:
        raise RenderError("srt library is required for caption processing")
    
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


def load_captions_words(words_path: Path) -> List[Dict[str, Any]]:
    """Load word-level captions from JSON file."""
    import json
    
    if not words_path.exists():
        raise RenderError(f"Words file not found: {words_path}")
    
    try:
        with open(words_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        return data.get("words", [])
        
    except Exception as e:
        raise RenderError(f"Failed to load words file: {e}")


def wrap_caption_text(text: str, max_chars: int = 52, max_lines: int = 2) -> str:
    """Wrap caption text to fit within character and line limits."""
    
    # Clean up text
    text = re.sub(r'\s+', ' ', text.strip())
    
    if len(text) <= max_chars:
        return text
    
    # Split into words
    words = text.split()
    lines = []
    current_line = ""
    
    for word in words:
        # Check if adding this word would exceed max_chars
        test_line = current_line + (" " if current_line else "") + word
        
        if len(test_line) <= max_chars:
            current_line = test_line
        else:
            # Save current line and start new one
            if current_line:
                lines.append(current_line)
                current_line = word
            else:
                # Single word longer than max_chars, split it
                lines.append(word[:max_chars])
                current_line = word[max_chars:]
    
    # Add final line
    if current_line:
        lines.append(current_line)
    
    # Limit to max_lines
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        # Add ellipsis to last line if truncated
        if len(lines) == max_lines and len(words) > len(" ".join(lines).split()):
            lines[-1] = lines[-1].rstrip() + "..."
    
    return "\n".join(lines)


def adjust_caption_timing(captions: List[Dict[str, Any]], 
                         slide_transitions: List[float]) -> List[Dict[str, Any]]:
    """Adjust caption timing to avoid overlap with slide transitions."""
    
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
    """Generate overlay specification for burning captions into video."""
    
    caption_config = styles.get("caption", {})
    safe_bottom_pct = caption_config.get("safe_bottom_pct", 12)
    font_size = caption_config.get("font_size", 40)
    stroke_px = caption_config.get("stroke_px", 3)
    max_lines = caption_config.get("max_lines", 2)
    
    # Wrap text
    wrapped_text = wrap_caption_text(caption["content"], max_lines=max_lines)
    
    # Calculate position (bottom safe area)
    text_color = styles.get("text_color", "#FFFFFF")
    stroke_color = "#000000"  # Black stroke for contrast
    
    # Position calculation
    y_pos = f"h-h*{safe_bottom_pct}/100"
    
    return {
        "text": wrapped_text,
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


def create_caption_overlay_filter(captions: List[Dict[str, Any]], 
                                 styles: Dict[str, Any]) -> str:
    """Create FFmpeg subtitle filter for burning captions."""
    
    if not captions:
        return ""
    
    # Create temporary SRT file content
    srt_content = ""
    for i, caption in enumerate(captions, 1):
        start_time = _seconds_to_srt_time(caption["start"])
        end_time = _seconds_to_srt_time(caption["end"])
        text = wrap_caption_text(caption["content"])
        
        srt_content += f"{i}\n{start_time} --> {end_time}\n{text}\n\n"
    
    # Write temporary SRT file
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.srt', delete=False) as f:
        f.write(srt_content)
        temp_srt_path = f.name
    
    # Create subtitle filter
    caption_config = styles.get("caption", {})
    font_size = caption_config.get("font_size", 40)
    font_color = styles.get("text_color", "#FFFFFF")
    stroke_color = "#000000"
    stroke_width = caption_config.get("stroke_px", 3)
    
    filter_str = (
        f"subtitles={temp_srt_path}:"
        f"force_style='FontSize={font_size},"
        f"PrimaryColour={font_color.replace('#', '&H')},"
        f"OutlineColour={stroke_color.replace('#', '&H')},"
        f"Outline={stroke_width},"
        f"Alignment=2'"  # Bottom center
    )
    
    return filter_str, temp_srt_path


def _seconds_to_srt_time(seconds: float) -> str:
    """Convert seconds to SRT time format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millisecs = int((seconds % 1) * 1000)
    
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millisecs:03d}"


def attach_soft_captions(video_path: Path, srt_path: Path, 
                        output_path: Path) -> None:
    """Attach SRT file as soft subtitles to video."""
    
    import subprocess
    
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(srt_path),
        "-c", "copy",
        "-c:s", "mov_text",
        "-metadata:s:s:0", "language=eng",
        str(output_path)
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise RenderError(f"Failed to attach soft captions: {e}")
