"""
Final export with audio processing and SRT handling.
"""

import subprocess
from pathlib import Path
from typing import Optional, Dict, Any

from .errors import MuxError, RenderError
from .logging import Timer
from .captions import burn_captions, attach_soft_subs
from .io_paths import ProjectPaths
from .mux import mux_audio_video, probe_video_duration, video_has_expected_codecs


def export_complete_video(config: Dict[str, Any], paths: ProjectPaths, 
                         burn_captions: bool, logger=None, project: str = "") -> float:
    """
    Export complete video with professional encoding and caption integration.
    
    Args:
        config: Project configuration
        paths: ProjectPaths instance with all file paths
        burn_captions: Whether to burn captions or attach as soft subs
        logger: Logger instance
        project: Project name for logging
    
    Returns:
        Duration of the final video in seconds
    """
    
    if not paths.video_nocap_mp4.exists():
        raise RenderError(f"Video file not found: {paths.video_nocap_mp4}")
    
    if not paths.audio_wav.exists():
        raise RenderError(f"Audio file not found: {paths.audio_wav}")
    
    try:
        with Timer(logger, "export_complete", project, "Exporting complete video"):
            # Get music path from config (project config key "music") and CLI override
            music_path = None
            if "music" in config:
                music_path = Path(config["music"]) if config["music"] else None
            
            # Step 1: Process audio (normalize voice, duck music)
            from .audio import process_audio
            process_audio(
                paths.audio_wav, music_path, 
                paths.voice_norm_wav, paths.music_ducked_wav, 
                config, logger, project
            )
            
            # Step 2: Mux audio with video
            mux_audio_video(
                paths.video_nocap_mp4, paths.voice_norm_wav,
                paths.music_ducked_wav if paths.music_ducked_wav.exists() else None,
                paths.video_audio_mp4, config, logger, project
            )

            if logger:
                logger.info("Validating muxed video duration and codecs")
            try:
                mux_duration = probe_video_duration(paths.video_audio_mp4)
            except MuxError as exc:
                raise RenderError(str(exc)) from exc

            if mux_duration <= 1.0:
                raise RenderError("Muxed video is too short (< 1s); check timeline and inputs")

            if logger:
                logger.info(f"Muxed video duration: {mux_duration:.2f} seconds")
                if video_has_expected_codecs(paths.video_audio_mp4):
                    logger.info("✅ Codec check passed for video_audio.mp4")
                else:
                    logger.warning("Codec mismatch detected for video_audio.mp4")
            
            # Step 3: Final export with captions and professional encoding
            final_export(
                in_video=paths.video_audio_mp4,
                srt=paths.captions_srt if paths.captions_srt.exists() else None,
                out_final_mp4=paths.final_mp4,
                burn=burn_captions,
                config=config, logger=logger, project=project
            )
            
            # Get final video duration
            duration = _get_video_duration(paths.final_mp4)
            
            if logger:
                logger.info(f"Export complete video finished: {paths.final_mp4}")
                logger.info(f"Video duration: {duration:.2f} seconds")
            
            return duration
            
    except subprocess.CalledProcessError as e:
        stderr_tail = (e.stderr or "")[-800:]
        raise RenderError(f"Video export failed\n{stderr_tail}")
    except Exception as e:
        raise RenderError(f"Export error: {e}")


def final_export(in_video: Path, srt: Optional[Path], out_final_mp4: Path,
                burn: bool = False, config: Optional[Dict[str, Any]] = None,
                logger=None, project: str = "") -> float:
    """
    Final video export with subtitle handling and professional encoding.
    
    Args:
        in_video: Input video file (with audio)
        srt: SRT subtitle file (optional)
        out_final_mp4: Output final MP4 file
        burn: Whether to burn captions or attach as soft subs
        config: Project configuration
        logger: Logger instance
        project: Project name for logging
    
    Returns:
        Duration of the final video in seconds
    """
    
    if not in_video.exists():
        raise RenderError(f"Input video file not found: {in_video}")
    
    config = config or {}
    temp_outputs = []

    try:
        with Timer(logger, "final_export", project, "Final video export"):
            export_config = config.get("export", {})
            crf = export_config.get("crf", 18)
            preset = export_config.get("preset", "medium")

            styles = config.get("styles", {})
            caption_config = styles.get("caption", {})
            font_size = caption_config.get("font_size", 40)
            stroke_px = caption_config.get("stroke_px", 3)
            safe_bottom_pct = caption_config.get("safe_bottom_pct", 12)
            watermark_corner = None
            watermark_cfg = styles.get("watermark", {}) if styles else {}
            if watermark_cfg.get("enabled", False):
                watermark_corner = watermark_cfg.get("position", "bottom-right")

            working_video = in_video

            if srt and srt.exists():
                if burn:
                    temp_burned = out_final_mp4.with_suffix('.burn_temp.mp4')
                    burn_captions(
                        in_video,
                        srt,
                        temp_burned,
                        font=caption_config.get("font", "Arial"),
                        size=font_size,
                        outline=stroke_px,
                        safe_bottom_pct=safe_bottom_pct,
                        watermark_corner=watermark_corner
                    )
                    working_video = temp_burned
                    temp_outputs.append(temp_burned)
                else:
                    temp_subs = out_final_mp4.with_suffix('.subs_temp.mp4')
                    attach_soft_subs(in_video, srt, temp_subs)
                    working_video = temp_subs
                    temp_outputs.append(temp_subs)

            _encode_final_video(working_video, out_final_mp4, crf, preset)

            duration = _get_video_duration(out_final_mp4)

            if logger:
                logger.info(f"Final export completed: {out_final_mp4}")
                logger.info(f"Video duration: {duration:.2f} seconds")

            return duration

    except Exception as e:
        raise RenderError(f"Final export failed: {e}")
    finally:
        for temp_path in temp_outputs:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass


def _encode_final_video(in_video: Path, out_video: Path, crf: int, preset: str) -> None:
    """
    Encode final video with professional settings.
    
    Args:
        in_video: Input video file
        out_video: Output video file
        crf: Constant Rate Factor
        preset: Encoding preset
    """
    
    cmd = [
        "ffmpeg", "-y",
        "-i", str(in_video),
        "-c:v", "libx264",
        "-crf", str(crf),
        "-preset", preset,
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-colorspace", "bt709",
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "48000",
        "-ac", "2",
        str(out_video)
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        stderr_tail = (e.stderr or "")[-800:]
        raise RenderError(f"Video encoding failed\n{stderr_tail}")
    except Exception as e:
        raise RenderError(f"Video encoding error: {e}")


def _get_video_duration(video_path: Path) -> float:
    """
    Get video duration using ffprobe.
    
    Args:
        video_path: Path to video file
    
    Returns:
        Duration in seconds
    """
    
    cmd = [
        "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
        "-of", "csv=p=0", str(video_path)
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        duration_str = result.stdout.strip()
        if not duration_str:
            raise ValueError("Empty duration output")
        return float(duration_str)
    except subprocess.CalledProcessError as e:
        stderr_tail = (e.stderr or "")[-800:]
        raise RenderError(f"Failed to get video duration\n{stderr_tail}")
    except (ValueError, TypeError) as e:
        raise RenderError(f"Invalid duration value: {e}")


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
        raise RenderError(f"ffprobe failed\n{stderr_tail}")
    except json.JSONDecodeError as e:
        raise RenderError(f"Failed to parse video info JSON: {e}")
    except FileNotFoundError:
        raise RenderError("ffprobe not found. Please install FFmpeg.")


def video_has_expected_codecs(video_path: Path) -> bool:
    """
    Check if video has expected codecs (h264 + aac).
    
    Args:
        video_path: Path to video file
    
    Returns:
        True if video has h264 video and aac audio codecs
    """
    
    try:
        info = get_video_info(video_path)
        
        # Check for video and audio streams with expected codecs
        has_h264_video = False
        has_aac_audio = False
        
        for stream in info.get("streams", []):
            codec_name = stream.get("codec_name", "").lower()
            codec_type = stream.get("codec_type", "")
            
            if codec_type == "video" and codec_name == "h264":
                has_h264_video = True
            elif codec_type == "audio" and codec_name in ["aac", "mp4a"]:
                has_aac_audio = True
        
        return has_h264_video and has_aac_audio
        
    except Exception:
        return False


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


# Legacy functions for backward compatibility
def process_voice_audio(voice_path: Path, output_path: Path,
                       target_dbfs: float = -14.0) -> None:
    """
    Legacy function for backward compatibility.
    
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
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        stderr_tail = (e.stderr or "")[-800:]
        raise RenderError(f"Voice audio processing failed\n{stderr_tail}")
    except FileNotFoundError:
        raise RenderError("FFmpeg not found. Please install FFmpeg.")


def mix_audio_tracks(voice_path: Path, music_path: Path, output_path: Path,
                    voice_level: float = 0.0, music_level: float = -6.0) -> None:
    """
    Legacy function for backward compatibility.
    
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
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        stderr_tail = (e.stderr or "")[-800:]
        raise RenderError(f"Audio mixing failed\n{stderr_tail}")
    except FileNotFoundError:
        raise RenderError("FFmpeg not found. Please install FFmpeg.")
