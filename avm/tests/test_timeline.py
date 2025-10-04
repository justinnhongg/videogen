"""
Test timeline generation and Ken-Burns motion.
"""

import pytest
from pathlib import Path
import sys

# Add the avm package to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from avm.pipeline.timeline import (
    compute_slide_durations, build_timeline, _get_pan_direction
)


def test_compute_slide_durations_even():
    """Test even duration calculation with sum and clamp assertions."""
    total_sec = 30.0
    num_slides = 3
    min_slide_sec = 5.0
    max_slide_sec = 20.0
    
    durations = compute_slide_durations(
        total_sec=total_sec,
        num_slides=num_slides,
        method="even",
        min_slide_sec=min_slide_sec,
        max_slide_sec=max_slide_sec
    )
    
    # Should have correct number of durations
    assert len(durations) == num_slides
    
    # Each duration should be clamped within bounds
    for duration in durations:
        assert duration >= min_slide_sec
        assert duration <= max_slide_sec
    
    # Durations should sum to total_sec within 1ms precision
    total_duration = sum(durations)
    assert abs(total_duration - total_sec) < 0.001, f"Sum {total_duration} != {total_sec}"
    
    # For even distribution with no clamping needed, should be equal
    expected_even = total_sec / num_slides
    if min_slide_sec <= expected_even <= max_slide_sec:
        for duration in durations:
            assert abs(duration - expected_even) < 0.001


def test_compute_slide_durations_even_with_clamping():
    """Test even duration calculation with clamping."""
    total_sec = 60.0
    num_slides = 2
    min_slide_sec = 5.0
    max_slide_sec = 20.0
    
    durations = compute_slide_durations(
        total_sec=total_sec,
        num_slides=num_slides,
        method="even",
        min_slide_sec=min_slide_sec,
        max_slide_sec=max_slide_sec
    )
    
    # Should have correct number of durations
    assert len(durations) == num_slides
    
    # Each duration should be clamped
    for duration in durations:
        assert duration >= min_slide_sec
        assert duration <= max_slide_sec
    
    # Since constraints prevent exact sum (60s with max 20s per slide = max 40s total),
    # we expect the algorithm to return the best possible approximation (40s total)
    total_duration = sum(durations)
    expected_max_total = max_slide_sec * num_slides
    assert abs(total_duration - expected_max_total) < 0.001, f"Sum {total_duration} should be close to max possible {expected_max_total}"
    
    # Since even split (30s each) exceeds max_slide_sec (20s), should be clamped to 20s
    expected_clamped = max_slide_sec
    for duration in durations:
        assert abs(duration - expected_clamped) < 0.001


def test_compute_slide_durations_weighted():
    """Test weighted duration calculation with token counts."""
    total_sec = 30.0
    num_slides = 3
    min_slide_sec = 3.0
    max_slide_sec = 15.0
    
    # Mock token counts for different slide lengths
    token_counts = [10, 20, 30]  # Slide 1: short, Slide 2: medium, Slide 3: long
    
    durations = compute_slide_durations(
        total_sec=total_sec,
        num_slides=num_slides,
        method="weighted",
        min_slide_sec=min_slide_sec,
        max_slide_sec=max_slide_sec,
        token_counts=token_counts
    )
    
    # Should have correct number of durations
    assert len(durations) == num_slides
    
    # Each duration should be clamped within bounds
    for duration in durations:
        assert duration >= min_slide_sec
        assert duration <= max_slide_sec
    
    # Durations should sum to total_sec within 1ms precision
    total_duration = sum(durations)
    assert abs(total_duration - total_sec) < 0.001, f"Sum {total_duration} != {total_sec}"
    
    # Slide with more tokens should get more time (if not clamped)
    # Slide 3 (30 tokens) should have >= Slide 2 (20 tokens) >= Slide 1 (10 tokens)
    assert durations[2] >= durations[1], "Slide 3 should have >= duration than Slide 2"
    assert durations[1] >= durations[0], "Slide 2 should have >= duration than Slide 1"


def test_compute_slide_durations_weighted_with_clamping():
    """Test weighted duration calculation with heavy clamping."""
    total_sec = 100.0
    num_slides = 2
    min_slide_sec = 10.0
    max_slide_sec = 20.0
    
    # Very different token counts
    token_counts = [5, 95]  # Very uneven distribution
    
    durations = compute_slide_durations(
        total_sec=total_sec,
        num_slides=num_slides,
        method="weighted",
        min_slide_sec=min_slide_sec,
        max_slide_sec=max_slide_sec,
        token_counts=token_counts
    )
    
    # Should have correct number of durations
    assert len(durations) == num_slides
    
    # Each duration should be clamped
    for duration in durations:
        assert duration >= min_slide_sec
        assert duration <= max_slide_sec
    
    # Since constraints prevent exact sum (100s with max 20s per slide = max 40s total),
    # we expect the algorithm to return the best possible approximation (40s total)
    total_duration = sum(durations)
    expected_max_total = max_slide_sec * num_slides
    assert abs(total_duration - expected_max_total) < 0.001, f"Sum {total_duration} should be close to max possible {expected_max_total}"
    
    # Both should be at max due to heavy clamping
    for duration in durations:
        assert abs(duration - max_slide_sec) < 0.001


def test_compute_slide_durations_edge_cases():
    """Test edge cases in duration calculation."""
    # Single slide
    durations = compute_slide_durations(
        total_sec=15.0,
        num_slides=1,
        method="even",
        min_slide_sec=5.0,
        max_slide_sec=20.0
    )
    assert len(durations) == 1
    assert abs(durations[0] - 15.0) < 0.001
    
    # Very short total duration
    durations = compute_slide_durations(
        total_sec=2.0,
        num_slides=2,
        method="even",
        min_slide_sec=1.0,
        max_slide_sec=10.0
    )
    assert len(durations) == 2
    assert all(d >= 1.0 for d in durations)
    assert abs(sum(durations) - 2.0) < 0.001
    
    # Zero tokens in weighted mode
    durations = compute_slide_durations(
        total_sec=10.0,
        num_slides=2,
        method="weighted",
        min_slide_sec=2.0,
        max_slide_sec=8.0,
        token_counts=[0, 0]
    )
    assert len(durations) == 2
    assert abs(sum(durations) - 10.0) < 0.001


def test_build_timeline():
    """Test full timeline creation."""
    slide_count = 3
    total_sec = 30.0
    method = "even"
    config = {
        "timeline": {
            "min_slide_sec": 5.0,
            "max_slide_sec": 20.0,
            "gap_sec": 0.5,
            "kenburns": {
                "zoom_from": 1.05,
                "zoom_to": 1.12
            }
        }
    }
    
    timeline = build_timeline(slide_count, total_sec, method, config)
    
    # Should have correct number of segments
    assert len(timeline) == slide_count
    
    # Check each segment structure
    for i, segment in enumerate(timeline):
        assert segment["index"] == i
        assert "start" in segment
        assert "end" in segment
        assert "zoom_from" in segment
        assert "zoom_to" in segment
        assert "pan" in segment
        
        # Check timing bounds
        duration = segment["end"] - segment["start"]
        assert duration >= config["timeline"]["min_slide_sec"]
        assert duration <= config["timeline"]["max_slide_sec"]
    
    # Check total duration (including gaps)
    total_content_duration = sum(seg["end"] - seg["start"] for seg in timeline)
    expected_gaps = config["timeline"]["gap_sec"] * (slide_count - 1)
    total_with_gaps = total_content_duration + expected_gaps
    assert abs(total_with_gaps - total_sec) < 0.001  # Should match total_sec within 1ms precision
    
    # Check pan direction alternation
    pan_directions = [seg["pan"] for seg in timeline]
    if len(pan_directions) > 1:
        # Should alternate between different directions
        assert len(set(pan_directions)) > 1, "Pan directions should alternate"


# Note: _parse_slides_for_token_counts function not available in timeline.py


def test_get_pan_direction():
    """Test pan direction generation."""
    # Test alternating directions
    directions = [_get_pan_direction(i) for i in range(6)]
    
    # Should have variety in directions
    unique_directions = set(directions)
    assert len(unique_directions) > 1, "Should have multiple pan directions"
    
    # Should be valid directions
    valid_directions = {"left", "right", "up", "down"}
    assert all(d in valid_directions for d in directions)


# Note: _ease_in_out_cubic function not available in timeline.py


def test_timeline_with_gaps():
    """Test timeline generation with gaps between slides."""
    slide_count = 2
    total_sec = 20.0
    method = "even"
    config = {
        "timeline": {
            "min_slide_sec": 5.0,
            "max_slide_sec": 15.0,
            "gap_sec": 2.0,  # 2 second gaps
            "kenburns": {
                "zoom_from": 1.05,
                "zoom_to": 1.12
            }
        }
    }
    
    timeline = build_timeline(slide_count, total_sec, method, config)
    
    # Should have correct number of segments
    assert len(timeline) == slide_count
    
    # Check that segments don't overlap (accounting for gaps)
    for i in range(len(timeline) - 1):
        current_end = timeline[i]["end"]
        next_start = timeline[i + 1]["start"]
        gap = next_start - current_end
        assert gap >= config["timeline"]["gap_sec"], f"Gap {gap} should be >= {config['timeline']['gap_sec']}"
    
    # Total content duration should account for gaps
    content_duration = sum(seg["end"] - seg["start"] for seg in timeline)
    expected_gaps = config["timeline"]["gap_sec"] * (slide_count - 1)
    total_with_gaps = content_duration + expected_gaps
    
    # Should be close to total_sec
    assert abs(total_with_gaps - total_sec) < 1.0