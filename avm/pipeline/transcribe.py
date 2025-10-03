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
    return FASTER_WHISPER_AVAILABLE or OPENAI_WHISPER_AVAILABLE


def transcribe_audio(audio_path: Path, output_srt: Path, output_words: Path,
                    model_size: str = "small", language: Optional[str] = None,
                    use_gpu: bool = False, threads: int = 4,
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
        if FASTER_WHISPER_AVAILABLE:
            _transcribe_with_faster_whisper(
                audio_path, output_srt, output_words, 
                model_size, language, use_gpu, threads
            )
        else:
            _transcribe_with_openai_whisper(
                audio_path, output_srt, output_words,
                model_size, language, use_gpu
            )


def _transcribe_with_faster_whisper(audio_path: Path, output_srt: Path, 
                                   output_words: Path, model_size: str,
                                   language: Optional[str], use_gpu: bool,
                                   threads: int) -> None:
    """Transcribe using faster-whisper."""
    
    device = "cuda" if use_gpu else "cpu"
    compute_type = "float16" if use_gpu else "int8"
    
    try:
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
        
        # Transcribe with word-level timestamps
        segments, info = model.transcribe(
            str(audio_path),
            language=language,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500)
        )
        
        # Convert to SRT format
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
                        "probability": word.probability
                    })
        
        # Write SRT file
        with open(output_srt, 'w', encoding='utf-8') as f:
            f.write('\n'.join(srt_content))
        
        # Write word-level JSON
        with open(output_words, 'w', encoding='utf-8') as f:
            json.dump({
                "language": info.language,
                "language_probability": info.language_probability,
                "duration": info.duration,
                "words": word_data
            }, f, indent=2)
            
    except Exception as e:
        raise TranscriptionError(f"Faster-whisper transcription failed: {e}")


def _transcribe_with_openai_whisper(audio_path: Path, output_srt: Path,
                                   output_words: Path, model_size: str,
                                   language: Optional[str], use_gpu: bool) -> None:
    """Transcribe using OpenAI Whisper."""
    
    try:
        model = whisper.load_model(model_size)
        
        # Transcribe
        result = model.transcribe(
            str(audio_path),
            language=language,
            word_timestamps=True
        )
        
        # Convert to SRT format
        srt_content = []
        word_data = []
        
        for i, segment in enumerate(result["segments"], 1):
            start_time = _format_srt_time(segment["start"])
            end_time = _format_srt_time(segment["end"])
            
            srt_content.append(f"{i}\n{start_time} --> {end_time}\n{segment['text'].strip()}\n")
            
            # Collect word-level data
            if "words" in segment:
                for word in segment["words"]:
                    word_data.append({
                        "word": word["word"],
                        "start": word["start"],
                        "end": word["end"],
                        "probability": word.get("probability", 1.0)
                    })
        
        # Write SRT file
        with open(output_srt, 'w', encoding='utf-8') as f:
            f.write('\n'.join(srt_content))
        
        # Write word-level JSON
        with open(output_words, 'w', encoding='utf-8') as f:
            json.dump({
                "language": result.get("language", "unknown"),
                "language_probability": 1.0,
                "duration": result.get("duration", 0),
                "words": word_data
            }, f, indent=2)
            
    except Exception as e:
        raise TranscriptionError(f"OpenAI Whisper transcription failed: {e}")


def _format_srt_time(seconds: float) -> str:
    """Format time in seconds to SRT format (HH:MM:SS,mmm)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millisecs = int((seconds % 1) * 1000)
    
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millisecs:03d}"


def get_audio_duration(audio_path: Path) -> float:
    """Get audio duration using ffprobe."""
    try:
        cmd = [
            "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
            "-of", "csv=p=0", str(audio_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError) as e:
        raise TranscriptionError(f"Failed to get audio duration: {e}")


def normalize_wav(input_path: Path, output_path: Path, target_dbfs: float = -14.0) -> None:
    """Normalize WAV file to target dBFS using pydub."""
    if not PYDUB_AVAILABLE:
        raise TranscriptionError("pydub is required for audio normalization")
    
    if not input_path.exists():
        raise TranscriptionError(f"Input file not found: {input_path}")
    
    try:
        # Load audio
        audio = AudioSegment.from_wav(str(input_path))
        
        # Normalize to target dBFS
        normalized = audio.normalize(headroom=0.1)
        normalized = normalized.apply_gain(target_dbfs - normalized.dBFS)
        
        # Export as WAV
        normalized.export(str(output_path), format="wav")
        
    except Exception as e:
        raise TranscriptionError(f"Audio normalization failed: {e}")


def run_whisper(path_wav: Path, out_srt: Path, out_json: Optional[Path] = None,
                model: str = "small", language: Optional[str] = None,
                use_gpu: bool = False, threads: int = 4) -> None:
    """Run Whisper transcription via shell command."""
    
    if not path_wav.exists():
        raise TranscriptionError(f"Audio file not found: {path_wav}")
    
    # Check which Whisper implementation to use
    if FASTER_WHISPER_AVAILABLE:
        _run_faster_whisper_shell(path_wav, out_srt, out_json, model, language, use_gpu, threads)
    elif OPENAI_WHISPER_AVAILABLE:
        _run_openai_whisper_shell(path_wav, out_srt, out_json, model, language)
    else:
        raise TranscriptionError("No Whisper implementation available")


def _run_faster_whisper_shell(path_wav: Path, out_srt: Path, out_json: Optional[Path],
                             model: str, language: Optional[str], use_gpu: bool, threads: int) -> None:
    """Run faster-whisper via shell command."""
    
    device = "cuda" if use_gpu else "cpu"
    compute_type = "float16" if use_gpu else "int8"
    
    cmd = [
        sys.executable, "-c", f"""
import sys
sys.path.insert(0, '.')
from faster_whisper import WhisperModel
import json
import srt

model = WhisperModel('{model}', device='{device}', compute_type='{compute_type}')
segments, info = model.transcribe('{path_wav}', language='{language or "auto"}', word_timestamps=True)

# Convert to SRT
srt_content = []
word_data = []

for i, segment in enumerate(segments, 1):
    start_time = srt.timedelta(seconds=segment.start)
    end_time = srt.timedelta(seconds=segment.end)
    
    srt_content.append(srt.Subtitle(i, start_time, end_time, segment.text.strip()))
    
    # Collect word data
    if hasattr(segment, 'words'):
        for word in segment.words:
            word_data.append({{
                'word': word.word,
                'start': word.start,
                'end': word.end,
                'probability': word.probability
            }})

# Write SRT
with open('{out_srt}', 'w', encoding='utf-8') as f:
    f.write(srt.compose(srt_content))

# Write JSON if requested
{f"with open('{out_json}', 'w', encoding='utf-8') as f: json.dump({{'language': info.language, 'duration': info.duration, 'words': word_data}}, f, indent=2)" if out_json else "pass"}
"""
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise TranscriptionError(f"Faster-whisper shell command failed: {e}")


def _run_openai_whisper_shell(path_wav: Path, out_srt: Path, out_json: Optional[Path],
                             model: str, language: Optional[str]) -> None:
    """Run OpenAI Whisper via shell command."""
    
    cmd = [
        sys.executable, "-c", f"""
import sys
sys.path.insert(0, '.')
import whisper
import json
import srt

model = whisper.load_model('{model}')
result = model.transcribe('{path_wav}', language='{language or None}', word_timestamps=True)

# Convert to SRT
srt_content = []
word_data = []

for i, segment in enumerate(result['segments'], 1):
    start_time = srt.timedelta(seconds=segment['start'])
    end_time = srt.timedelta(seconds=segment['end'])
    
    srt_content.append(srt.Subtitle(i, start_time, end_time, segment['text'].strip()))
    
    # Collect word data
    if 'words' in segment:
        for word in segment['words']:
            word_data.append({{
                'word': word['word'],
                'start': word['start'],
                'end': word['end'],
                'probability': word.get('probability', 1.0)
            }})

# Write SRT
with open('{out_srt}', 'w', encoding='utf-8') as f:
    f.write(srt.compose(srt_content))

# Write JSON if requested
{f"with open('{out_json}', 'w', encoding='utf-8') as f: json.dump({{'language': result.get('language', 'unknown'), 'duration': result.get('duration', 0), 'words': word_data}}, f, indent=2)" if out_json else "pass"}
"""
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise TranscriptionError(f"OpenAI Whisper shell command failed: {e}")
