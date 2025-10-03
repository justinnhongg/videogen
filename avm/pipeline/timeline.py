"""
Timeline planning and Ken-Burns motion generation.
"""

import json
import math
from pathlib import Path
from typing import List, Dict, Any, Optional


def create_timeline(audio_duration: float, slides_count: int, 
                   captions_words: List[Dict[str, Any]],
                   config: Dict[str, Any], logger=None, project: str = "") -> Dict[str, Any]:
    """
    Create timeline with slide durations and Ken-Burns motion.
    
    Args:
        audio_duration: Total audio duration in seconds
        slides_count: Number of slides
        captions_words: Word-level caption data
        config: Project configuration
        logger: Logger instance
        project: Project name for logging
        
    Returns:
        Timeline dictionary with slide segments and motion data
    """
    
    timeline_config = config.get("timeline", {})
    method = timeline_config.get("method", "weighted")
    min_slide_sec = timeline_config.get("min_slide_sec", 5.0)
    max_slide_sec = timeline_config.get("max_slide_sec", 60.0)
    gap_sec = timeline_config.get("gap_sec", 0.25)
    
    if method == "weighted":
        durations = _calculate_weighted_durations(
            audio_duration, slides_count, captions_words,
            min_slide_sec, max_slide_sec, gap_sec
        )
    else:
        durations = _calculate_even_durations(
            audio_duration, slides_count, min_slide_sec, max_slide_sec, gap_sec
        )
    
    # Create slide segments with Ken-Burns motion
    segments = []
    current_time = 0.0
    
    for i, duration in enumerate(durations):
        segment = {
            "slide_num": i + 1,
            "start": current_time,
            "end": current_time + duration,
            "duration": duration,
            "kenburns": _generate_kenburns_motion(config, i)
        }
        segments.append(segment)
        current_time += duration + gap_sec
    
    timeline = {
        "total_duration": current_time - gap_sec,  # Remove final gap
        "audio_duration": audio_duration,
        "slides_count": slides_count,
        "method": method,
        "segments": segments
    }
    
    return timeline


def _calculate_weighted_durations(audio_duration: float, slides_count: int,
                                 captions_words: List[Dict[str, Any]],
                                 min_slide_sec: float, max_slide_sec: float,
                                 gap_sec: float) -> List[float]:
    """Calculate slide durations based on word count weighting."""
    
    if not captions_words:
        # Fallback to even distribution
        return _calculate_even_durations(
            audio_duration, slides_count, min_slide_sec, max_slide_sec, gap_sec
        )
    
    # Distribute words across slides
    words_per_slide = len(captions_words) / slides_count
    
    durations = []
    total_gap_time = gap_sec * (slides_count - 1)
    available_time = audio_duration - total_gap_time
    
    for i in range(slides_count):
        start_word = int(i * words_per_slide)
        end_word = int((i + 1) * words_per_slide)
        
        # Count words in this slide
        slide_words = captions_words[start_word:end_word]
        word_count = len(slide_words)
        
        # Calculate duration based on word count
        if word_count > 0:
            # Use word timing to estimate duration
            if slide_words:
                slide_start = slide_words[0]["start"]
                slide_end = slide_words[-1]["end"]
                estimated_duration = slide_end - slide_start
            else:
                estimated_duration = available_time / slides_count
        else:
            estimated_duration = available_time / slides_count
        
        # Clamp to min/max
        duration = max(min_slide_sec, min(max_slide_sec, estimated_duration))
        durations.append(duration)
    
    # Normalize to fit total audio duration
    total_allocated = sum(durations) + total_gap_time
    if total_allocated != audio_duration:
        scale_factor = (audio_duration - total_gap_time) / (total_allocated - total_gap_time)
        durations = [d * scale_factor for d in durations]
    
    return durations


def _calculate_even_durations(audio_duration: float, slides_count: int,
                             min_slide_sec: float, max_slide_sec: float,
                             gap_sec: float) -> List[float]:
    """Calculate even slide durations."""
    
    total_gap_time = gap_sec * (slides_count - 1)
    available_time = audio_duration - total_gap_time
    
    base_duration = available_time / slides_count
    
    # Apply min/max constraints
    durations = []
    for _ in range(slides_count):
        duration = max(min_slide_sec, min(max_slide_sec, base_duration))
        durations.append(duration)
    
    # Normalize if needed
    total_allocated = sum(durations) + total_gap_time
    if total_allocated != audio_duration:
        scale_factor = (audio_duration - total_gap_time) / (total_allocated - total_gap_time)
        durations = [d * scale_factor for d in durations]
    
    return durations


def _generate_kenburns_motion(config: Dict[str, Any], slide_index: int) -> Dict[str, Any]:
    """Generate Ken-Burns motion parameters for a slide."""
    
    kenburns_config = config.get("kenburns", {})
    zoom_start = kenburns_config.get("zoom_start", 1.05)
    zoom_end = kenburns_config.get("zoom_end", 1.12)
    pan_direction = kenburns_config.get("pan", "auto")
    easing = kenburns_config.get("easing", "easeInOutSine")
    
    # Determine pan direction
    if pan_direction == "auto":
        # Cycle through directions
        directions = ["left", "right", "up", "down"]
        pan_direction = directions[slide_index % len(directions)]
    
    # Calculate pan offsets (percentage of image)
    pan_amount = 0.02  # 2% of image size
    
    pan_x = 0.0
    pan_y = 0.0
    
    if pan_direction == "left":
        pan_x = -pan_amount
    elif pan_direction == "right":
        pan_x = pan_amount
    elif pan_direction == "up":
        pan_y = -pan_amount
    elif pan_direction == "down":
        pan_y = pan_amount
    
    return {
        "zoom_start": zoom_start,
        "zoom_end": zoom_end,
        "pan_x_start": -pan_x,
        "pan_x_end": pan_x,
        "pan_y_start": -pan_y,
        "pan_y_end": pan_y,
        "easing": easing
    }


def save_timeline(timeline: Dict[str, Any], output_path: Path) -> None:
    """Save timeline to JSON file."""
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(timeline, f, indent=2)


def load_timeline(timeline_path: Path) -> Dict[str, Any]:
    """Load timeline from JSON file."""
    if not timeline_path.exists():
        raise FileNotFoundError(f"Timeline file not found: {timeline_path}")
    
    with open(timeline_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_slide_at_time(timeline: Dict[str, Any], time_sec: float) -> Optional[Dict[str, Any]]:
    """Get slide segment at a specific time."""
    for segment in timeline["segments"]:
        if segment["start"] <= time_sec <= segment["end"]:
            return segment
    return None


def get_caption_segments_for_slide(timeline: Dict[str, Any], slide_num: int,
                                  captions_words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Get caption words that belong to a specific slide."""
    segment = None
    for seg in timeline["segments"]:
        if seg["slide_num"] == slide_num:
            segment = seg
            break
    
    if not segment:
        return []
    
    # Find words that overlap with slide timing
    slide_words = []
    for word in captions_words:
        word_start = word["start"]
        word_end = word["end"]
        
        # Check for overlap
        if (word_start < segment["end"] and word_end > segment["start"]):
            slide_words.append(word)
    
    return slide_words
