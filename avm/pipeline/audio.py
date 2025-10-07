"""
Audio processing: normalization, music ducking, and mastering.
"""

import json
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

from .errors import RenderError


def process_audio(voice_wav: Path, music_wav: Optional[Path], 
                  output_voice: Path, output_music: Path,
                  config: Dict[str, Any], logger=None, project: str = "") -> Tuple[Path, Path]:
    """
    Process audio: two-pass loudnorm on voice, music ducking with sidechain compression.
    
    Args:
        voice_wav: Path to input voice audio (WAV)
        music_wav: Path to background music (optional)
        output_voice: Path to output normalized voice (48kHz stereo)
        output_music: Path to output ducked music
        config: Project configuration
        logger: Logger instance
        project: Project name for logging
    """
    
    if not voice_wav.exists():
        raise RenderError(f"Voice audio file not found: {voice_wav}")
    
    try:
        # Two-pass loudnorm on voice to I=-14, TP=-1.0, LRA=11; resample to 48kHz stereo
        _normalize_voice_two_pass(voice_wav, output_voice, config)

        # Determine reference duration from normalized voice
        voice_duration = _get_audio_duration(output_voice)

        # Process music if provided
        if music_wav and music_wav.exists():
            # Trim/loop to duration; apply volume preset; sidechain compress
            _process_music_with_ducking(
                music_wav,
                output_voice,
                output_music,
                voice_duration,
                config
            )
        else:
            # Just produce normalized voice, create silent music track
            _create_silent_audio(output_music, max(voice_duration, 0.1))
        
        # Return paths for normalized voice and ducked music
        return output_voice, output_music
            
    except Exception as e:
        raise RenderError(f"Audio processing failed: {e}")


def _normalize_voice_two_pass(voice_wav: Path, output_voice: Path, 
                             config: Dict[str, Any]) -> None:
    """
    Two-pass loudness normalization to I=-14, TP=-1.0, LRA=11; resample to 48kHz stereo.
    
    Args:
        voice_wav: Input voice audio
        output_voice: Output normalized voice
        config: Project configuration
    """
    
    audio_config = config.get("audio", {})
    target_i = audio_config.get("target_lufs", -14.0)
    target_tp = audio_config.get("target_tp", -1.0)
    target_lra = audio_config.get("target_lra", 11.0)
    
    # First pass: measure loudness
    measure_cmd = [
        "ffmpeg", "-y", "-i", str(voice_wav),
        "-af", f"loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra}:print_format=json",
        "-f", "null", "-"
    ]
    
    try:
        result = subprocess.run(measure_cmd, capture_output=True, text=True, check=True)
        
        # Parse measurement data from stderr
        measure_data = _parse_loudnorm_json(result.stderr)
        
        # Second pass: apply normalization with measurements
        apply_cmd = [
            "ffmpeg", "-y", "-i", str(voice_wav),
            "-af", (
                f"loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra}:"
                f"measured_I={measure_data['input_i']}:"
                f"measured_LRA={measure_data['input_lra']}:"
                f"measured_TP={measure_data['input_tp']}:"
                f"measured_thresh={measure_data['input_thresh']}:"
                f"offset={measure_data['target_offset']}:"
                f"linear=true,"
                f"aresample=48000,"
                f"aformat=channel_layouts=stereo"
            ),
            "-c:a", "pcm_s24le",
            str(output_voice)
        ]
        
        result = subprocess.run(apply_cmd, check=True, capture_output=True, text=True)
        
    except subprocess.CalledProcessError as e:
        stderr_tail = (e.stderr or "")[-800:]
        raise RenderError(f"Voice normalization failed\n{stderr_tail}")
    except Exception as e:
        raise RenderError(f"Voice normalization error: {e}")


def _parse_loudnorm_json(stderr: str) -> Dict[str, float]:
    """
    Parse loudnorm measurement output from stderr.
    
    Args:
        stderr: FFmpeg stderr output containing JSON
    
    Returns:
        Parsed measurement data
    """
    
    # Extract JSON from stderr
    json_start = stderr.find('{')
    json_end = stderr.rfind('}') + 1
    
    if json_start == -1 or json_end == 0:
        raise RenderError("Could not parse loudnorm measurement output")
    
    json_str = stderr[json_start:json_end]
    
    try:
        data = json.loads(json_str)
        return {
            "input_i": float(data["input_i"]),
            "input_lra": float(data["input_lra"]),
            "input_tp": float(data["input_tp"]),
            "input_thresh": float(data["input_thresh"]),
            "target_offset": float(data.get("target_offset", 0.0))
        }
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        raise RenderError(f"Invalid loudnorm JSON output: {e}")


def _process_music_with_ducking(music_wav: Path, voice_ref_wav: Path, output_music: Path,
                               duration: float, config: Dict[str, Any]) -> None:
    """
    Process music: trim/loop to duration, apply volume preset, sidechain compress with voice.
    
    Args:
        music_wav: Input music audio
        voice_ref_wav: Voice audio for sidechain detection (normalized voice)
        output_music: Output ducked music path
        duration: Target duration to match (seconds)
        config: Project configuration
    """
    
    audio_config = config.get("audio", {})
    ducking_config = audio_config.get("ducking", {})
    
    # Get configuration values with defaults
    music_db = audio_config.get("music_db", -28.0)  # Volume preset
    threshold = ducking_config.get("threshold", -20.0)  # Sidechain threshold
    ratio = ducking_config.get("ratio", 8.0)  # Compression ratio
    attack_ms = ducking_config.get("attack_ms", 50.0)  # Attack time
    release_ms = ducking_config.get("release_ms", 300.0)  # Release time
    
    # Guard against invalid duration values
    target_duration = max(duration, 0.1)

    # Create filter_complex for music processing
    filter_complex = (
        f"[0:a]aformat=channel_layouts=stereo,aresample=48000[voice];"
        f"[1:a]aformat=channel_layouts=stereo,aresample=48000,"
        f"volume={music_db}dB,"
        f"aloop=loop=-1:size=0,"
        f"atrim=0:{target_duration:.3f},"
        f"asetpts=N/SR/TB[music_trim];"
        f"[music_trim][voice]sidechaincompress="
        f"threshold={threshold}dB:ratio={ratio}:"
        f"attack={attack_ms}:release={release_ms}:makeup=0[ducked];"  # Sidechain compression
        f"[ducked]alimiter=limit=-1dB,aresample=48000,aformat=channel_layouts=stereo[out]"
    )
    
    cmd = [
        "ffmpeg", "-y",
        "-i", str(voice_ref_wav),  # Input 0: voice (for sidechain)
        "-i", str(music_wav),  # Input 1: music
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-c:a", "pcm_s24le",
        "-t", f"{target_duration:.3f}",
        str(output_music)
    ]
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        stderr_tail = (e.stderr or "")[-800:]
        raise RenderError(f"Music processing failed\n{stderr_tail}")
    except Exception as e:
        raise RenderError(f"Music processing error: {e}")


def _create_silent_audio(output_path: Path, duration: float) -> None:
    """
    Create a silent audio file of specified duration (48kHz stereo).
    
    Args:
        output_path: Output file path
        duration: Duration in seconds
    """
    
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-t", str(duration),
        "-c:a", "pcm_s24le",
        str(output_path)
    ]
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        stderr_tail = (e.stderr or "")[-800:]
        raise RenderError(f"Failed to create silent audio\n{stderr_tail}")
    except Exception as e:
        raise RenderError(f"Silent audio creation error: {e}")


def _get_audio_duration(audio_path: Path) -> float:
    """
    Get audio duration using ffprobe.
    
    Args:
        audio_path: Path to audio file
    
    Returns:
        Duration in seconds
    """
    
    cmd = [
        "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
        "-of", "csv=p=0", str(audio_path)
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        duration_str = result.stdout.strip()
        if not duration_str:
            raise ValueError("Empty duration output")
        return float(duration_str)
    except subprocess.CalledProcessError as e:
        stderr_tail = (e.stderr or "")[-800:]
        raise RenderError(f"Failed to get audio duration\n{stderr_tail}")
    except (ValueError, TypeError) as e:
        raise RenderError(f"Invalid duration value: {e}")


def measure_lufs(audio_path: Path, logger=None, project: str = "") -> Dict[str, float]:
    """
    Measure LUFS (Loudness Units Full Scale) using ffmpeg loudnorm.
    
    Args:
        audio_path: Path to audio file
        logger: Logger instance
        project: Project name for logging
    
    Returns:
        Dictionary with loudness measurements
    """
    
    cmd = [
        "ffmpeg", "-y", "-i", str(audio_path),
        "-af", "loudnorm=I=-23:TP=-2:LRA=7:print_format=json",
        "-f", "null", "-"
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        
        # Parse JSON from stderr
        json_start = result.stderr.find('{')
        json_end = result.stderr.rfind('}') + 1
        
        if json_start == -1 or json_end == 0:
            raise RenderError("Could not parse LUFS measurement output")
        
        json_str = result.stderr[json_start:json_end]
        data = json.loads(json_str)
        
        return {
            "input_i": float(data["input_i"]),
            "input_lra": float(data["input_lra"]),
            "input_tp": float(data["input_tp"]),
            "input_thresh": float(data["input_thresh"])
        }
        
    except subprocess.CalledProcessError as e:
        stderr_tail = (e.stderr or "")[-800:]
        raise RenderError(f"LUFS measurement failed\n{stderr_tail}")
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        raise RenderError(f"Invalid LUFS measurement data: {e}")
    except Exception as e:
        raise RenderError(f"LUFS measurement error: {e}")


def mix_voice_and_music(voice_wav: Path, music_wav: Path, output_wav: Path,
                       voice_level: float = 0.0, music_level: float = -6.0,
                       config: Optional[Dict[str, Any]] = None) -> None:
    """
    Mix voice and music tracks with specified levels.
    
    Args:
        voice_wav: Path to voice audio
        music_wav: Path to music audio
        output_wav: Path to output mixed audio
        voice_level: Voice level in dB (default: 0.0)
        music_level: Music level in dB (default: -6.0)
        config: Optional configuration
    """
    
    cmd = [
        "ffmpeg", "-y",
        "-i", str(voice_wav),
        "-i", str(music_wav),
        "-filter_complex", 
        f"[0:a]volume={voice_level}dB[voice];"
        f"[1:a]volume={music_level}dB[music];"
        f"[voice][music]amix=inputs=2:weights=1 1:duration=longest[out]",
        "-map", "[out]",
        "-c:a", "pcm_s24le",
        str(output_wav)
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        stderr_tail = (e.stderr or "")[-800:]
        raise RenderError(f"Audio mixing failed\n{stderr_tail}")
    except Exception as e:
        raise RenderError(f"Audio mixing error: {e}")


def apply_final_limiter(audio_path: Path, output_path: Path,
                       limit_db: float = -1.0) -> None:
    """
    Apply final limiter to prevent clipping.
    
    Args:
        audio_path: Input audio file
        output_path: Output limited audio file
        limit_db: Limiter threshold in dB (default: -1.0)
    """
    
    cmd = [
        "ffmpeg", "-y", "-i", str(audio_path),
        "-af", f"alimiter=limit={limit_db}dB:level=true:mode=compress",
        "-c:a", "pcm_s24le",
        str(output_path)
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        stderr_tail = (e.stderr or "")[-800:]
        raise RenderError(f"Final limiting failed\n{stderr_tail}")
    except Exception as e:
        raise RenderError(f"Final limiting error: {e}")


def resample_audio(input_path: Path, output_path: Path, 
                  sample_rate: int = 48000, channels: int = 2) -> None:
    """
    Resample audio to specified sample rate and channel count.
    
    Args:
        input_path: Input audio file
        output_path: Output resampled audio file
        sample_rate: Target sample rate (default: 48000)
        channels: Target channel count (default: 2 for stereo)
    """
    
    if channels == 2:
        channel_layout = "stereo"
    elif channels == 1:
        channel_layout = "mono"
    else:
        raise RenderError(f"Unsupported channel count: {channels}")
    
    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-af", f"aresample={sample_rate},aformat=channel_layouts={channel_layout}",
        "-c:a", "pcm_s24le",
        str(output_path)
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        stderr_tail = (e.stderr or "")[-800:]
        raise RenderError(f"Audio resampling failed\n{stderr_tail}")
    except Exception as e:
        raise RenderError(f"Audio resampling error: {e}")


# Legacy functions for backward compatibility
def normalize_audio(audio_path: Path, output_path: Path, 
                   target_lufs: float = -14.0) -> None:
    """
    Legacy function for backward compatibility.
    
    Args:
        audio_path: Input audio file
        output_path: Output normalized audio file
        target_lufs: Target LUFS level
    """
    
    config = {
        "audio": {
            "target_lufs": target_lufs,
            "target_tp": -1.0,
            "target_lra": 11.0
        }
    }
    
    _normalize_voice_two_pass(audio_path, output_path, config)


def duck_music(music_path: Path, voice_path: Path, output_path: Path,
               threshold: float = -20.0, ratio: float = 8.0,
               attack_ms: float = 50.0, release_ms: float = 300.0) -> None:
    """
    Legacy function for backward compatibility.
    
    Args:
        music_path: Input music file
        voice_path: Voice file for sidechain detection
        output_path: Output ducked music file
        threshold: Sidechain threshold
        ratio: Compression ratio
        attack_ms: Attack time in milliseconds
        release_ms: Release time in milliseconds
    """
    
    config = {
        "audio": {
            "music_db": -28.0,
            "ducking": {
                "threshold": threshold,
                "ratio": ratio,
                "attack_ms": attack_ms,
                "release_ms": release_ms
            }
        }
    }
    
    _process_music_with_ducking(music_path, voice_path, output_path, config)
