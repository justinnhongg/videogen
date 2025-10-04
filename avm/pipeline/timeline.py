"""
Timeline planning and Ken-Burns motion generation.
"""

import json
import math
import re
from pathlib import Path
from typing import List, Dict, Any, Optional


def compute_slide_durations(total_sec: float, num_slides: int, method: str,
                          min_slide_sec: float, max_slide_sec: float,
                          token_counts: Optional[List[int]] = None) -> List[float]:
    """
    Compute slide durations based on method and constraints.
    
    Args:
        total_sec: Total duration in seconds
        num_slides: Number of slides
        method: "even" or "weighted"
        min_slide_sec: Minimum duration per slide
        max_slide_sec: Maximum duration per slide
        token_counts: Token counts per slide (for weighted method)
        
    Returns:
        List of durations for each slide
    """
    if num_slides <= 0:
        return []
    
    if method == "even":
        return _compute_even_durations(total_sec, num_slides, min_slide_sec, max_slide_sec)
    elif method == "weighted":
        return _compute_weighted_durations(total_sec, num_slides, min_slide_sec, max_slide_sec, token_counts)
    else:
        raise ValueError(f"Unknown method: {method}. Use 'even' or 'weighted'")


def _compute_even_durations(total_sec: float, num_slides: int,
                          min_slide_sec: float, max_slide_sec: float) -> List[float]:
    """Compute even durations with min/max clamping."""
    
    # Check if total duration is feasible with constraints
    min_total = min_slide_sec * num_slides
    max_total = max_slide_sec * num_slides
    
    if total_sec < min_total:
        # Total is too short - use minimum durations
        return [min_slide_sec] * num_slides
    elif total_sec > max_total:
        # Total is too long - use maximum durations
        return [max_slide_sec] * num_slides
    
    # Equal split
    base_duration = total_sec / num_slides
    
    # Check if equal split fits within constraints
    if min_slide_sec <= base_duration <= max_slide_sec:
        # Perfect case - equal distribution works
        return [base_duration] * num_slides
    
    # Need to clamp and adjust
    durations = []
    for _ in range(num_slides):
        duration = max(min_slide_sec, min(max_slide_sec, base_duration))
        durations.append(duration)
    
    # Adjust to make sum exact (iteratively)
    for _ in range(10):  # Prevent infinite loops
        current_total = sum(durations)
        difference = total_sec - current_total
        
        if abs(difference) < 0.001:  # Close enough
            break
            
        # Find slides that can be adjusted
        adjustable_slides = []
        for i, duration in enumerate(durations):
            if difference > 0 and duration < max_slide_sec:
                adjustable_slides.append(i)
            elif difference < 0 and duration > min_slide_sec:
                adjustable_slides.append(i)
        
        if not adjustable_slides:
            # Can't adjust further while maintaining constraints
            break
            
        # Distribute adjustment among adjustable slides
        adjustment_per_slide = difference / len(adjustable_slides)
        for i in adjustable_slides:
            new_duration = durations[i] + adjustment_per_slide
            durations[i] = max(min_slide_sec, min(max_slide_sec, new_duration))
    
    return durations


def _compute_weighted_durations(total_sec: float, num_slides: int,
                              min_slide_sec: float, max_slide_sec: float,
                              token_counts: Optional[List[int]]) -> List[float]:
    """Compute weighted durations based on token counts."""
    
    if not token_counts or len(token_counts) != num_slides:
        # Fallback to even distribution
        return _compute_even_durations(total_sec, num_slides, min_slide_sec, max_slide_sec)
    
    # Calculate weights
    total_tokens = sum(token_counts)
    if total_tokens == 0:
        return _compute_even_durations(total_sec, num_slides, min_slide_sec, max_slide_sec)
    
    # Check if total duration is feasible with constraints
    min_total = min_slide_sec * num_slides
    max_total = max_slide_sec * num_slides
    
    if total_sec < min_total:
        # Total is too short - use minimum durations
        return [min_slide_sec] * num_slides
    elif total_sec > max_total:
        # Total is too long - use maximum durations
        return [max_slide_sec] * num_slides
    
    # Initial weighted distribution
    durations = []
    for token_count in token_counts:
        weight = token_count / total_tokens
        duration = total_sec * weight
        durations.append(duration)
    
    # Apply min/max constraints
    durations = [max(min_slide_sec, min(max_slide_sec, d)) for d in durations]
    
    # Adjust to make sum exact (iteratively, similar to even method)
    for _ in range(10):  # Prevent infinite loops
        current_total = sum(durations)
        difference = total_sec - current_total
        
        if abs(difference) < 0.001:  # Close enough
            break
            
        # Find slides that can be adjusted
        adjustable_slides = []
        for i, duration in enumerate(durations):
            if difference > 0 and duration < max_slide_sec:
                adjustable_slides.append(i)
            elif difference < 0 and duration > min_slide_sec:
                adjustable_slides.append(i)
        
        if not adjustable_slides:
            # Can't adjust further while maintaining constraints
            break
            
        # Distribute adjustment among adjustable slides
        adjustment_per_slide = difference / len(adjustable_slides)
        for i in adjustable_slides:
            new_duration = durations[i] + adjustment_per_slide
            durations[i] = max(min_slide_sec, min(max_slide_sec, new_duration))
    
    return durations


def build_timeline(slide_count: int, total_sec: float, method: str, config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Build timeline with Ken-Burns motion parameters.
    
    Args:
        slide_count: Number of slides
        total_sec: Total duration in seconds
        method: Duration calculation method ("even" or "weighted")
        config: Configuration dictionary
        
    Returns:
        List of timeline segments with motion parameters
    """
    
    timeline_config = config.get("timeline", {})
    min_slide_sec = timeline_config.get("min_slide_sec", 5.0)
    max_slide_sec = timeline_config.get("max_slide_sec", 60.0)
    gap_sec = timeline_config.get("gap_sec", 0.0)
    
    # Calculate content duration (excluding gaps)
    total_gaps = gap_sec * max(0, slide_count - 1)
    content_duration = total_sec - total_gaps
    
    # Get token counts for weighted method
    token_counts = None
    if method == "weighted":
        # Try to get token counts from slides.md
        project_dir = config.get("project_dir")
        if project_dir:
            slides_md = Path(project_dir) / "slides.md"
            token_counts = _parse_slides_for_token_counts(slides_md)
    
    durations = compute_slide_durations(
        content_duration, slide_count, method,
        min_slide_sec, max_slide_sec, token_counts
    )
    
    # Build timeline segments with gaps
    segments = []
    current_time = 0.0
    
    for i, duration in enumerate(durations):
        segment = {
            "index": i,
            "start": current_time,
            "end": current_time + duration,
            "zoom_from": 1.05,
            "zoom_to": 1.12,
            "pan": _get_pan_direction(i)
        }
        segments.append(segment)
        current_time += duration + gap_sec  # Add gap after each slide (except last)
    
    return segments


def _get_pan_direction(slide_index: int) -> str:
    """Get pan direction for slide, alternating per slide."""
    directions = ["left", "right", "up", "down"]
    return directions[slide_index % len(directions)]


def _parse_slides_for_token_counts(slides_md: Path) -> Optional[List[int]]:
    """
    Parse slides.md to extract token counts for weighted duration calculation.
    
    Args:
        slides_md: Path to slides markdown file
        
    Returns:
        List of token counts per slide, or None if parsing fails
    """
    if not slides_md.exists():
        return None
    
    try:
        with open(slides_md, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Split on ## headings (top-level)
        sections = re.split(r'^##\s+(.+)$', content, flags=re.MULTILINE)
        
        token_counts = []
        
        # Handle first section (before any ##)
        if sections[0].strip():
            first_section = sections[0].strip()
            # Remove title line and count tokens in content
            content_without_title = re.sub(r'^#\s+.+$', '', first_section, flags=re.MULTILINE).strip()
            if content_without_title:
                # Simple token count (words)
                tokens = len(re.findall(r'\S+', content_without_title))
                token_counts.append(tokens)
        
        # Process remaining sections (## title + content pairs)
        for i in range(1, len(sections), 2):
            if i + 1 < len(sections):
                content = sections[i + 1].strip()
                if content:
                    # Simple token count (words)
                    tokens = len(re.findall(r'\S+', content))
                    token_counts.append(tokens)
        
        return token_counts if token_counts else None
        
    except Exception:
        return None


def save_timeline_to_json(timeline_segments: List[Dict[str, Any]], output_path: Path) -> None:
    """
    Save timeline to build/timeline.json.
    
    Args:
        timeline_segments: List of timeline segments
        output_path: Path to timeline.json file
    """
    
    timeline_data = {
        "version": "1.0.0",
        "total_duration": timeline_segments[-1]["end"] if timeline_segments else 0.0,
        "slide_count": len(timeline_segments),
        "segments": timeline_segments
    }
    
    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(timeline_data, f, indent=2)


def load_timeline_from_json(timeline_path: Path) -> Dict[str, Any]:
    """
    Load timeline from build/timeline.json.
    
    Args:
        timeline_path: Path to timeline.json file
        
    Returns:
        Timeline data dictionary
    """
    if not timeline_path.exists():
        raise FileNotFoundError(f"Timeline file not found: {timeline_path}")
    
    with open(timeline_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_slide_durations_from_timeline(captions_words_json: Path, slide_images: List[Path],
                                    method: str = "weighted", min_slide_sec: float = 5.0,
                                    max_slide_sec: float = 60.0, gap_sec: float = 0.25) -> List[float]:
    """
    Get slide durations from word timing data.
    
    Args:
        captions_words_json: Path to word-level captions JSON
        slide_images: List of slide image paths
        method: Duration calculation method
        min_slide_sec: Minimum slide duration
        max_slide_sec: Maximum slide duration
        gap_sec: Gap between slides
        
    Returns:
        List of durations for each slide
    """
    
    if not captions_words_json.exists():
        # Fallback to simple timeline
        return create_simple_timeline(slide_images, min_sec=min_slide_sec)
    
    try:
        with open(captions_words_json, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        words = data.get("words", [])
        total_duration = data.get("duration", 0)
        
        if not words or total_duration <= 0:
            return create_simple_timeline(slide_images, min_sec=min_slide_sec)
        
        # Calculate total time available (accounting for gaps)
        num_slides = len(slide_images)
        total_gap_time = gap_sec * (num_slides - 1)
        available_time = total_duration - total_gap_time
        
        if available_time <= 0:
            return create_simple_timeline(slide_images, min_sec=min_slide_sec)
        
        # Distribute words across slides
        words_per_slide = len(words) / num_slides
        
        if method == "weighted":
            # Calculate token counts per slide
            token_counts = []
            for i in range(num_slides):
                start_word = int(i * words_per_slide)
                end_word = int((i + 1) * words_per_slide)
                slide_words = words[start_word:end_word]
                token_counts.append(len(slide_words))
            
            durations = compute_slide_durations(
                available_time, num_slides, "weighted",
                min_slide_sec, max_slide_sec, token_counts
            )
        else:
            durations = compute_slide_durations(
                available_time, num_slides, "even",
                min_slide_sec, max_slide_sec
            )
        
        return durations
        
    except (json.JSONDecodeError, KeyError, IOError):
        # Fallback to simple timeline
        return create_simple_timeline(slide_images, min_sec=min_slide_sec)


def create_simple_timeline(slide_images: List[Path], min_sec: float = 5.0) -> List[float]:
    """
    Create a simple timeline with equal durations.
    
    Args:
        slide_images: List of slide image paths
        min_sec: Minimum duration per slide
        
    Returns:
        List of durations for each slide
    """
    return [min_sec] * len(slide_images)


def generate_timeline(captions_words_json: Path, slides_md: Path, timeline_json: Path,
                     method: str = "weighted", min_slide_sec: float = 5.0,
                     max_slide_sec: float = 60.0, gap_sec: float = 0.25,
                     config: Optional[Dict[str, Any]] = None) -> None:
    """
    Generate complete timeline and save to JSON.
    
    Args:
        captions_words_json: Path to word-level captions JSON
        slides_md: Path to slides markdown file
        timeline_json: Path to output timeline JSON
        method: Duration calculation method
        min_slide_sec: Minimum slide duration
        max_slide_sec: Maximum slide duration
        gap_sec: Gap between slides
        config: Configuration dictionary
    """
    
    # Get slide count from slides.md
    slide_count = _count_slides_in_markdown(slides_md)
    
    # Get total duration from captions
    total_duration = _get_audio_duration_from_captions(captions_words_json)
    
    if total_duration <= 0:
        # Fallback to simple timeline
        durations = create_simple_timeline([Path(f"slide_{i+1}.png") for i in range(slide_count)], min_sec=min_slide_sec)
        timeline_segments = _create_timeline_segments_from_durations(durations, config or {})
    else:
        # Build timeline with motion parameters
        timeline_segments = build_timeline(slide_count, total_duration, method, config or {})
    
    # Save to JSON
    save_timeline_to_json(timeline_segments, timeline_json)


def _count_slides_in_markdown(slides_md: Path) -> int:
    """Count slides in markdown file."""
    if not slides_md.exists():
        return 1  # Fallback
    
    try:
        with open(slides_md, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Count ## headings (top-level slides)
        h2_matches = re.findall(r'^##\s+', content, re.MULTILINE)
        slide_count = len(h2_matches)
        
        # If no ## headings, treat as single slide
        if slide_count == 0:
            slide_count = 1
        
        return slide_count
        
    except (IOError, UnicodeDecodeError):
        return 1  # Fallback


def _get_audio_duration_from_captions(captions_words_json: Path) -> float:
    """Get audio duration from captions JSON."""
    if not captions_words_json.exists():
        return 0.0
    
    try:
        with open(captions_words_json, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        return data.get("duration", 0.0)
        
    except (json.JSONDecodeError, KeyError, IOError):
        return 0.0


def _create_timeline_segments_from_durations(durations: List[float], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Create timeline segments from durations."""
    segments = []
    current_time = 0.0
    
    for i, duration in enumerate(durations):
        segment = {
            "index": i,
            "start": current_time,
            "end": current_time + duration,
            "zoom_from": 1.05,
            "zoom_to": 1.12,
            "pan": _get_pan_direction(i)
        }
        segments.append(segment)
        current_time += duration
    
    return segments


# Legacy functions for backward compatibility
def create_timeline(audio_duration: float, slides_count: int, 
                   captions_words: List[Dict[str, Any]],
                   config: Dict[str, Any], logger=None, project: str = "") -> Dict[str, Any]:
    """Legacy function for backward compatibility."""
    
    timeline_config = config.get("timeline", {})
    method = timeline_config.get("method", "weighted")
    min_slide_sec = timeline_config.get("min_slide_sec", 5.0)
    max_slide_sec = timeline_config.get("max_slide_sec", 60.0)
    
    # Convert captions_words to token_counts
    token_counts = None
    if captions_words and method == "weighted":
        # Simple token counting (words per slide)
        words_per_slide = len(captions_words) / slides_count
        token_counts = [int(words_per_slide)] * slides_count
    
    durations = compute_slide_durations(
        audio_duration, slides_count, method,
        min_slide_sec, max_slide_sec, token_counts
    )
    
    # Create segments with Ken-Burns motion
    segments = []
    current_time = 0.0
    
    for i, duration in enumerate(durations):
        segment = {
            "slide_num": i + 1,
            "start": current_time,
            "end": current_time + duration,
            "duration": duration,
            "kenburns": {
                "zoom_start": 1.05,
                "zoom_end": 1.12,
                "pan": _get_pan_direction(i)
            }
        }
        segments.append(segment)
        current_time += duration
    
    timeline = {
        "total_duration": current_time,
        "audio_duration": audio_duration,
        "slides_count": slides_count,
        "method": method,
        "segments": segments
    }
    
    return timeline


def save_timeline(timeline: Dict[str, Any], output_path: Path) -> None:
    """Legacy function for backward compatibility."""
    # Convert legacy format to new format
    segments = []
    for segment in timeline.get("segments", []):
        new_segment = {
            "index": segment.get("slide_num", 1) - 1,
            "start": segment.get("start", 0.0),
            "end": segment.get("end", 0.0),
            "zoom_from": segment.get("kenburns", {}).get("zoom_start", 1.05),
            "zoom_to": segment.get("kenburns", {}).get("zoom_end", 1.12),
            "pan": segment.get("kenburns", {}).get("pan", "left")
        }
        segments.append(new_segment)
    
    save_timeline_to_json(segments, output_path)


def load_timeline(timeline_path: Path) -> Dict[str, Any]:
    """Legacy function for backward compatibility."""
    return load_timeline_from_json(timeline_path)