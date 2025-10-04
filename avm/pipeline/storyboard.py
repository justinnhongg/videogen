"""
Storyboard generation from transcripts.
"""

import json
import re
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import timedelta

from .errors import RenderError


def generate_storyboard(project_path: Path, config: Dict[str, Any], 
                       logger=None, project: str = "") -> Dict[str, Any]:
    """
    Generate storyboard JSON from transcripts.
    
    Args:
        project_path: Path to project directory
        config: Project configuration
        logger: Logger instance
        project: Project name for logging
    
    Returns:
        Storyboard JSON matching SPEC.md schema
    """
    
    if logger:
        logger.info("Generating storyboard from transcripts")
    
    # Try to read transcripts from captions_words.json first
    words_path = project_path / "build" / "captions_words.json"
    srt_path = project_path / "build" / "captions.srt"
    
    transcripts = []
    duration_sec = 0.0
    
    if words_path.exists():
        transcripts, duration_sec = _load_transcripts_from_words(words_path)
        if logger:
            logger.info(f"Loaded transcripts from words JSON: {len(transcripts)} segments")
    elif srt_path.exists():
        transcripts, duration_sec = _load_transcripts_from_srt(srt_path)
        if logger:
            logger.info(f"Loaded transcripts from SRT: {len(transcripts)} segments")
    else:
        raise RenderError(f"No transcripts found. Expected {words_path} or {srt_path}")
    
    # Generate beats by splitting transcripts evenly
    beats = _generate_beats_from_transcripts(transcripts, duration_sec, config)
    
    # Create storyboard JSON
    storyboard = {
        "meta": {
            "title": config.get("title", "Untitled"),
            "duration_sec": duration_sec,
            "fps": config.get("fps", 30)
        },
        "beats": beats
    }
    
    if logger:
        logger.info(f"Generated storyboard with {len(beats)} beats")
    
    return storyboard


def _load_transcripts_from_words(words_path: Path) -> tuple[List[Dict[str, Any]], float]:
    """
    Load transcripts from captions_words.json file.
    
    Args:
        words_path: Path to captions_words.json file
    
    Returns:
        Tuple of (transcript_segments, total_duration)
    """
    
    try:
        with open(words_path, 'r', encoding='utf-8') as f:
            words_data = json.load(f)
        
        if not isinstance(words_data, list):
            raise RenderError("Invalid words JSON format: expected array")
        
        if not words_data:
            raise RenderError("No words found in transcript")
        
        # Group words into segments (e.g., by sentence or time chunks)
        segments = []
        current_segment = []
        current_start = words_data[0]["start"]
        
        for word in words_data:
            # Start new segment if gap is too large (>2 seconds) or new sentence
            if (current_segment and 
                (word["start"] - current_segment[-1]["end"] > 2.0 or 
                 _is_sentence_end(current_segment[-1]["word"]))):
                
                if current_segment:
                    segments.append({
                        "text": " ".join([w["word"] for w in current_segment]),
                        "start": current_start,
                        "end": current_segment[-1]["end"]
                    })
                
                current_segment = [word]
                current_start = word["start"]
            else:
                current_segment.append(word)
        
        # Add final segment
        if current_segment:
            segments.append({
                "text": " ".join([w["word"] for w in current_segment]),
                "start": current_start,
                "end": current_segment[-1]["end"]
            })
        
        total_duration = max(segment["end"] for segment in segments)
        
        return segments, total_duration
        
    except Exception as e:
        raise RenderError(f"Failed to load words JSON: {e}")


def _load_transcripts_from_srt(srt_path: Path) -> tuple[List[Dict[str, Any]], float]:
    """
    Load transcripts from SRT file and convert to segments.
    
    Args:
        srt_path: Path to SRT file
    
    Returns:
        Tuple of (transcript_segments, total_duration)
    """
    
    try:
        from .captions import load_captions_srt
        
        captions = load_captions_srt(srt_path)
        
        segments = []
        for caption in captions:
            segments.append({
                "text": caption["content"],
                "start": caption["start"],
                "end": caption["end"]
            })
        
        total_duration = max(segment["end"] for segment in segments) if segments else 0.0
        
        return segments, total_duration
        
    except Exception as e:
        raise RenderError(f"Failed to load SRT file: {e}")


def _generate_beats_from_transcripts(transcripts: List[Dict[str, Any]], 
                                   duration_sec: float,
                                   config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Generate storyboard beats by splitting transcripts evenly.
    
    Args:
        transcripts: List of transcript segments
        duration_sec: Total duration in seconds
        config: Project configuration
    
    Returns:
        List of beat objects
    """
    
    # Get beat configuration
    beat_config = config.get("storyboard", {}).get("beats", {})
    num_beats = beat_config.get("count", 5)  # Default to 5 beats
    min_beat_duration = beat_config.get("min_duration_sec", 10.0)
    max_beat_duration = beat_config.get("max_duration_sec", 60.0)
    
    # Adjust number of beats if duration is too short
    if duration_sec < min_beat_duration * num_beats:
        num_beats = max(1, int(duration_sec / min_beat_duration))
    
    # Calculate beat durations
    beat_duration = duration_sec / num_beats
    
    # Clamp beat duration
    beat_duration = max(min_beat_duration, min(max_beat_duration, beat_duration))
    
    beats = []
    
    for i in range(num_beats):
        start_time = i * beat_duration
        end_time = min((i + 1) * beat_duration, duration_sec)
        
        # Find transcript segments that overlap with this beat
        beat_transcripts = []
        for transcript in transcripts:
            if (transcript["end"] > start_time and transcript["start"] < end_time):
                beat_transcripts.append(transcript["text"])
        
        # Generate beat title from transcripts
        title = _generate_beat_title(beat_transcripts, i + 1)
        
        # Generate bullet points from transcripts
        bullets = _generate_beat_bullets(beat_transcripts)
        
        beat = {
            "start": start_time,
            "end": end_time,
            "title": title,
            "bullets": bullets,
            "latex": [],  # Empty for now
            "overlays": []  # Empty for now
        }
        
        beats.append(beat)
    
    return beats


def _generate_beat_title(transcripts: List[str], beat_number: int) -> str:
    """
    Generate a title for a beat from its transcripts.
    
    Args:
        transcripts: List of transcript text segments
        beat_number: Beat number (1-indexed)
    
    Returns:
        Beat title
    """
    
    if not transcripts:
        return f"Beat {beat_number}"
    
    # Take the first meaningful sentence from transcripts
    combined_text = " ".join(transcripts)
    
    # Split into sentences and take the first substantial one
    sentences = re.split(r'[.!?]+', combined_text)
    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) > 10:  # Substantial sentence
            # Truncate if too long
            if len(sentence) > 60:
                sentence = sentence[:57] + "..."
            return sentence
    
    # Fallback to first part of combined text
    if len(combined_text) > 60:
        combined_text = combined_text[:57] + "..."
    
    return combined_text or f"Beat {beat_number}"


def _generate_beat_bullets(transcripts: List[str]) -> List[str]:
    """
    Generate bullet points for a beat from its transcripts.
    
    Args:
        transcripts: List of transcript text segments
    
    Returns:
        List of bullet point strings
    """
    
    if not transcripts:
        return ["No content available"]
    
    bullets = []
    combined_text = " ".join(transcripts)
    
    # Split into sentences
    sentences = re.split(r'[.!?]+', combined_text)
    
    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) > 15:  # Meaningful sentence
            bullets.append(sentence)
            
            # Limit to 3 bullets max
            if len(bullets) >= 3:
                break
    
    # If no substantial sentences, create bullets from word chunks
    if not bullets:
        words = combined_text.split()
        chunk_size = max(8, len(words) // 3)  # At least 8 words per chunk
        
        for i in range(0, min(len(words), chunk_size * 3), chunk_size):
            chunk = " ".join(words[i:i + chunk_size])
            if chunk.strip():
                bullets.append(chunk)
    
    return bullets[:3]  # Maximum 3 bullets


def _is_sentence_end(word: str) -> bool:
    """
    Check if a word likely ends a sentence.
    
    Args:
        word: Word to check
    
    Returns:
        True if word likely ends a sentence
    """
    
    # Remove punctuation for checking
    clean_word = word.strip().rstrip('.,!?;:')
    
    # Check if original word had sentence-ending punctuation
    return word.strip().endswith(('.', '!', '?')) and len(clean_word) > 0


def save_storyboard_json(storyboard: Dict[str, Any], output_path: Path) -> None:
    """
    Save storyboard to JSON file.
    
    Args:
        storyboard: Storyboard data
        output_path: Path to output JSON file
    """
    
    try:
        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(storyboard, f, indent=2, ensure_ascii=False)
            
    except Exception as e:
        raise RenderError(f"Failed to save storyboard JSON: {e}")


def load_storyboard_json(storyboard_path: Path) -> Dict[str, Any]:
    """
    Load storyboard from JSON file.
    
    Args:
        storyboard_path: Path to storyboard JSON file
    
    Returns:
        Storyboard data
    """
    
    try:
        with open(storyboard_path, 'r', encoding='utf-8') as f:
            return json.load(f)
            
    except Exception as e:
        raise RenderError(f"Failed to load storyboard JSON: {e}")


def validate_storyboard_schema(storyboard: Dict[str, Any]) -> bool:
    """
    Validate storyboard against the schema from SPEC.md.
    
    Args:
        storyboard: Storyboard data to validate
    
    Returns:
        True if valid, raises RenderError if invalid
    """
    
    # Check required top-level fields
    if "meta" not in storyboard:
        raise RenderError("Storyboard missing 'meta' field")
    
    if "beats" not in storyboard:
        raise RenderError("Storyboard missing 'beats' field")
    
    meta = storyboard["meta"]
    beats = storyboard["beats"]
    
    # Validate meta
    if not isinstance(meta, dict):
        raise RenderError("Storyboard 'meta' must be an object")
    
    if "title" not in meta:
        raise RenderError("Storyboard meta missing 'title' field")
    
    if "duration_sec" not in meta:
        raise RenderError("Storyboard meta missing 'duration_sec' field")
    
    if not isinstance(meta["title"], str):
        raise RenderError("Storyboard meta 'title' must be a string")
    
    if not isinstance(meta["duration_sec"], (int, float)) or meta["duration_sec"] < 0:
        raise RenderError("Storyboard meta 'duration_sec' must be a non-negative number")
    
    # Validate beats
    if not isinstance(beats, list):
        raise RenderError("Storyboard 'beats' must be an array")
    
    for i, beat in enumerate(beats):
        if not isinstance(beat, dict):
            raise RenderError(f"Beat {i} must be an object")
        
        # Check required beat fields
        required_fields = ["start", "end", "title", "bullets"]
        for field in required_fields:
            if field not in beat:
                raise RenderError(f"Beat {i} missing required field '{field}'")
        
        # Validate field types
        if not isinstance(beat["start"], (int, float)) or beat["start"] < 0:
            raise RenderError(f"Beat {i} 'start' must be a non-negative number")
        
        if not isinstance(beat["end"], (int, float)) or beat["end"] <= 0:
            raise RenderError(f"Beat {i} 'end' must be a positive number")
        
        if not isinstance(beat["title"], str):
            raise RenderError(f"Beat {i} 'title' must be a string")
        
        if not isinstance(beat["bullets"], list):
            raise RenderError(f"Beat {i} 'bullets' must be an array")
        
        for j, bullet in enumerate(beat["bullets"]):
            if not isinstance(bullet, str):
                raise RenderError(f"Beat {i} bullet {j} must be a string")
    
    return True
