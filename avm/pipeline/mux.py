"""Final video/audio muxing and output validation utilities."""

import json
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

from .errors import MuxError
from .logging import Timer

logger = logging.getLogger("avm")


def mux_audio_video(video_nocap: Path, voice_norm_wav: Path, music_ducked_wav: Optional[Path],
                   out_no_subs_mp4: Path, config: Optional[Dict[str, Any]] = None,
                   logger=None, project: str = "") -> float:
    """
    Mux audio and video streams with proper mixing.
    
    Args:
        video_nocap: Path to video without audio
        voice_norm_wav: Path to normalized voice audio
        music_ducked_wav: Path to ducked music audio (optional)
        out_no_subs_mp4: Path to output video without subtitles
        config: Project configuration
        logger: Logger instance
        project: Project name for logging
    
    Returns:
        Duration of the final video in seconds
    """
    
    if not video_nocap.exists():
        raise MuxError(f"Video file not found: {video_nocap}")
    
    if not voice_norm_wav.exists():
        raise MuxError(f"Voice audio file not found: {voice_norm_wav}")
    
    config = config or {}
    
    try:
        with Timer(logger, "mux_audio", project, "Muxing audio and video"):
            # Build FFmpeg command
            cmd = ["ffmpeg", "-y"]
            
            # Input files
            cmd.extend(["-i", str(video_nocap)])
            cmd.extend(["-i", str(voice_norm_wav)])
            
            if music_ducked_wav and music_ducked_wav.exists():
                # Both voice and music: amix with weights 1:1 (post-ducking)
                cmd.extend(["-i", str(music_ducked_wav)])
                
                # Audio mixing filter
                filter_complex = (
                    f"[1:a]aformat=channel_layouts=stereo,aresample=48000[voice];"
                    f"[2:a]aformat=channel_layouts=stereo,aresample=48000[music];"
                    f"[voice][music]amix=inputs=2:weights=1 1:duration=longest[out]"
                )
                
                cmd.extend(["-filter_complex", filter_complex])
                cmd.extend(["-map", "0:v:0"])  # Video from first input
                cmd.extend(["-map", "[out]"])  # Mixed audio
            else:
                # Just voice: copy voice audio
                cmd.extend(["-map", "0:v:0"])  # Video from first input
                cmd.extend(["-map", "1:a:0"])  # Voice from second input
            
            # Audio encoding settings - AAC at 48kHz stereo with limiter
            cmd.extend([
                "-c:a", "aac",
                "-b:a", "192k",
                "-ar", "48000",
                "-ac", "2",  # Ensure stereo
                "-af", "alimiter=limit=-1.0"  # True peak limiter to -1.0 dBTP
            ])
            
            # Video encoding settings (copy to preserve quality)
            cmd.extend(["-c:v", "copy"])
            
            # Output file
            cmd.append(str(out_no_subs_mp4))
            
            # Execute command
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            
            duration = probe_video_duration(out_no_subs_mp4)
            
            if logger:
                logger.info(f"Successfully muxed audio and video: {out_no_subs_mp4}")
                logger.info(f"Video duration: {duration:.2f} seconds")
            
            return duration
            
    except subprocess.CalledProcessError as e:
        stderr_tail = (e.stderr or "")[-800:]
        raise MuxError(f"FFmpeg muxing failed\n{stderr_tail}")
    except FileNotFoundError:
        raise MuxError("FFmpeg not found. Please install FFmpeg.")
    except Exception as e:
        raise MuxError(f"Audio/video muxing error: {e}")


def probe_video_duration(video_path: Path) -> float:
    """
    Get video duration using ffprobe.
    
    Args:
        video_path: Path to video file
    
    Returns:
        Duration in seconds
    """
    
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(video_path),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        payload = json.loads(result.stdout)
        duration_value = payload.get("format", {}).get("duration")
        if duration_value is None:
            raise ValueError("Duration missing from ffprobe output")
        return float(duration_value)
    except subprocess.CalledProcessError as exc:
        stderr_tail = (exc.stderr or "")[-800:]
        raise MuxError(f"Failed to probe video duration\n{stderr_tail}") from exc
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise MuxError(f"Invalid ffprobe duration output: {exc}")


def video_has_expected_codecs(video_path: Path) -> bool:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_streams",
        "-print_format",
        "json",
        str(video_path),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        payload = json.loads(result.stdout)
    except subprocess.CalledProcessError as exc:
        stderr_tail = (exc.stderr or "")[-800:]
        logger.warning(f"ffprobe codec inspection failed for {video_path}: {stderr_tail}")
        return False
    except json.JSONDecodeError as exc:
        logger.warning(f"Unable to decode codec information for {video_path}: {exc}")
        return False

    has_h264 = False
    has_aac = False

    for stream in payload.get("streams", []):
        codec = stream.get("codec_name", "").lower()
        codec_type = stream.get("codec_type")
        if codec_type == "video" and codec == "h264":
            has_h264 = True
        elif codec_type == "audio" and codec in {"aac", "mp4a"}:
            has_aac = True

    if not has_h264 or not has_aac:
        logger.warning(
            f"Codec check failed for {video_path}: video=h264? {has_h264}, audio=aac? {has_aac}"
        )
        return False

    return True


def get_video_info(video_path: Path) -> Dict[str, Any]:
    """
    Get comprehensive video information using ffprobe.
    
    Args:
        video_path: Path to video file
    
    Returns:
        Dictionary with video information
    """
    
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(video_path)
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        import json
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        stderr_tail = (e.stderr or "")[-800:]
        raise MuxError(f"ffprobe failed\n{stderr_tail}")
    except json.JSONDecodeError as e:
        raise MuxError(f"Failed to parse video info JSON: {e}")
    except FileNotFoundError:
        raise MuxError("ffprobe not found. Please install FFmpeg.")


def validate_output(video_path: Path) -> bool:
    """
    Validate that output video is properly formatted.
    
    Args:
        video_path: Path to video file
    
    Returns:
        True if video is valid, False otherwise
    """
    
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


def create_chapter_markers(video_path: Path, timeline: Dict[str, Any],
                          output_path: Path) -> None:
    """
    Create chapter markers for video segments.
    
    Args:
        video_path: Input video file
        timeline: Timeline data with segments
        output_path: Output video with chapter markers
    """
    
    # Create chapter metadata file
    chapters_content = ";FFMETADATA1\n"
    
    for segment in timeline.get("segments", []):
        start_time = segment.get("start", 0)
        end_time = segment.get("end", 0)
        index = segment.get("index", 0)
        
        chapters_content += f"[CHAPTER]\n"
        chapters_content += f"TIMEBASE=1/1000\n"
        chapters_content += f"START={int(start_time * 1000)}\n"
        chapters_content += f"END={int(end_time * 1000)}\n"
        chapters_content += f"title=Slide {index + 1}\n"
    
    # Write chapter file
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(chapters_content)
        chapter_file = f.name
    
    try:
        # Apply chapters to video
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", chapter_file,
            "-map_metadata", "1",
            "-c", "copy",
            str(output_path)
        ]
        
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        
    except subprocess.CalledProcessError as e:
        stderr_tail = (e.stderr or "")[-800:]
        raise MuxError(f"Failed to add chapter markers\n{stderr_tail}")
    except FileNotFoundError:
        raise MuxError("FFmpeg not found. Please install FFmpeg.")
    finally:
        # Clean up chapter file
        Path(chapter_file).unlink(missing_ok=True)


def extract_thumbnail(video_path: Path, output_path: Path, 
                     time_sec: float = 5.0) -> None:
    """
    Extract thumbnail from video at specified time.
    
    Args:
        video_path: Input video file
        output_path: Output thumbnail file
        time_sec: Time position in seconds
    """
    
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-ss", str(time_sec),
        "-vframes", "1",
        "-q:v", "2",
        str(output_path)
    ]
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        stderr_tail = (e.stderr or "")[-800:]
        raise MuxError(f"Failed to extract thumbnail\n{stderr_tail}")
    except FileNotFoundError:
        raise MuxError("FFmpeg not found. Please install FFmpeg.")


def create_preview_video(video_path: Path, output_path: Path,
                        duration_sec: float = 30.0) -> None:
    """
    Create a preview clip from the full video.
    
    Args:
        video_path: Input video file
        output_path: Output preview file
        duration_sec: Preview duration in seconds
    """
    
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-t", str(duration_sec),
        "-c", "copy",
        str(output_path)
    ]
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        stderr_tail = (e.stderr or "")[-800:]
        raise MuxError(f"Failed to create preview\n{stderr_tail}")
    except FileNotFoundError:
        raise MuxError("FFmpeg not found. Please install FFmpeg.")


def add_watermark_overlay(video_path: Path, watermark_path: Path,
                         output_path: Path, position: str = "bottom-right",
                         opacity: float = 0.8, size: int = 200) -> None:
    """
    Add watermark overlay using FFmpeg.
    
    Args:
        video_path: Input video file
        watermark_path: Watermark image file
        output_path: Output video file
        position: Watermark position
        opacity: Watermark opacity (0.0 to 1.0)
        size: Watermark size in pixels
    """
    
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
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        stderr_tail = (e.stderr or "")[-800:]
        raise MuxError(f"Failed to add watermark\n{stderr_tail}")
    except FileNotFoundError:
        raise MuxError("FFmpeg not found. Please install FFmpeg.")


# Legacy functions for backward compatibility
def mux_video_audio(video_path: Path, audio_path: Path, output_path: Path,
                   captions_srt: Optional[Path] = None, 
                   config: Dict[str, Any] = None,
                   logger=None, project: str = "") -> None:
    """
    Legacy function for backward compatibility.
    
    Args:
        video_path: Path to video file
        audio_path: Path to audio file
        output_path: Path to output file
        captions_srt: Path to SRT captions file (optional)
        config: Project configuration
        logger: Logger instance
        project: Project name for logging
    """
    
    # Use the new mux_audio_video function
    duration = mux_audio_video(video_path, audio_path, None, output_path, config, logger, project)
    
    # Add captions if provided (this would need additional implementation)
    if captions_srt and captions_srt.exists():
        # This would require additional caption handling
        pass
