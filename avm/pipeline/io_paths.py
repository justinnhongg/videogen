"""
Path helpers and cache management for AVM pipeline.
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Dict, Any, Optional


class ProjectPaths:
    """Manages file paths for a project."""
    
    def __init__(self, project_root: Path, slug: str):
        self.project_root = project_root
        self.slug = slug
        self.project_dir = project_root / "projects" / slug
        self.build_dir = self.project_dir / "build"
        self.slides_dir = self.build_dir / "slides"
        
        # Ensure directories exist
        self.build_dir.mkdir(parents=True, exist_ok=True)
        self.slides_dir.mkdir(parents=True, exist_ok=True)
    
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
    
    def slide_png(self, slide_num: int) -> Path:
        """Path to a specific slide PNG."""
        return self.slides_dir / f"slide_{slide_num:03d}.png"


def file_hash(file_path: Path) -> str:
    """Calculate SHA256 hash of a file."""
    if not file_path.exists():
        return ""
    
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def is_file_modified(file_path: Path, cached_hash: str) -> bool:
    """Check if a file has been modified since last cached."""
    if not file_path.exists():
        return True
    
    current_hash = file_hash(file_path)
    return current_hash != cached_hash


def load_manifest(build_dir: Path) -> Dict[str, Any]:
    """Load build manifest if it exists."""
    manifest_path = build_dir / "manifest.json"
    if manifest_path.exists():
        try:
            with open(manifest_path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_manifest(build_dir: Path, manifest: Dict[str, Any]) -> None:
    """Save build manifest."""
    manifest_path = build_dir / "manifest.json"
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)


def should_skip_step(step_name: str, manifest: Dict[str, Any], 
                    input_files: list[Path], force: bool = False) -> bool:
    """Determine if a pipeline step should be skipped due to caching."""
    if force:
        return False
    
    if step_name not in manifest:
        return False
    
    step_info = manifest[step_name]
    
    # Check if input files have changed
    for file_path in input_files:
        if not file_path.exists():
            return False
        
        cached_hash = step_info.get("input_hashes", {}).get(str(file_path))
        if cached_hash is None or is_file_modified(file_path, cached_hash):
            return False
    
    return True


def update_manifest_step(manifest: Dict[str, Any], step_name: str, 
                        input_files: list[Path], output_files: list[Path],
                        duration_ms: float) -> None:
    """Update manifest with step completion info."""
    input_hashes = {str(f): file_hash(f) for f in input_files if f.exists()}
    output_hashes = {str(f): file_hash(f) for f in output_files if f.exists()}
    
    manifest[step_name] = {
        "completed_at": str(Path().cwd()),
        "input_hashes": input_hashes,
        "output_hashes": output_hashes,
        "duration_ms": duration_ms
    }
