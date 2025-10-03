"""
Test caption processing and SRT handling.
"""

import pytest
from pathlib import Path
import sys
import tempfile

# Add the avm package to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from avm.pipeline.captions import (
    wrap_caption_text, adjust_caption_timing,
    generate_caption_overlay_spec
)


def test_wrap_caption_text():
    """Test caption text wrapping."""
    # Short text should not be wrapped
    short_text = "Hello world"
    wrapped = wrap_caption_text(short_text, max_chars=52)
    assert wrapped == short_text
    
    # Long text should be wrapped
    long_text = "This is a very long caption that should definitely be wrapped because it exceeds the maximum character limit"
    wrapped = wrap_caption_text(long_text, max_chars=52)
    
    # Should be split into lines
    lines = wrapped.split('\n')
    assert len(lines) <= 2  # Max 2 lines
    
    # Each line should not exceed max_chars
    for line in lines:
        assert len(line) <= 52
    
    # Should preserve words (no word splitting)
    assert "very long" in wrapped


def test_wrap_caption_text_max_lines():
    """Test caption text wrapping with line limits."""
    # Create text that would exceed max lines
    text = " ".join([f"word{i}" for i in range(100)])
    
    wrapped = wrap_caption_text(text, max_chars=10, max_lines=2)
    lines = wrapped.split('\n')
    
    assert len(lines) <= 2
    assert wrapped.endswith("...")  # Should have ellipsis if truncated


def test_adjust_caption_timing():
    """Test caption timing adjustment around transitions."""
    captions = [
        {"start": 0.0, "end": 2.0, "content": "First caption"},
        {"start": 1.5, "end": 3.5, "content": "Overlapping caption"},
        {"start": 3.0, "end": 5.0, "content": "Third caption"},
    ]
    
    transitions = [2.0, 4.0]  # Transition times
    
    adjusted = adjust_caption_timing(captions, transitions)
    
    # Should have fewer captions due to conflicts
    assert len(adjusted) <= len(captions)
    
    # Check no caption overlaps with transitions (within margin)
    for caption in adjusted:
        for transition in transitions:
            assert not (caption["start"] < transition + 0.5 and 
                       caption["end"] > transition - 0.5)


def test_generate_caption_overlay_spec():
    """Test caption overlay specification generation."""
    caption = {
        "start": 10.0,
        "end": 15.0,
        "content": "This is a test caption"
    }
    
    styles = {
        "text_color": "#FFFFFF",
        "caption": {
            "font_size": 40,
            "stroke_px": 3,
            "safe_bottom_pct": 12,
            "max_lines": 2
        }
    }
    
    spec = generate_caption_overlay_spec(caption, styles)
    
    # Check required fields
    assert "text" in spec
    assert "start_time" in spec
    assert "end_time" in spec
    assert "font_size" in spec
    assert "font_color" in spec
    assert "stroke_color" in spec
    assert "stroke_width" in spec
    
    # Check values
    assert spec["start_time"] == 10.0
    assert spec["end_time"] == 15.0
    assert spec["font_size"] == 40
    assert spec["font_color"] == "#FFFFFF"
    assert spec["stroke_width"] == 3
    
    # Check positioning
    assert "x" in spec
    assert "y" in spec
    assert spec["x"] == "w/2"  # Center horizontally


def test_wrap_caption_edge_cases():
    """Test edge cases in caption wrapping."""
    # Empty text
    assert wrap_caption_text("") == ""
    
    # Single very long word
    long_word = "supercalifragilisticexpialidocious"
    wrapped = wrap_caption_text(long_word, max_chars=20)
    assert len(wrapped) <= 20
    
    # Text with extra whitespace
    messy_text = "  Hello    world   with   spaces  "
    wrapped = wrap_caption_text(messy_text, max_chars=20)
    # Should clean up whitespace
    assert "  " not in wrapped  # No double spaces
    
    # Text with line breaks
    multiline_text = "Line 1\nLine 2\nLine 3"
    wrapped = wrap_caption_text(multiline_text, max_chars=10, max_lines=2)
    lines = wrapped.split('\n')
    assert len(lines) <= 2
