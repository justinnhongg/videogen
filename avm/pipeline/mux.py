"""
Final video/audio muxing and output generation.
"""

import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

from .errors import MuxError


def mux_video_audio(video_path: Path, audio_path: Path, output_path: Path,
                   captions_srt: Optional[Path] = None, 
                   config: Dict[str, Any] = None,
                   logger=None, project: str = "") -> None:
    """
    Mux video and audio streams into final output.
    
    Args:
        video_path: Path to video file
        audio_path: Path to audio file
        output_path: Path to output file
        captions_srt: Path to SRT captions file (optional)
        config: Project configuration
        logger: Logger instance
        project: Project name for logging
    """
    
    if not video_path.exists():
        raise MuxError(f"Video file not found: {video_path}")
    
    if not audio_path.exists():
        raise MuxError(f"Audio file not found: {audio_path}")
    
    # Build FFmpeg command
    cmd = ["ffmpeg", "-y"]
    
    # Input files
    cmd.extend(["-i", str(video_path)])
    cmd.extend(["-i", str(audio_path)])
    
    # Add captions if provided
    if captions_srt and captions_srt.exists():
        cmd.extend(["-i", str(captions_srt)])
    
    # Video encoding settings
    export_config = config.get("export", {}) if config else {}
    crf = export_config.get("crf", 18)
    preset = export_config.get("preset", "medium")
    
    cmd.extend([
        "-c:v", "libx264",
        "-crf", str(crf),
        "-preset", preset,
        "-pix_fmt", "yuv420p"
    ])
    
    # Audio encoding
    cmd.extend([
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "48000"
    ])
    
    # Map streams
    cmd.extend(["-map", "0:v:0"])  # Video from first input
    cmd.extend(["-map", "1:a:0"])  # Audio from second input
    
    # Handle captions
    if captions_srt and captions_srt.exists():
        cmd.extend(["-map", "2:s:0"])  # Subtitles from third input
        cmd.extend(["-c:s", "mov_text"])
        cmd.extend(["-metadata:s:s:0", "language=eng"])
    
    # Metadata
    project_config = config.get("project", {}) if config else {}
    title = project_config.get("title", "")
    author = project_config.get("author", "")
    
    if title:
        cmd.extend(["-metadata", f"title={title}"])
    if author:
        cmd.extend(["-metadata", f"artist={author}"])
    
    # Output file
    cmd.append(str(output_path))
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        
        if logger:
            logger.info(f"Successfully muxed video: {output_path}")
            
    except subprocess.CalledProcessError as e:
        error_msg = f"FFmpeg muxing failed: {e}"
        if e.stderr:
            error_msg += f"\nFFmpeg error: {e.stderr}"
        raise MuxError(error_msg)


def create_chapter_markers(video_path: Path, timeline: Dict[str, Any],
                          output_path: Path) -> None:
    """Create chapter markers for video segments."""
    
    # Create chapter metadata file
    chapters_content = ";FFMETADATA1\n"
    
    for segment in timeline["segments"]:
        start_time = segment["start"]
        title = f"Slide {segment['slide_num']}"
        
        chapters_content += f"[CHAPTER]\n"
        chapters_content += f"TIMEBASE=1/1000\n"
        chapters_content += f"START={int(start_time * 1000)}\n"
        chapters_content += f"END={int(segment['end'] * 1000)}\n"
        chapters_content += f"title={title}\n"
    
    # Write chapter file
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(chapters_content)
        chapter_file = f.name
    
    # Apply chapters to video
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", chapter_file,
        "-map_metadata", "1",
        "-c", "copy",
        str(output_path)
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise MuxError(f"Failed to add chapter markers: {e}")
    finally:
        # Clean up chapter file
        Path(chapter_file).unlink(missing_ok=True)


def extract_thumbnail(video_path: Path, output_path: Path, 
                     time_sec: float = 5.0) -> None:
    """Extract thumbnail from video at specified time."""
    
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-ss", str(time_sec),
        "-vframes", "1",
        "-q:v", "2",
        str(output_path)
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise MuxError(f"Failed to extract thumbnail: {e}")


def get_video_info(video_path: Path) -> Dict[str, Any]:
    """Get video information using ffprobe."""
    
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(video_path)
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        import json
        return json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        raise MuxError(f"Failed to get video info: {e}")


def validate_output(video_path: Path) -> bool:
    """Validate that output video is properly formatted."""
    
    try:
        info = get_video_info(video_path)
        
        # Check for video and audio streams
        has_video = False
        has_audio = False
        
        for stream in info.get("streams", []):
            if stream.get("codec_type") == "video":
                has_video = True
                # Check codec
                if stream.get("codec_name") != "h264":
                    return False
            elif stream.get("codec_type") == "audio":
                has_audio = True
                # Check codec
                if stream.get("codec_name") not in ["aac", "mp4a"]:
                    return False
        
        return has_video and has_audio
        
    except Exception:
        return False


def create_preview_video(video_path: Path, output_path: Path,
                        duration_sec: float = 30.0) -> None:
    """Create a preview clip from the full video."""
    
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-t", str(duration_sec),
        "-c", "copy",
        str(output_path)
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise MuxError(f"Failed to create preview: {e}")


def add_watermark_overlay(video_path: Path, watermark_path: Path,
                         output_path: Path, position: str = "bottom-right",
                         opacity: float = 0.8, size: int = 200) -> None:
    """Add watermark overlay using FFmpeg."""
    
    # Calculate position
    if position == "bottom-right":
        pos = f"W-w-20:H-h-20"
    elif position == "bottom-left":
        pos = f"20:H-h-20"
    elif position == "top-right":
        pos = f"W-w-20:20"
    elif position == "top-left":
        pos = f"20:20"
    else:
        pos = f"W-w-20:H-h-20"
    
    # Create filter
    filter_str = f"[0:v][1:v]overlay={pos}:format=auto:alpha={opacity}"
    
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(watermark_path),
        "-filter_complex", filter_str,
        "-c:a", "copy",
        "-c:v", "libx264",
        str(output_path)
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise MuxError(f"Failed to add watermark: {e}")
