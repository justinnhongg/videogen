"""
Audio processing: normalization, music ducking, and mastering.
"""

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional, Tuple


def process_audio(audio_path: Path, music_path: Optional[Path],
                  output_voice: Path, output_music: Path,
                  config: Dict[str, Any], logger=None, project: str = "") -> None:
    """
    Process audio: normalize voice and duck music.
    
    Args:
        audio_path: Path to input voice audio
        music_path: Path to background music (optional)
        output_voice: Path to output normalized voice
        output_music: Path to output ducked music
        config: Project configuration
        logger: Logger instance
        project: Project name for logging
    """
    
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")
    
    # Normalize voice to target LUFS
    _normalize_voice(audio_path, output_voice, config)
    
    # Process music if provided
    if music_path and music_path.exists():
        _process_music(music_path, audio_path, output_music, config)
    else:
        # Create silent audio file
        _create_silent_audio(output_music, _get_audio_duration(audio_path))


def _normalize_voice(audio_path: Path, output_path: Path, 
                    config: Dict[str, Any]) -> None:
    """Normalize voice audio to target LUFS using two-pass loudnorm."""
    
    audio_config = config.get("audio", {})
    target_lufs = audio_config.get("target_lufs", -14.0)
    
    # First pass: measure
    measure_cmd = [
        "ffmpeg", "-y", "-i", str(audio_path),
        "-af", f"loudnorm=I={target_lufs}:TP=-1.0:LRA=11:print_format=json",
        "-f", "null", "-"
    ]
    
    try:
        result = subprocess.run(measure_cmd, capture_output=True, text=True, check=True)
        
        # Parse measurement data
        measure_data = _parse_loudnorm_output(result.stderr)
        
        # Second pass: apply normalization
        apply_cmd = [
            "ffmpeg", "-y", "-i", str(audio_path),
            "-af", (
                f"loudnorm=I={target_lufs}:TP=-1.0:LRA=11:"
                f"measured_I={measure_data['input_i']}:"
                f"measured_LRA={measure_data['input_lra']}:"
                f"measured_TP={measure_data['input_tp']}:"
                f"measured_thresh={measure_data['input_thresh']}:"
                f"linear=true"
            ),
            "-c:a", "pcm_s24le",
            str(output_path)
        ]
        
        subprocess.run(apply_cmd, check=True, capture_output=True)
        
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Voice normalization failed: {e}")


def _parse_loudnorm_output(stderr: str) -> Dict[str, float]:
    """Parse loudnorm measurement output from stderr."""
    
    # Extract JSON from stderr
    json_start = stderr.find('{')
    json_end = stderr.rfind('}') + 1
    
    if json_start == -1 or json_end == 0:
        raise ValueError("Could not parse loudnorm output")
    
    json_str = stderr[json_start:json_end]
    
    try:
        data = json.loads(json_str)
        return {
            "input_i": data["input_i"],
            "input_lra": data["input_lra"],
            "input_tp": data["input_tp"],
            "input_thresh": data["input_thresh"]
        }
    except (json.JSONDecodeError, KeyError) as e:
        raise ValueError(f"Invalid loudnorm JSON: {e}")


def _process_music(music_path: Path, voice_path: Path, output_path: Path,
                  config: Dict[str, Any]) -> None:
    """Process background music with sidechain ducking."""
    
    audio_config = config.get("audio", {})
    ducking_config = audio_config.get("ducking", {})
    
    music_db = audio_config.get("music_db", -28)
    threshold = ducking_config.get("threshold", -20)
    ratio = ducking_config.get("ratio", 8)
    attack_ms = ducking_config.get("attack_ms", 50)
    release_ms = ducking_config.get("release_ms", 300)
    
    # Get voice duration to loop/trim music
    voice_duration = _get_audio_duration(voice_path)
    
    # Create sidechain ducking filter
    filter_complex = (
        f"[0:a]aformat=channel_layouts=stereo,volume=1.0[lv];"
        f"[1:a]aformat=channel_layouts=stereo,volume={music_db}dB[lm];"
        f"[lm][lv]sidechaincompress=threshold={threshold}dB:ratio={ratio}:"
        f"attack={attack_ms}:release={release_ms}:makeup=0[mduck];"
        f"[lv]alimiter=limit=-1dB[lv2];"
        f"[mduck]alimiter=limit=-1dB[m2];"
        f"[lv2][m2]amix=inputs=2:weights=1 1:duration=longest[out]"
    )
    
    cmd = [
        "ffmpeg", "-y",
        "-i", str(voice_path),
        "-i", str(music_path),
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-c:a", "pcm_s24le",
        "-t", str(voice_duration),
        str(output_path)
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Music processing failed: {e}")


def _create_silent_audio(output_path: Path, duration: float) -> None:
    """Create a silent audio file of specified duration."""
    
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"anullsrc=channel_layout=stereo:sample_rate=48000",
        "-t", str(duration),
        "-c:a", "pcm_s24le",
        str(output_path)
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to create silent audio: {e}")


def _get_audio_duration(audio_path: Path) -> float:
    """Get audio duration using ffprobe."""
    
    cmd = [
        "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
        "-of", "csv=p=0", str(audio_path)
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError) as e:
        raise RuntimeError(f"Failed to get audio duration: {e}")


def mix_audio_tracks(voice_path: Path, music_path: Path, output_path: Path,
                    voice_level: float = 0.0, music_level: float = -6.0) -> None:
    """Mix voice and music tracks with specified levels."""
    
    cmd = [
        "ffmpeg", "-y",
        "-i", str(voice_path),
        "-i", str(music_path),
        "-filter_complex", 
        f"[0:a]volume={voice_level}dB[voice];"
        f"[1:a]volume={music_level}dB[music];"
        f"[voice][music]amix=inputs=2:weights=1 1:duration=longest[out]",
        "-map", "[out]",
        "-c:a", "aac", "-b:a", "192k",
        str(output_path)
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Audio mixing failed: {e}")


def apply_final_limiter(audio_path: Path, output_path: Path) -> None:
    """Apply final limiter to prevent clipping."""
    
    cmd = [
        "ffmpeg", "-y", "-i", str(audio_path),
        "-af", "alimiter=limit=-1dB:level=true:mode=compress",
        "-c:a", "aac", "-b:a", "192k",
        str(output_path)
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Final limiting failed: {e}")
