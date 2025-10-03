"""
Test timeline generation and Ken-Burns motion.
"""

import pytest
from pathlib import Path
import sys

# Add the avm package to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from avm.pipeline.timeline import (
    create_timeline, _calculate_weighted_durations, 
    _calculate_even_durations, _generate_kenburns_motion
)


def test_calculate_even_durations():
    """Test even duration calculation."""
    durations = _calculate_even_durations(
        audio_duration=30.0,
        slides_count=3,
        min_slide_sec=5.0,
        max_slide_sec=20.0,
        gap_sec=0.25
    )
    
    # Should have 3 durations
    assert len(durations) == 3
    
    # Each duration should be 10 seconds (30/3)
    expected_duration = 10.0
    for duration in durations:
        assert abs(duration - expected_duration) < 0.1


def test_calculate_weighted_durations():
    """Test weighted duration calculation."""
    # Mock word data with varying lengths
    captions_words = [
        {"start": 0.0, "end": 2.0, "word": "word1"},
        {"start": 2.0, "end": 4.0, "word": "word2"},
        {"start": 4.0, "end": 6.0, "word": "word3"},
        {"start": 6.0, "end": 8.0, "word": "word4"},
        {"start": 8.0, "end": 10.0, "word": "word5"},
    ]
    
    durations = _calculate_weighted_durations(
        audio_duration=30.0,
        slides_count=2,
        captions_words=captions_words,
        min_slide_sec=5.0,
        max_slide_sec=20.0,
        gap_sec=0.25
    )
    
    # Should have 2 durations
    assert len(durations) == 2
    
    # Total duration should be approximately correct
    total_gap_time = 0.25 * (2 - 1)  # gaps between slides
    total_duration = sum(durations) + total_gap_time
    assert abs(total_duration - 30.0) < 1.0


def test_generate_kenburns_motion():
    """Test Ken-Burns motion generation."""
    config = {
        "kenburns": {
            "zoom_start": 1.05,
            "zoom_end": 1.12,
            "pan": "auto"
        }
    }
    
    # Test first slide
    motion1 = _generate_kenburns_motion(config, 0)
    assert motion1["zoom_start"] == 1.05
    assert motion1["zoom_end"] == 1.12
    assert "pan_x_start" in motion1
    assert "pan_x_end" in motion1
    
    # Test second slide (should have different pan direction)
    motion2 = _generate_kenburns_motion(config, 1)
    assert motion2["zoom_start"] == 1.05
    assert motion2["zoom_end"] == 1.12
    
    # Pan directions should be different
    assert (motion1["pan_x_start"] != motion2["pan_x_start"] or 
            motion1["pan_y_start"] != motion2["pan_y_start"])


def test_create_timeline():
    """Test full timeline creation."""
    config = {
        "timeline": {
            "method": "even",
            "min_slide_sec": 5.0,
            "max_slide_sec": 60.0,
            "gap_sec": 0.25
        }
    }
    
    timeline = create_timeline(
        audio_duration=30.0,
        slides_count=3,
        captions_words=[],
        config=config
    )
    
    # Check timeline structure
    assert "total_duration" in timeline
    assert "audio_duration" in timeline
    assert "slides_count" in timeline
    assert "segments" in timeline
    
    # Check segments
    assert len(timeline["segments"]) == 3
    
    for i, segment in enumerate(timeline["segments"]):
        assert segment["slide_num"] == i + 1
        assert "start" in segment
        assert "end" in segment
        assert "duration" in segment
        assert "kenburns" in segment
        
        # Check timing is reasonable
        assert segment["duration"] >= 5.0
        assert segment["duration"] <= 60.0
