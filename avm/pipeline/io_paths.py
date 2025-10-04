"""
Path helpers and cache management for AVM pipeline.
"""

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Dict, Any, Optional, List, Union
from datetime import datetime


class ProjectPaths:
    """Manages file paths for a project."""
    
    def __init__(self, project_root: Path, slug: str):
        self.project_root = project_root
        self.slug = slug
        self.project_dir = project_root / "projects" / slug
        self.build_dir = self.project_dir / "build"
        self._slides_dir = self.build_dir / "slides"
        
        # Ensure all build directories exist
        self._ensure_build_directories()
    
    def _ensure_build_directories(self) -> None:
        """Create all necessary build directories."""
        directories = [
            self.build_dir,
            self._slides_dir,
            self.build_dir / "temp",  # For temporary files
            self.build_dir / "cache",  # For cache files
        ]
        
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
    
    @property
    def audio_wav(self) -> Path:
        """Path to input audio file."""
        return self.project_dir / "audio.wav"
    
    @property
    def slides_md(self) -> Path:
        """Path to slides markdown file."""
        return self.project_dir / "slides.md"
    
    @property
    def config_yml(self) -> Path:
        """Path to project config file."""
        return self.project_dir / "config.yml"
    
    @property
    def captions_srt(self) -> Path:
        """Path to captions SRT file."""
        return self.build_dir / "captions.srt"
    
    @property
    def captions_words_json(self) -> Path:
        """Path to word-level captions JSON."""
        return self.build_dir / "captions_words.json"
    
    @property
    def slides_dir(self) -> Path:
        """Path to slides directory."""
        return self._slides_dir
    
    @property
    def timeline_json(self) -> Path:
        """Path to timeline JSON."""
        return self.build_dir / "timeline.json"
    
    @property
    def video_nocap_mp4(self) -> Path:
        """Path to video without captions."""
        return self.build_dir / "video_nocap.mp4"
    
    @property
    def voice_norm_wav(self) -> Path:
        """Path to normalized voice audio."""
        return self.build_dir / "voice_norm.wav"
    
    @property
    def music_ducked_wav(self) -> Path:
        """Path to ducked music audio."""
        return self.build_dir / "music_ducked.wav"
    
    @property
    def final_mp4(self) -> Path:
        """Path to final video output."""
        return self.build_dir / "final.mp4"
    
    @property
    def thumb_png(self) -> Path:
        """Path to thumbnail."""
        return self.build_dir / "thumb.png"
    
    @property
    def manifest_json(self) -> Path:
        """Path to build manifest."""
        return self.build_dir / "manifest.json"
    
    @property
    def temp_dir(self) -> Path:
        """Path to temporary files directory."""
        return self.build_dir / "temp"
    
    @property
    def cache_dir(self) -> Path:
        """Path to cache directory."""
        return self.build_dir / "cache"
    
    def slide_png(self, slide_num: int) -> Path:
        """Path to a specific slide PNG."""
        return self._slides_dir / f"slide_{slide_num:03d}.png"
    
    def temp_file(self, name: str) -> Path:
        """Get path to a temporary file."""
        return self.temp_dir / name
    
    def cache_file(self, name: str) -> Path:
        """Get path to a cache file."""
        return self.cache_dir / name


def file_hash(file_path: Path) -> str:
    """Calculate SHA256 hash of a file."""
    if not file_path.exists():
        return ""
    
    sha256_hash = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    except (IOError, OSError):
        return ""


def config_hash(config: Dict[str, Any]) -> str:
    """Calculate hash of configuration for caching purposes."""
    # Create a deterministic string representation of config
    config_str = json.dumps(config, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(config_str.encode('utf-8')).hexdigest()


def file_mtime(file_path: Path) -> float:
    """Get file modification time, return 0 if file doesn't exist."""
    try:
        return file_path.stat().st_mtime
    except (OSError, FileNotFoundError):
        return 0.0


def is_file_newer(file_path: Path, reference_time: float) -> bool:
    """Check if file is newer than reference time."""
    return file_mtime(file_path) > reference_time


def load_manifest(build_dir: Path) -> Dict[str, Any]:
    """
    Load build manifest if it exists.
    
    Returns:
        Manifest dictionary with step information including timings and config hashes
    """
    manifest_path = build_dir / "manifest.json"
    if manifest_path.exists():
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError, UnicodeDecodeError):
            pass
    return {
        "created_at": datetime.now().isoformat(),
        "version": "1.0.0",
        "steps": {}
    }


def save_manifest(build_dir: Path, manifest: Dict[str, Any]) -> None:
    """
    Save build manifest with stage timings and config hash.
    
    Args:
        build_dir: Build directory path
        manifest: Manifest dictionary to save
    """
    manifest_path = build_dir / "manifest.json"
    
    # Ensure build directory exists
    build_dir.mkdir(parents=True, exist_ok=True)
    
    # Update metadata
    manifest["updated_at"] = datetime.now().isoformat()
    manifest["version"] = manifest.get("version", "1.0.0")
    
    try:
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
    except (IOError, OSError) as e:
        raise IOError(f"Failed to save manifest: {e}")


def should_skip_step(step_name: str, manifest: Dict[str, Any], 
                    input_files: List[Path], output_files: List[Path] = None,
                    config_hash: str = None, force: bool = False) -> bool:
    """
    Determine if a pipeline step should be skipped due to caching.
    
    Uses file modification times and content hashing (SHA256) for cache validation.
    
    Args:
        step_name: Name of the pipeline step
        manifest: Build manifest dictionary
        input_files: List of input file paths
        output_files: List of output file paths (optional)
        config_hash: Configuration hash for this step (optional)
        force: Force recomputation even if cached
        
    Returns:
        True if step should be skipped, False if it should run
    """
    if force:
        return False
    
    steps = manifest.get("steps", {})
    if step_name not in steps:
        return False
    
    step_info = steps[step_name]
    
    # Check if any input files are missing or newer than cached versions
    cached_input_hashes = step_info.get("input_hashes", {})
    cached_input_mtimes = step_info.get("input_mtimes", {})
    
    for file_path in input_files:
        file_str = str(file_path)
        
        # Check if file exists
        if not file_path.exists():
            return False
        
        # Check modification time (fast check)
        current_mtime = file_mtime(file_path)
        cached_mtime = cached_input_mtimes.get(file_str, 0.0)
        
        if current_mtime > cached_mtime:
            return False
        
        # Check content hash (thorough check)
        current_hash = file_hash(file_path)
        cached_hash = cached_input_hashes.get(file_str, "")
        
        if current_hash != cached_hash:
            return False
    
    # Check if all output files exist and are newer than inputs
    if output_files:
        latest_input_mtime = max((file_mtime(f) for f in input_files if f.exists()), default=0.0)
        
        for output_file in output_files:
            if not output_file.exists():
                return False
            
            # Output should be newer than all inputs
            if file_mtime(output_file) <= latest_input_mtime:
                return False
    
    # Check configuration hash if provided
    if config_hash:
        cached_config_hash = step_info.get("config_hash", "")
        if config_hash != cached_config_hash:
            return False
    
    return True


def update_manifest_step(manifest: Dict[str, Any], step_name: str, 
                        input_files: List[Path], output_files: List[Path],
                        duration_ms: float, config_hash: str = None) -> None:
    """
    Update manifest with step completion info including timings and config hash.
    
    Args:
        manifest: Manifest dictionary to update
        step_name: Name of the pipeline step
        input_files: List of input file paths
        output_files: List of output file paths
        duration_ms: Duration of the step in milliseconds
        config_hash: Configuration hash for this step (optional)
    """
    # Calculate hashes and modification times for input files
    input_hashes = {}
    input_mtimes = {}
    for file_path in input_files:
        if file_path.exists():
            file_str = str(file_path)
            input_hashes[file_str] = file_hash(file_path)
            input_mtimes[file_str] = file_mtime(file_path)
    
    # Calculate hashes and modification times for output files
    output_hashes = {}
    output_mtimes = {}
    for file_path in output_files:
        if file_path.exists():
            file_str = str(file_path)
            output_hashes[file_str] = file_hash(file_path)
            output_mtimes[file_str] = file_mtime(file_path)
    
    # Ensure steps dictionary exists
    if "steps" not in manifest:
        manifest["steps"] = {}
    
    # Update step information
    manifest["steps"][step_name] = {
        "completed_at": datetime.now().isoformat(),
        "input_files": [str(f) for f in input_files],
        "output_files": [str(f) for f in output_files],
        "input_hashes": input_hashes,
        "output_hashes": output_hashes,
        "input_mtimes": input_mtimes,
        "output_mtimes": output_mtimes,
        "duration_ms": duration_ms,
        "config_hash": config_hash or "",
        "status": "completed"
    }


def clean_temp_files(build_dir: Path, max_age_hours: int = 24) -> None:
    """
    Clean up old temporary files.
    
    Args:
        build_dir: Build directory path
        max_age_hours: Maximum age of temp files in hours
    """
    temp_dir = build_dir / "temp"
    if not temp_dir.exists():
        return
    
    current_time = time.time()
    max_age_seconds = max_age_hours * 3600
    
    for file_path in temp_dir.iterdir():
        if file_path.is_file():
            try:
                file_age = current_time - file_path.stat().st_mtime
                if file_age > max_age_seconds:
                    file_path.unlink()
            except (OSError, FileNotFoundError):
                # Ignore errors when cleaning up
                pass


def get_build_summary(build_dir: Path) -> Dict[str, Any]:
    """
    Get summary of build artifacts and their status.
    
    Args:
        build_dir: Build directory path
        
    Returns:
        Dictionary with build summary information
    """
    manifest = load_manifest(build_dir)
    steps = manifest.get("steps", {})
    
    summary = {
        "build_dir": str(build_dir),
        "total_steps": len(steps),
        "completed_steps": len([s for s in steps.values() if s.get("status") == "completed"]),
        "total_duration_ms": sum(s.get("duration_ms", 0) for s in steps.values()),
        "last_updated": manifest.get("updated_at", "never"),
        "steps": {}
    }
    
    for step_name, step_info in steps.items():
        summary["steps"][step_name] = {
            "status": step_info.get("status", "unknown"),
            "duration_ms": step_info.get("duration_ms", 0),
            "completed_at": step_info.get("completed_at", "unknown"),
            "output_count": len(step_info.get("output_files", []))
        }
    
    return summary


def validate_build_artifacts(build_dir: Path) -> Dict[str, List[str]]:
    """
    Validate that build artifacts are consistent with manifest.
    
    Args:
        build_dir: Build directory path
        
    Returns:
        Dictionary with validation results (missing files, corrupted files, etc.)
    """
    manifest = load_manifest(build_dir)
    steps = manifest.get("steps", {})
    
    results = {
        "missing_files": [],
        "corrupted_files": [],
        "stale_files": []
    }
    
    for step_name, step_info in steps.items():
        if step_info.get("status") != "completed":
            continue
        
        # Check output files
        output_files = step_info.get("output_files", [])
        cached_hashes = step_info.get("output_hashes", {})
        
        for file_str in output_files:
            file_path = Path(file_str)
            
            # Check if file exists
            if not file_path.exists():
                results["missing_files"].append(file_str)
                continue
            
            # Check if file hash matches
            current_hash = file_hash(file_path)
            cached_hash = cached_hashes.get(file_str, "")
            
            if current_hash != cached_hash:
                results["corrupted_files"].append(file_str)
    
    return results