"""
Audio transcription using Whisper/faster-whisper.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional

try:
    from faster_whisper import WhisperModel
    FASTER_WHISPER_AVAILABLE = True
except ImportError:
    FASTER_WHISPER_AVAILABLE = False

try:
    import whisper
    OPENAI_WHISPER_AVAILABLE = True
except ImportError:
    OPENAI_WHISPER_AVAILABLE = False

try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False

from .errors import TranscriptionError
from .logging import Timer


def check_whisper_availability() -> bool:
    """Check if any Whisper implementation is available."""
    # Check for faster-whisper or openai-whisper imports
    if FASTER_WHISPER_AVAILABLE or OPENAI_WHISPER_AVAILABLE:
        return True
    
    # Check for whisper CLI
    try:
        result = subprocess.run(['whisper', '--help'], 
                              capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def normalize_wav(in_path: Path, out_path: Path, target_dbfs: float = -14.0) -> None:
    """
    Normalize WAV file using pydub; mono 48kHz enforced.
    
    Args:
        in_path: Input audio file path
        out_path: Output normalized audio file path
        target_dbfs: Target dBFS level (default: -14.0)
    """
    if not PYDUB_AVAILABLE:
        raise TranscriptionError("pydub is required for audio normalization. Install with: pip install pydub")
    
    if not in_path.exists():
        raise TranscriptionError(f"Input file not found: {in_path}")
    
    try:
        # Load audio
        audio = AudioSegment.from_file(str(in_path))
        
        # Convert to mono if stereo
        if audio.channels > 1:
            audio = audio.set_channels(1)
        
        # Resample to 48kHz if needed
        if audio.frame_rate != 48000:
            audio = audio.set_frame_rate(48000)
        
        # Normalize to target dBFS
        normalized = audio.normalize(headroom=0.1)
        gain_needed = target_dbfs - normalized.dBFS
        normalized = normalized.apply_gain(gain_needed)
        
        # Export as WAV with specific parameters
        normalized.export(
            str(out_path), 
            format="wav",
            parameters=["-ac", "1", "-ar", "48000"]  # Force mono, 48kHz
        )
        
    except Exception as e:
        raise TranscriptionError(f"Audio normalization failed: {e}")


def run_whisper(audio_wav: Path, out_srt: Path, out_words_json: Path, 
                model_size: str, language: Optional[str], use_gpu: bool, threads: int = 0) -> None:
    """
    Run Whisper transcription.
    
    Prefers faster-whisper if installed; else shells out to openai-whisper CLI.
    Writes SRT and words JSON: [{"word":"...", "start":s, "end":e, "prob":p}]
    
    Args:
        audio_wav: Input audio file path
        out_srt: Output SRT file path
        out_words_json: Output words JSON file path
        model_size: Whisper model size (tiny, base, small, medium, large-v3)
        language: Language code (None for auto-detect)
        use_gpu: Whether to use GPU acceleration
    """
    if not audio_wav.exists():
        raise TranscriptionError(f"Audio file not found: {audio_wav}")
    
    if not check_whisper_availability():
        raise TranscriptionError(
            "No Whisper implementation available. Install faster-whisper or openai-whisper."
        )
    
    # Prefer faster-whisper if available
    if FASTER_WHISPER_AVAILABLE:
        _run_faster_whisper(audio_wav, out_srt, out_words_json, model_size, language, use_gpu, threads)
    else:
        _run_openai_whisper_shell(audio_wav, out_srt, out_words_json, model_size, language, threads)


def _run_faster_whisper(audio_wav: Path, out_srt: Path, out_words_json: Path,
                       model_size: str, language: Optional[str], use_gpu: bool, threads: int = 0) -> None:
    """Run faster-whisper directly."""
    
    device = "cuda" if use_gpu else "cpu"
    compute_type = "float16" if use_gpu else "int8"
    
    try:
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
        
        # Transcribe with word-level timestamps
        segments, info = model.transcribe(
            str(audio_wav),
            language=language,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
            num_workers=threads if threads > 0 else 1
        )
        
        # Convert to SRT format and collect word data
        srt_content = []
        word_data = []
        
        for i, segment in enumerate(segments, 1):
            start_time = _format_srt_time(segment.start)
            end_time = _format_srt_time(segment.end)
            
            srt_content.append(f"{i}\n{start_time} --> {end_time}\n{segment.text.strip()}\n")
            
            # Collect word-level data
            if hasattr(segment, 'words'):
                for word in segment.words:
                    word_data.append({
                        "word": word.word,
                        "start": word.start,
                        "end": word.end,
                        "prob": word.probability
                    })
        
        # Write SRT file
        with open(out_srt, 'w', encoding='utf-8') as f:
            f.write('\n'.join(srt_content))
        
        # Write words JSON
        with open(out_words_json, 'w', encoding='utf-8') as f:
            json.dump(word_data, f, indent=2)
            
    except Exception as e:
        raise TranscriptionError(f"Faster-whisper transcription failed: {e}")


def _run_openai_whisper_shell(audio_wav: Path, out_srt: Path, out_words_json: Path,
                             model_size: str, language: Optional[str], threads: int = 0) -> None:
    """Run OpenAI Whisper via shell command with word timing synthesis."""
    
    # First try to use whisper CLI directly
    try:
        cmd = ["whisper", str(audio_wav), "--model", model_size, "--output_format", "srt"]
        if language:
            cmd.extend(["--language", language])
        if threads > 0:
            cmd.extend(["--threads", str(threads)])
        
        # Run whisper CLI
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        
        # The CLI creates a .srt file with the same name as input
        expected_srt = audio_wav.with_suffix('.srt')
        if expected_srt.exists():
            # Move to our output location
            expected_srt.rename(out_srt)
        
        # Generate word-level timing by synthesizing from SRT segments
        _synthesize_word_timings(out_srt, out_words_json)
        
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Fallback to Python script if CLI not available
        _run_openai_whisper_python_script(audio_wav, out_srt, out_words_json, model_size, language, threads)


def _run_openai_whisper_python_script(audio_wav: Path, out_srt: Path, out_words_json: Path,
                                     model_size: str, language: Optional[str], threads: int) -> None:
    """Run OpenAI Whisper using Python script as fallback."""
    
    script_content = f'''
import sys
import json
import whisper
import re

def format_time(seconds):
    """Format time for SRT."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millisecs = int((seconds % 1) * 1000)
    return f"{{hours:02d}}:{{minutes:02d}}:{{secs:02d}},{{millisecs:03d}}"

try:
    # Load model
    model = whisper.load_model("{model_size}")
    
    # Transcribe with word timestamps if available
    result = model.transcribe("{audio_wav}", language="{language or None}", word_timestamps=True)
    
    # Generate SRT content
    srt_content = []
    word_data = []
    
    for i, segment in enumerate(result["segments"], 1):
        start_time = format_time(segment["start"])
        end_time = format_time(segment["end"])
        text = segment["text"].strip()
        
        srt_content.append(f"{{i}}\\n{{start_time}} --> {{end_time}}\\n{{text}}\\n")
        
        # Collect word data - synthesize if not available
        if "words" in segment and segment["words"]:
            for word in segment["words"]:
                word_data.append({{
                    "word": word["word"],
                    "start": word["start"],
                    "end": word["end"],
                    "prob": word.get("probability", 1.0)
                }})
        else:
            # Synthesize word timings from segment text
            words = re.findall(r'\\S+', text)
            if words:
                segment_duration = segment["end"] - segment["start"]
                word_duration = segment_duration / len(words)
                
                for j, word in enumerate(words):
                    word_start = segment["start"] + (j * word_duration)
                    word_end = word_start + word_duration
                    word_data.append({{
                        "word": word,
                        "start": word_start,
                        "end": word_end,
                        "prob": 1.0
                    }})
    
    # Write SRT
    with open("{out_srt}", "w", encoding="utf-8") as f:
        f.write("\\n".join(srt_content))
    
    # Write words JSON
    with open("{out_words_json}", "w", encoding="utf-8") as f:
        json.dump(word_data, f, indent=2)
        
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)
'''
    
    try:
        result = subprocess.run([
            sys.executable, "-c", script_content
        ], check=True, capture_output=True, text=True)
        
    except subprocess.CalledProcessError as e:
        error_msg = f"OpenAI Whisper Python script failed: {e}"
        if e.stderr:
            error_msg += f"\nError output: {e.stderr}"
        raise TranscriptionError(error_msg)
    except FileNotFoundError:
        raise TranscriptionError("Python interpreter not found for Whisper execution.")


def _synthesize_word_timings(srt_path: Path, words_json_path: Path) -> None:
    """Synthesize word-level timings from SRT segments."""
    import re
    
    word_data = []
    
    with open(srt_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Parse SRT segments
    segments = re.split(r'\n\s*\n', content.strip())
    
    for segment in segments:
        lines = segment.strip().split('\n')
        if len(lines) >= 3:
            # Parse timing
            timing_line = lines[1]
            time_match = re.match(r'(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})', timing_line)
            if time_match:
                start_time = _parse_srt_time(time_match.group(1))
                end_time = _parse_srt_time(time_match.group(2))
                text = ' '.join(lines[2:]).strip()
                
                # Split text into words and distribute timing
                words = re.findall(r'\S+', text)
                if words:
                    segment_duration = end_time - start_time
                    word_duration = segment_duration / len(words)
                    
                    for i, word in enumerate(words):
                        word_start = start_time + (i * word_duration)
                        word_end = word_start + word_duration
                        word_data.append({
                            "word": word,
                            "start": word_start,
                            "end": word_end,
                            "prob": 1.0
                        })
    
    # Write words JSON
    with open(words_json_path, 'w', encoding='utf-8') as f:
        json.dump(word_data, f, indent=2)


def _parse_srt_time(time_str: str) -> float:
    """Parse SRT time format to seconds."""
    time_part, ms_part = time_str.split(',')
    hours, minutes, seconds = map(int, time_part.split(':'))
    milliseconds = int(ms_part)
    
    total_seconds = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0
    return total_seconds


def _format_srt_time(seconds: float) -> str:
    """Format time in seconds to SRT format (HH:MM:SS,mmm)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millisecs = int((seconds % 1) * 1000)
    
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millisecs:03d}"


def get_audio_duration(audio_wav: Path) -> float:
    """
    Get audio duration via ffprobe JSON output.
    
    Args:
        audio_wav: Path to audio file
        
    Returns:
        Duration in seconds
    """
    try:
        cmd = [
            "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
            "-of", "json", str(audio_wav)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        
        # Parse JSON output
        data = json.loads(result.stdout)
        duration = float(data["format"]["duration"])
        
        if duration <= 0:
            raise TranscriptionError(f"Invalid audio duration: {duration}")
        return duration
        
    except subprocess.CalledProcessError as e:
        error_msg = f"ffprobe failed: {e}"
        if e.stderr:
            error_msg += f"\nffprobe error: {e.stderr.decode('utf-8', errors='ignore')}"
        raise TranscriptionError(error_msg)
    except (ValueError, KeyError, json.JSONDecodeError) as e:
        raise TranscriptionError(f"Failed to parse audio duration: {e}")
    except FileNotFoundError:
        raise TranscriptionError("ffprobe not found. Please install FFmpeg.")


def transcribe_audio(audio_path: Path, output_srt: Path, output_words: Path,
                    model_size: str = "small", language: Optional[str] = None,
                    use_gpu: bool = False, threads: int = 0,
                    logger=None, project: str = "") -> None:
    """
    Transcribe audio file to SRT and word-level JSON.
    
    Args:
        audio_path: Path to input audio file
        output_srt: Path to output SRT file
        output_words: Path to output word-level JSON file
        model_size: Whisper model size (tiny, base, small, medium, large-v3)
        language: Language code (auto-detect if None)
        use_gpu: Whether to use GPU acceleration
        threads: Number of threads for CPU processing
        logger: Logger instance
        project: Project name for logging
    """
    
    if not audio_path.exists():
        raise TranscriptionError(f"Audio file not found: {audio_path}")
    
    if not check_whisper_availability():
        raise TranscriptionError(
            "No Whisper implementation available. Install faster-whisper or openai-whisper."
        )
    
    with Timer(logger, "transcribe", project, f"Transcribing {audio_path.name}"):
        # Normalize audio first
        normalized_audio = audio_path.parent / "audio_normalized.wav"
        normalize_wav(audio_path, normalized_audio, target_dbfs=-14.0)
        
        # Run transcription
        run_whisper(
            normalized_audio, output_srt, output_words,
            model_size, language, use_gpu, threads
        )
        
        # Clean up normalized audio
        if normalized_audio.exists() and normalized_audio != audio_path:
            normalized_audio.unlink()


# Legacy function for backward compatibility
def transcribe_with_cache(audio_path: Path, output_srt: Path, output_words: Path,
                         model_size: str = "small", language: Optional[str] = None,
                         use_gpu: bool = False, threads: int = 0, force: bool = False,
                         logger=None, project: str = "") -> None:
    """
    Transcribe with caching support.
    
    Args:
        audio_path: Path to input audio file
        output_srt: Path to output SRT file
        output_words: Path to output word-level JSON file
        model_size: Whisper model size
        language: Language code
        use_gpu: Whether to use GPU
        force: Force recomputation even if cached
        logger: Logger instance
        project: Project name
    """
    
    # Check cache if not forcing
    if not force and output_srt.exists() and output_words.exists():
        # Check if audio file is newer than outputs
        audio_mtime = audio_path.stat().st_mtime if audio_path.exists() else 0
        srt_mtime = output_srt.stat().st_mtime
        json_mtime = output_words.stat().st_mtime
        
        if audio_mtime < min(srt_mtime, json_mtime):
            if logger:
                logger.info(f"Transcription cache is up-to-date for {audio_path.name}")
            return
    
    # Run transcription
    transcribe_audio(
        audio_path, output_srt, output_words,
        model_size, language, use_gpu, threads, logger=logger, project=project
    )