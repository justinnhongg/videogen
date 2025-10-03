"""
Final export with audio processing and SRT handling.
"""

import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any

from .errors import MuxError, RenderError
from .logging import Timer


def process_voice_audio(voice_path: Path, output_path: Path,
                       target_dbfs: float = -14.0) -> None:
    """
    Process voice audio: normalize to target dBFS.
    
    Args:
        voice_path: Path to input voice audio
        output_path: Path to output normalized audio
        target_dbfs: Target dBFS level
    """
    if not voice_path.exists():
        raise RenderError(f"Voice audio file not found: {voice_path}")
    
    # Use FFmpeg for normalization
    cmd = [
        "ffmpeg", "-y", "-i", str(voice_path),
        "-af", f"loudnorm=I={target_dbfs}:TP=-1.0:LRA=11",
        "-c:a", "pcm_s24le",
        str(output_path)
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise RenderError(f"Voice audio processing failed: {e}")


def process_music_audio(music_path: Path, voice_path: Path, output_path: Path,
                       threshold: float = 0.02, ratio: float = 8.0,
                       attack_ms: float = 5.0, release_ms: float = 250.0,
                       music_level: float = -28.0) -> None:
    """
    Process music audio with sidechain compression.
    
    Args:
        music_path: Path to background music
        voice_path: Path to voice audio (for sidechain)
        output_path: Path to output ducked music
        threshold: Compression threshold (0.0 to 1.0)
        ratio: Compression ratio
        attack_ms: Attack time in milliseconds
        release_ms: Release time in milliseconds
        music_level: Music level in dBFS
    """
    if not music_path.exists():
        raise RenderError(f"Music file not found: {music_path}")
    
    if not voice_path.exists():
        raise RenderError(f"Voice file not found: {voice_path}")
    
    # Create sidechain compression filter
    filter_complex = (
        f"[0:a]aformat=channel_layouts=stereo,volume=1.0[lv];"
        f"[1:a]aformat=channel_layouts=stereo,volume={music_level}dB[lm];"
        f"[lm][lv]sidechaincompress=threshold={threshold}:ratio={ratio}:"
        f"attack={attack_ms}:release={release_ms}:makeup=0[mduck];"
        f"[mduck]alimiter=limit=-1dB[out]"
    )
    
    cmd = [
        "ffmpeg", "-y",
        "-i", str(voice_path),
        "-i", str(music_path),
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-c:a", "pcm_s24le",
        str(output_path)
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise RenderError(f"Music processing failed: {e}")


def mix_audio_tracks(voice_path: Path, music_path: Path, output_path: Path,
                    voice_level: float = 0.0, music_level: float = -6.0) -> None:
    """
    Mix voice and music tracks.
    
    Args:
        voice_path: Path to voice audio
        music_path: Path to music audio
        output_path: Path to mixed output
        voice_level: Voice level in dB
        music_level: Music level in dB
    """
    filter_complex = (
        f"[0:a]volume={voice_level}dB[voice];"
        f"[1:a]volume={music_level}dB[music];"
        f"[voice][music]amix=inputs=2:weights=1 1:duration=longest[out]"
    )
    
    cmd = [
        "ffmpeg", "-y",
        "-i", str(voice_path),
        "-i", str(music_path),
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-c:a", "aac", "-b:a", "192k",
        str(output_path)
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise RenderError(f"Audio mixing failed: {e}")


def burn_srt_subtitles(video_path: Path, srt_path: Path, output_path: Path,
                      font_size: int = 40, font_color: str = "#FFFFFF",
                      stroke_color: str = "#000000", stroke_width: int = 3) -> None:
    """
    Burn SRT subtitles into video using FFmpeg.
    
    Args:
        video_path: Path to input video
        srt_path: Path to SRT subtitle file
        output_path: Path to output video with burned subtitles
        font_size: Font size in pixels
        font_color: Font color (hex)
        stroke_color: Stroke color (hex)
        stroke_width: Stroke width in pixels
    """
    if not video_path.exists():
        raise RenderError(f"Video file not found: {video_path}")
    
    if not srt_path.exists():
        raise RenderError(f"SRT file not found: {srt_path}")
    
    # Create subtitle filter
    filter_str = (
        f"subtitles={srt_path}:"
        f"force_style='FontSize={font_size},"
        f"PrimaryColour={font_color.replace('#', '&H')},"
        f"OutlineColour={stroke_color.replace('#', '&H')},"
        f"Outline={stroke_width},"
        f"Alignment=2'"  # Bottom center
    )
    
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vf", filter_str,
        "-c:a", "copy",
        "-c:v", "libx264",
        str(output_path)
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise RenderError(f"Failed to burn subtitles: {e}")


def attach_soft_subtitles(video_path: Path, srt_path: Path, output_path: Path) -> None:
    """
    Attach SRT as soft subtitles to video.
    
    Args:
        video_path: Path to input video
        srt_path: Path to SRT subtitle file
        output_path: Path to output video with soft subtitles
    """
    if not video_path.exists():
        raise RenderError(f"Video file not found: {video_path}")
    
    if not srt_path.exists():
        raise RenderError(f"SRT file not found: {srt_path}")
    
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(srt_path),
        "-c", "copy",
        "-c:s", "mov_text",
        "-metadata:s:s:0", "language=eng",
        str(output_path)
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise RenderError(f"Failed to attach soft subtitles: {e}")


def mux_final_video(video_path: Path, audio_path: Path, output_path: Path,
                   srt_path: Optional[Path] = None, burn_subs: bool = False,
                   logger=None, project: str = "") -> Path:
    """
    Mux final video with audio and optional subtitles.
    
    Args:
        video_path: Path to video file
        audio_path: Path to audio file
        output_path: Path to final output
        srt_path: Path to SRT file (optional)
        burn_subs: Whether to burn subtitles or attach as soft subs
        logger: Logger instance
        project: Project name for logging
    
    Returns:
        Path to final video
    """
    with Timer(logger, "mux", project, "Muxing final video"):
        if not video_path.exists():
            raise MuxError(f"Video file not found: {video_path}")
        
        if not audio_path.exists():
            raise MuxError(f"Audio file not found: {audio_path}")
        
        # If subtitles are requested
        if srt_path and srt_path.exists():
            if burn_subs:
                # Burn subtitles into video
                burn_srt_subtitles(video_path, srt_path, output_path)
            else:
                # Attach as soft subtitles
                attach_soft_subtitles(video_path, srt_path, output_path)
        else:
            # Simple video + audio muxing
            cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-i", str(audio_path),
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k",
                "-shortest",
                str(output_path)
            ]
            
            try:
                subprocess.run(cmd, check=True, capture_output=True)
            except subprocess.CalledProcessError as e:
                raise MuxError(f"Video muxing failed: {e}")
        
        return output_path


def export_complete_video(video_path: Path, voice_path: Path, music_path: Optional[Path],
                         srt_path: Optional[Path], output_path: Path,
                         config: Dict[str, Any], burn_subs: bool = False,
                         logger=None, project: str = "") -> Path:
    """
    Complete video export pipeline.
    
    Args:
        video_path: Path to assembled video (no audio)
        voice_path: Path to voice audio
        music_path: Path to background music (optional)
        srt_path: Path to SRT subtitles (optional)
        output_path: Path to final output video
        config: Configuration dictionary
        burn_subs: Whether to burn subtitles
        logger: Logger instance
        project: Project name for logging
    
    Returns:
        Path to final video
    """
    with Timer(logger, "export", project, "Exporting complete video"):
        # Process voice audio
        voice_processed = output_path.parent / "voice_processed.wav"
        target_dbfs = config.get("audio", {}).get("target_lufs", -14.0)
        process_voice_audio(voice_path, voice_processed, target_dbfs)
        
        # Process music if provided
        if music_path and music_path.exists():
            music_processed = output_path.parent / "music_processed.wav"
            ducking_config = config.get("audio", {}).get("ducking", {})
            
            process_music_audio(
                music_path, voice_processed, music_processed,
                threshold=ducking_config.get("threshold", 0.02),
                ratio=ducking_config.get("ratio", 8.0),
                attack_ms=ducking_config.get("attack_ms", 5.0),
                release_ms=ducking_config.get("release_ms", 250.0),
                music_level=config.get("audio", {}).get("music_db", -28.0)
            )
            
            # Mix voice and music
            mixed_audio = output_path.parent / "mixed_audio.wav"
            mix_audio_tracks(voice_processed, music_processed, mixed_audio)
            final_audio = mixed_audio
        else:
            final_audio = voice_processed
        
        # Mux final video
        return mux_final_video(
            video_path, final_audio, output_path,
            srt_path, burn_subs, logger, project
        )


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
