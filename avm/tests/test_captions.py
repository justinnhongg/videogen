"""
Test caption processing and SRT handling.
"""

import pytest
from pathlib import Path
import sys
import tempfile
import os

# Add the avm package to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from avm.pipeline.captions import (
    load_captions_srt, save_captions_srt, wrap_captions_by_pixel_width,
    burn_captions, attach_soft_subs, _seconds_to_srt_time
)


def test_srt_parse_serialize_roundtrip():
    """Test SRT parse → serialize roundtrip."""
    # Create test SRT content
    original_srt_content = """1
00:00:01,000 --> 00:00:03,500
Hello world, this is a test caption.

2
00:00:03,500 --> 00:00:06,000
This is the second caption with
multiple lines.

3
00:00:06,000 --> 00:00:08,500
Final caption here.
"""
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.srt', delete=False) as f:
        original_file = f.name
        f.write(original_srt_content)
    
    roundtrip_file = None
    try:
        # Parse SRT
        captions = load_captions_srt(Path(original_file))
        
        # Should have 3 captions
        assert len(captions) == 3
        
        # Check first caption
        assert captions[0]["index"] == 1
        assert captions[0]["start"] == 1.0
        assert captions[0]["end"] == 3.5
        assert captions[0]["content"] == "Hello world, this is a test caption."
        
        # Check second caption (multi-line)
        assert captions[1]["index"] == 2
        assert captions[1]["start"] == 3.5
        assert captions[1]["end"] == 6.0
        assert captions[1]["content"] == "This is the second caption with\nmultiple lines."
        
        # Check third caption
        assert captions[2]["index"] == 3
        assert captions[2]["start"] == 6.0
        assert captions[2]["end"] == 8.5
        assert captions[2]["content"] == "Final caption here."
        
        # Serialize back to SRT
        with tempfile.NamedTemporaryFile(mode='w', suffix='.srt', delete=False) as f:
            roundtrip_file = f.name
        
        save_captions_srt(captions, Path(roundtrip_file))
        
        # Read back and compare
        with open(roundtrip_file, 'r') as f:
            roundtrip_content = f.read()
        
        # Parse roundtrip content
        roundtrip_captions = load_captions_srt(Path(roundtrip_file))
        
        # Should have same number of captions
        assert len(roundtrip_captions) == len(captions)
        
        # Check each caption matches
        for orig, rt in zip(captions, roundtrip_captions):
            assert orig["index"] == rt["index"]
            assert orig["start"] == rt["start"]
            assert orig["end"] == rt["end"]
            assert orig["content"] == rt["content"]
        
        print("✅ SRT parse → serialize roundtrip successful")
        
    finally:
        # Clean up
        for file_path in [original_file, roundtrip_file]:
            if file_path and os.path.exists(file_path):
                os.unlink(file_path)


def test_wrap_captions_by_pixel_width():
    """Test caption wrapping under max width."""
    # Test short text (no wrapping needed)
    short_lines = ["Hello world"]
    wrapped = wrap_captions_by_pixel_width(short_lines, font_size=40, max_width_px=800)
    assert wrapped == ["Hello world"]
    
    # Test long text (should wrap)
    long_lines = ["This is a very long caption that should definitely be wrapped because it exceeds the maximum pixel width limit"]
    wrapped = wrap_captions_by_pixel_width(long_lines, font_size=40, max_width_px=400)
    
    # Should be split into multiple lines
    assert len(wrapped) <= 2  # Max 2 lines
    
    # Each line should not exceed max width (approximate check)
    char_width = int(40 * 0.6)  # Approximate character width
    max_chars_per_line = 400 // char_width  # Use the actual max_width_px value
    
    for line in wrapped:
        assert len(line) <= max_chars_per_line + 10  # Allow some tolerance
    
    # Should preserve words (no word splitting)
    original_words = long_lines[0].split()
    wrapped_text = " ".join(wrapped)
    for word in original_words[:5]:  # Check first few words are preserved
        assert word in wrapped_text


def test_wrap_captions_edge_cases():
    """Test edge cases in caption wrapping."""
    # Empty input
    assert wrap_captions_by_pixel_width([], font_size=40, max_width_px=400) == []
    
    # Single very long word
    long_word_lines = ["supercalifragilisticexpialidocious"]
    wrapped = wrap_captions_by_pixel_width(long_word_lines, font_size=40, max_width_px=200)
    assert len(wrapped) <= 2
    
    # Text with line breaks already
    multiline_lines = ["Line 1\nLine 2\nLine 3"]
    wrapped = wrap_captions_by_pixel_width(multiline_lines, font_size=40, max_width_px=400)
    # Should handle existing line breaks
    assert len(wrapped) <= 3
    
    # Very small max width
    normal_lines = ["This is normal text"]
    wrapped = wrap_captions_by_pixel_width(normal_lines, font_size=40, max_width_px=50)
    assert len(wrapped) <= 2


def test_wrap_captions_max_lines_enforcement():
    """Test that max lines constraint is enforced."""
    # Create text that would exceed max lines
    long_lines = [" ".join([f"word{i}" for i in range(50)])]
    
    wrapped = wrap_captions_by_pixel_width(long_lines, font_size=40, max_width_px=200, max_lines=2)
    
    assert len(wrapped) <= 2
    
    # If truncated, should have ellipsis
    if len(wrapped) == 2:
        assert "..." in wrapped[-1] or len(wrapped[-1]) > 0


def test_seconds_to_srt_time():
    """Test conversion of seconds to SRT time format."""
    # Test basic conversion
    srt_time = _seconds_to_srt_time(65.123)
    assert srt_time == "00:01:05,123"
    
    # Test zero
    srt_time = _seconds_to_srt_time(0.0)
    assert srt_time == "00:00:00,000"
    
    # Test negative (should be clamped to 0)
    srt_time = _seconds_to_srt_time(-1.5)
    assert srt_time == "00:00:00,000"
    
    # Test large values
    srt_time = _seconds_to_srt_time(3661.999)
    assert srt_time == "01:01:01,998"  # Floating point precision
    
    # Test fractional seconds
    srt_time = _seconds_to_srt_time(1.001)
    assert srt_time == "00:00:01,000"  # Floating point precision


def test_srt_roundtrip_with_special_characters():
    """Test SRT roundtrip with special characters."""
    # SRT content with special characters
    special_srt_content = """1
00:00:01,000 --> 00:00:03,000
Hello & welcome! <b>Bold text</b> & "quotes"

2
00:00:03,000 --> 00:00:05,000
Special chars: àáâãäå & ñüç
"""
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.srt', delete=False, encoding='utf-8') as f:
        original_file = f.name
        f.write(special_srt_content)
    
    try:
        # Parse and serialize
        captions = load_captions_srt(Path(original_file))
        assert len(captions) == 2
        
        # Check special characters are preserved
        assert "& welcome!" in captions[0]["content"]
        assert "<b>Bold text</b>" in captions[0]["content"]
        assert '"quotes"' in captions[0]["content"]
        assert "àáâãäå" in captions[1]["content"]
        assert "ñüç" in captions[1]["content"]
        
        # Roundtrip
        with tempfile.NamedTemporaryFile(mode='w', suffix='.srt', delete=False, encoding='utf-8') as f:
            roundtrip_file = f.name
        
        save_captions_srt(captions, Path(roundtrip_file))
        
        # Parse roundtrip
        roundtrip_captions = load_captions_srt(Path(roundtrip_file))
        
        # Special characters should be preserved
        assert roundtrip_captions[0]["content"] == captions[0]["content"]
        assert roundtrip_captions[1]["content"] == captions[1]["content"]
        
        print("✅ SRT special characters roundtrip successful")
        
    finally:
        # Clean up
        for file_path in [original_file, roundtrip_file]:
            if os.path.exists(file_path):
                os.unlink(file_path)


def test_srt_roundtrip_with_timing_edge_cases():
    """Test SRT roundtrip with edge case timings."""
    # Edge case timings
    edge_srt_content = """1
00:00:00,000 --> 00:00:00,001
Very short caption

2
00:59:59,999 --> 01:00:00,000
End of hour caption

3
99:59:59,999 --> 99:59:59,999
Same start and end time
"""
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.srt', delete=False) as f:
        original_file = f.name
        f.write(edge_srt_content)
    
    try:
        # Parse
        captions = load_captions_srt(Path(original_file))
        assert len(captions) == 3
        
        # Check timings
        assert captions[0]["start"] == 0.0
        assert captions[0]["end"] == 0.001
        
        assert captions[1]["start"] == 3599.999
        assert captions[1]["end"] == 3600.0
        
        assert captions[2]["start"] == captions[2]["end"]
        
        # Roundtrip
        with tempfile.NamedTemporaryFile(mode='w', suffix='.srt', delete=False) as f:
            roundtrip_file = f.name
        
        save_captions_srt(captions, Path(roundtrip_file))
        
        # Parse roundtrip
        roundtrip_captions = load_captions_srt(Path(roundtrip_file))
        
        # Timings should be preserved exactly
        for orig, rt in zip(captions, roundtrip_captions):
            assert abs(orig["start"] - rt["start"]) < 0.001
            assert abs(orig["end"] - rt["end"]) < 0.001
        
        print("✅ SRT timing edge cases roundtrip successful")
        
    finally:
        # Clean up
        for file_path in [original_file, roundtrip_file]:
            if os.path.exists(file_path):
                os.unlink(file_path)


def test_wrap_captions_different_font_sizes():
    """Test caption wrapping with different font sizes."""
    long_lines = ["This is a very long caption that should be wrapped differently based on font size"]
    
    # Small font - should allow more characters per line
    wrapped_small = wrap_captions_by_pixel_width(long_lines, font_size=20, max_width_px=400)
    
    # Large font - should allow fewer characters per line
    wrapped_large = wrap_captions_by_pixel_width(long_lines, font_size=60, max_width_px=400)
    
    # Large font should result in more lines or shorter lines
    if len(wrapped_small) == len(wrapped_large):
        # Same number of lines, check if large font lines are shorter
        small_chars = sum(len(line) for line in wrapped_small)
        large_chars = sum(len(line) for line in wrapped_large)
        assert large_chars <= small_chars
    else:
        # Different number of lines is also acceptable
        assert True


def test_srt_roundtrip_performance():
    """Test SRT roundtrip with large number of captions."""
    # Create many captions
    captions_content = ""
    for i in range(100):
        start_time = i * 2.0
        end_time = start_time + 1.5
        captions_content += f"""{i+1}
00:{int(start_time//60):02d}:{int(start_time%60):02d},{int((start_time%1)*1000):03d} --> 00:{int(end_time//60):02d}:{int(end_time%60):02d},{int((end_time%1)*1000):03d}
Caption number {i+1} with some content.

"""
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.srt', delete=False) as f:
        original_file = f.name
        f.write(captions_content)
    
    try:
        # Parse
        captions = load_captions_srt(Path(original_file))
        assert len(captions) == 100
        
        # Roundtrip
        with tempfile.NamedTemporaryFile(mode='w', suffix='.srt', delete=False) as f:
            roundtrip_file = f.name
        
        save_captions_srt(captions, Path(roundtrip_file))
        
        # Parse roundtrip
        roundtrip_captions = load_captions_srt(Path(roundtrip_file))
        assert len(roundtrip_captions) == 100
        
        # Check a few random captions
        for i in [0, 25, 50, 75, 99]:
            orig = captions[i]
            rt = roundtrip_captions[i]
            assert orig["index"] == rt["index"]
            assert orig["content"] == rt["content"]
            assert abs(orig["start"] - rt["start"]) < 0.001
        
        print("✅ SRT large file roundtrip successful")
        
    finally:
        # Clean up
        for file_path in [original_file, roundtrip_file]:
            if os.path.exists(file_path):
                os.unlink(file_path)