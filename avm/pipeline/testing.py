"""
Testing utilities and golden file comparison for AVM pipeline.
"""

import json
import hashlib
from pathlib import Path
from typing import Dict, Any, List, Optional

try:
    import cv2
    import numpy as np
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False


def compare_timeline_golden(timeline_path: Path, golden_path: Path,
                           tolerance: float = 0.1) -> bool:
    """Compare timeline JSON with golden file."""
    
    if not timeline_path.exists():
        return False
    
    if not golden_path.exists():
        return False
    
    try:
        with open(timeline_path, 'r') as f:
            timeline = json.load(f)
        
        with open(golden_path, 'r') as f:
            golden = json.load(f)
        
        # Compare basic structure
        if timeline.get("total_duration", 0) != golden.get("total_duration", 0):
            return False
        
        if len(timeline.get("segments", [])) != len(golden.get("segments", [])):
            return False
        
        # Compare segments with tolerance
        for i, (seg, golden_seg) in enumerate(zip(timeline["segments"], golden["segments"])):
            if not _compare_segment(seg, golden_seg, tolerance):
                return False
        
        return True
        
    except (json.JSONDecodeError, KeyError):
        return False


def _compare_segment(segment: Dict[str, Any], golden_segment: Dict[str, Any],
                    tolerance: float) -> bool:
    """Compare individual timeline segments."""
    
    # Compare timing
    if abs(segment.get("start", 0) - golden_segment.get("start", 0)) > tolerance:
        return False
    
    if abs(segment.get("end", 0) - golden_segment.get("end", 0)) > tolerance:
        return False
    
    if abs(segment.get("duration", 0) - golden_segment.get("duration", 0)) > tolerance:
        return False
    
    # Compare Ken-Burns parameters
    seg_kb = segment.get("kenburns", {})
    golden_kb = golden_segment.get("kenburns", {})
    
    if abs(seg_kb.get("zoom_start", 1) - golden_kb.get("zoom_start", 1)) > 0.01:
        return False
    
    if abs(seg_kb.get("zoom_end", 1) - golden_kb.get("zoom_end", 1)) > 0.01:
        return False
    
    return True


def compare_image_golden(image_path: Path, golden_path: Path,
                        ssim_threshold: float = 0.98) -> bool:
    """Compare image with golden file using SSIM."""
    
    if not OPENCV_AVAILABLE:
        return _compare_image_hash(image_path, golden_path)
    
    if not image_path.exists() or not golden_path.exists():
        return False
    
    try:
        # Load images
        img1 = cv2.imread(str(image_path))
        img2 = cv2.imread(str(golden_path))
        
        if img1 is None or img2 is None:
            return False
        
        # Convert to grayscale
        gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)
        
        # Calculate SSIM
        ssim = _calculate_ssim(gray1, gray2)
        
        return ssim >= ssim_threshold
        
    except Exception:
        return False


def _calculate_ssim(img1: np.ndarray, img2: np.ndarray) -> float:
    """Calculate Structural Similarity Index."""
    
    # Constants
    C1 = 0.01 ** 2
    C2 = 0.03 ** 2
    
    # Calculate means
    mu1 = cv2.GaussianBlur(img1, (11, 11), 1.5)
    mu2 = cv2.GaussianBlur(img2, (11, 11), 1.5)
    
    mu1_sq = mu1 * mu1
    mu2_sq = mu2 * mu2
    mu1_mu2 = mu1 * mu2
    
    # Calculate variances and covariance
    sigma1_sq = cv2.GaussianBlur(img1 * img1, (11, 11), 1.5) - mu1_sq
    sigma2_sq = cv2.GaussianBlur(img2 * img2, (11, 11), 1.5) - mu2_sq
    sigma12 = cv2.GaussianBlur(img1 * img2, (11, 11), 1.5) - mu1_mu2
    
    # Calculate SSIM
    ssim_map = ((2 * mu1_mu2 + C1) * (2 * sigma12 + C2)) / \
               ((mu1_sq + mu2_sq + C1) * (sigma1_sq + sigma2_sq + C2))
    
    return np.mean(ssim_map)


def _compare_image_hash(image_path: Path, golden_path: Path) -> bool:
    """Fallback image comparison using file hash."""
    
    try:
        hash1 = hashlib.md5(image_path.read_bytes()).hexdigest()
        hash2 = hashlib.md5(golden_path.read_bytes()).hexdigest()
        return hash1 == hash2
    except Exception:
        return False


def compare_captions_golden(captions_path: Path, golden_path: Path) -> bool:
    """Compare captions with golden file (byte-tolerant)."""
    
    if not captions_path.exists() or not golden_path.exists():
        return False
    
    try:
        with open(captions_path, 'r', encoding='utf-8') as f:
            captions_content = f.read()
        
        with open(golden_path, 'r', encoding='utf-8') as f:
            golden_content = f.read()
        
        # Normalize whitespace
        captions_normalized = _normalize_captions(captions_content)
        golden_normalized = _normalize_captions(golden_content)
        
        return captions_normalized == golden_normalized
        
    except Exception:
        return False


def _normalize_captions(content: str) -> str:
    """Normalize caption content for comparison."""
    
    # Remove extra whitespace
    lines = [line.strip() for line in content.split('\n')]
    
    # Remove empty lines
    lines = [line for line in lines if line]
    
    return '\n'.join(lines)


def create_test_fixtures(test_dir: Path, audio_duration: float = 10.0,
                        slides_count: int = 3) -> Dict[str, Path]:
    """Create test fixtures for pipeline testing."""
    
    test_dir.mkdir(parents=True, exist_ok=True)
    
    fixtures = {}
    
    # Create test audio (silent)
    audio_path = test_dir / "test_audio.wav"
    _create_silent_audio(audio_path, audio_duration)
    fixtures["audio"] = audio_path
    
    # Create test slides markdown
    slides_path = test_dir / "test_slides.md"
    _create_test_slides(slides_path, slides_count)
    fixtures["slides"] = slides_path
    
    # Create test config
    config_path = test_dir / "test_config.yml"
    _create_test_config(config_path)
    fixtures["config"] = config_path
    
    return fixtures


def _create_silent_audio(audio_path: Path, duration: float) -> None:
    """Create silent audio file for testing."""
    
    import subprocess
    
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"anullsrc=channel_layout=stereo:sample_rate=48000",
        "-t", str(duration),
        "-c:a", "pcm_s16le",
        str(audio_path)
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError:
        # Fallback: create empty file
        audio_path.write_bytes(b'')


def _create_test_slides(slides_path: Path, slides_count: int) -> None:
    """Create test slides markdown."""
    
    slides_content = []
    
    for i in range(slides_count):
        slides_content.append(f"# Test Slide {i + 1}")
        slides_content.append(f"- This is bullet point 1 for slide {i + 1}")
        slides_content.append(f"- This is bullet point 2 for slide {i + 1}")
        slides_content.append(f"- This is bullet point 3 for slide {i + 1}")
        slides_content.append("")
    
    slides_path.write_text('\n'.join(slides_content))


def _create_test_config(config_path: Path) -> None:
    """Create test configuration."""
    
    config = {
        "slug": "test",
        "title": "Test Video",
        "author": "Test Author",
        "watermark": False,
        "burn_captions": False,
        "timeline": {
            "method": "even",
            "min_slide_sec": 2.0,
            "max_slide_sec": 10.0,
            "gap_sec": 0.25
        },
        "thumbnail": {
            "title": "Test Thumbnail",
            "subtitle": "Test Subtitle",
            "bg": "#000000"
        }
    }
    
    import yaml
    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False)


def run_pipeline_test(project_dir: Path, expected_artifacts: List[str]) -> bool:
    """Run full pipeline test and verify artifacts."""
    
    build_dir = project_dir / "build"
    
    if not build_dir.exists():
        return False
    
    # Check that all expected artifacts exist
    for artifact in expected_artifacts:
        artifact_path = build_dir / artifact
        if not artifact_path.exists():
            return False
    
    return True


def validate_video_output(video_path: Path) -> Dict[str, Any]:
    """Validate video output and return metadata."""
    
    if not video_path.exists():
        return {"valid": False, "error": "File not found"}
    
    try:
        import subprocess
        
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", str(video_path)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        info = json.loads(result.stdout)
        
        # Extract key information
        format_info = info.get("format", {})
        streams = info.get("streams", [])
        
        video_stream = None
        audio_stream = None
        
        for stream in streams:
            if stream.get("codec_type") == "video":
                video_stream = stream
            elif stream.get("codec_type") == "audio":
                audio_stream = stream
        
        return {
            "valid": True,
            "duration": float(format_info.get("duration", 0)),
            "size": int(format_info.get("size", 0)),
            "video_codec": video_stream.get("codec_name") if video_stream else None,
            "audio_codec": audio_stream.get("codec_name") if audio_stream else None,
            "width": video_stream.get("width") if video_stream else None,
            "height": video_stream.get("height") if video_stream else None,
            "fps": eval(video_stream.get("r_frame_rate", "0/1")) if video_stream else None
        }
        
    except Exception as e:
        return {"valid": False, "error": str(e)}
