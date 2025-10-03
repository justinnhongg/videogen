#!/usr/bin/env python3
"""
AVM - Audio to Video Maker CLI

Convert narrated lessons into polished YouTube videos with captions, 
watermarks, and professional motion graphics.
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

# Add the avm package to path
sys.path.insert(0, str(Path(__file__).parent))

from avm.pipeline import (
    AVMError, TranscriptionError, RenderError, MuxError, ConfigError
)
from avm.pipeline.logging import setup_logging, Timer
from avm.pipeline.io_paths import ProjectPaths, load_manifest, save_manifest, should_skip_step, update_manifest_step
from avm.pipeline.transcribe import (
    normalize_wav, run_whisper, check_whisper_availability, get_audio_duration
)
from avm.pipeline.slides import render_slides, check_playwright_installation
from avm.pipeline.assemble import assemble_video, get_slide_durations_from_timeline, create_simple_timeline
from avm.pipeline.export import export_complete_video
from avm.pipeline.thumb import generate_thumbnail

import yaml


def load_project_config(project_dir: Path) -> dict:
    """Load project configuration from config.yml."""
    config_path = project_dir / "config.yml"
    
    if not config_path.exists():
        # Return default config
        return {
            "watermark": True,
            "burn_captions": False,
            "timeline": {
                "method": "weighted",
                "min_slide_sec": 5.0,
                "max_slide_sec": 60.0,
                "gap_sec": 0.25
            }
        }
    
    try:
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid config.yml: {e}")


def load_global_styles(styles_path: Path) -> dict:
    """Load global styles configuration."""
    if not styles_path.exists():
        raise ConfigError(f"Styles file not found: {styles_path}")
    
    try:
        with open(styles_path, 'r') as f:
            return yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid styles.yml: {e}")


def check_dependencies(args) -> None:
    """Check that all required dependencies are available."""
    missing_deps = []
    
    # Check FFmpeg
    try:
        import subprocess
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        missing_deps.append("ffmpeg")
    
    # Check Whisper
    if not check_whisper_availability():
        missing_deps.append("faster-whisper or openai-whisper")
    
    # Check Playwright
    if not check_playwright_installation():
        missing_deps.append("playwright (run: playwright install chromium)")
    
    if missing_deps:
        print("Error: Missing required dependencies:")
        for dep in missing_deps:
            print(f"  - {dep}")
        sys.exit(11)


def cmd_transcribe(args) -> None:
    """Transcribe audio to captions."""
    logger = setup_logging(args.verbose, args.quiet, args.json_logs)
    
    paths = ProjectPaths(Path(args.root), args.project)
    config = load_project_config(paths.project_dir)
    
    # Check if we can skip this step
    manifest = load_manifest(paths.build_dir)
    if should_skip_step("transcribe", manifest, [paths.audio_wav], args.force):
        logger.info(f"Transcription already complete for {args.project}")
        return
    
    with Timer(logger, "transcribe", args.project, "Transcribing audio"):
        # Normalize audio first
        normalized_audio = paths.build_dir / "audio_normalized.wav"
        normalize_wav(paths.audio_wav, normalized_audio, target_dbfs=args.target_dbfs)
        
        # Run Whisper transcription
        run_whisper(
            normalized_audio,
            paths.captions_srt,
            paths.captions_words_json,
            model=args.model,
            language=args.language,
            use_gpu=args.gpu,
            threads=args.threads
        )
        
        # Update manifest
        update_manifest_step(
            manifest, "transcribe",
            [paths.audio_wav],
            [paths.captions_srt, paths.captions_words_json],
            0.0  # Duration will be filled by Timer
        )
        save_manifest(paths.build_dir, manifest)


def cmd_slides(args) -> None:
    """Render slides to PNG images."""
    logger = setup_logging(args.verbose, args.quiet, args.json_logs)
    
    paths = ProjectPaths(Path(args.root), args.project)
    config = load_project_config(paths.project_dir)
    
    # Check if slides file exists
    slides_md = Path(args.md) if args.md else paths.slides_md
    if not slides_md.exists():
        logger.warning(f"No slides file found: {slides_md}")
        return
    
    # Check if we can skip this step
    manifest = load_manifest(paths.build_dir)
    styles_path = Path(args.styles) if args.styles else Path(args.root) / "styles.yml"
    
    if should_skip_step("slides", manifest, [slides_md, styles_path], args.force):
        logger.info(f"Slides already rendered for {args.project}")
        return
    
    with Timer(logger, "slides", args.project, "Rendering slides"):
        styles = load_global_styles(styles_path)
        template_path = Path(args.template) if args.template else Path(args.root) / "templates" / "slide.html"
        
        png_files = render_slides(
            slides_md, styles_path, template_path,
            paths.slides_dir, config,
            logger=logger, project=args.project
        )
        
        # Update manifest
        update_manifest_step(
            manifest, "slides",
            [slides_md, styles_path],
            png_files,
            0.0
        )
        save_manifest(paths.build_dir, manifest)


def cmd_render(args) -> None:
    """Render final video."""
    logger = setup_logging(args.verbose, args.quiet, args.json_logs)
    
    paths = ProjectPaths(Path(args.root), args.project)
    config = load_project_config(paths.project_dir)
    
    # Get slide images
    slide_images = sorted(paths.slides_dir.glob("*.png"))
    if not slide_images:
        raise RenderError("No slide images found. Run slides command first.")
    
    # Get slide durations
    if paths.timeline_json.exists():
        durations = get_slide_durations_from_timeline(paths.timeline_json)
    else:
        # Create simple timeline
        audio_duration = get_audio_duration(paths.audio_wav)
        durations = create_simple_timeline(audio_duration, len(slide_images))
    
    # Ensure we have enough durations
    while len(durations) < len(slide_images):
        durations.append(durations[-1] if durations else 5.0)
    
    durations = durations[:len(slide_images)]  # Trim to match slide count
    
    with Timer(logger, "assemble", args.project, "Assembling video"):
        # Get watermark path
        watermark_path = None
        if not args.no_watermark:
            styles = load_global_styles(Path(args.root) / "styles.yml")
            logo_config = styles.get("logo", {})
            if logo_config.get("path"):
                watermark_path = Path(args.root) / logo_config["path"]
        
        # Get intro/outro paths
        intro_path = Path(args.intro) if args.intro else None
        outro_path = Path(args.outro) if args.outro else None
        
        # Assemble video
        assemble_video(
            slide_images, durations,
            watermark_path=watermark_path,
            intro_path=intro_path,
            outro_path=outro_path,
            output_path=paths.video_nocap_mp4,
            fps=args.fps,
            zoom=args.zoom,
            logger=logger,
            project=args.project
        )
    
    with Timer(logger, "export", args.project, "Exporting final video"):
        # Get music path
        music_path = Path(args.music) if args.music else None
        
        # Export complete video
        export_complete_video(
            paths.video_nocap_mp4,
            paths.audio_wav,
            music_path,
            paths.captions_srt if paths.captions_srt.exists() else None,
            paths.final_mp4,
            config,
            burn_subs=args.burn_subs,
            logger=logger,
            project=args.project
        )


def cmd_thumb(args) -> None:
    """Generate thumbnail."""
    logger = setup_logging(args.verbose, args.quiet, args.json_logs)
    
    paths = ProjectPaths(Path(args.root), args.project)
    config = load_project_config(paths.project_dir)
    
    with Timer(logger, "thumb", args.project, "Generating thumbnail"):
        styles = load_global_styles(Path(args.root) / "styles.yml")
        
        # Override config with command line args
        thumbnail_config = config.get("thumbnail", {})
        if args.title:
            thumbnail_config["title"] = args.title
        if args.subtitle:
            thumbnail_config["subtitle"] = args.subtitle
        
        config["thumbnail"] = thumbnail_config
        
        generate_thumbnail(
            config, styles, paths.thumb_png,
            use_html=not args.use_pillow,
            logger=logger, project=args.project
        )


def cmd_all(args) -> None:
    """Run the complete pipeline."""
    logger = setup_logging(args.verbose, args.quiet, args.json_logs)
    
    logger.info(f"Starting complete pipeline for project: {args.project}")
    
    # Run all steps
    try:
        # Transcribe
        logger.info("Step 1/4: Transcribing audio...")
        cmd_transcribe(args)
        
        # Slides
        logger.info("Step 2/4: Rendering slides...")
        cmd_slides(args)
        
        # Render
        logger.info("Step 3/4: Rendering video...")
        cmd_render(args)
        
        # Thumbnail
        logger.info("Step 4/4: Generating thumbnail...")
        cmd_thumb(args)
        
        # Print success message and next steps
        output_path = Path(args.root) / "projects" / args.project / "build" / "final.mp4"
        thumb_path = Path(args.root) / "projects" / args.project / "build" / "thumb.png"
        
        logger.info("✅ Pipeline complete!")
        logger.info(f"📹 Video: {output_path}")
        logger.info(f"🖼️  Thumbnail: {thumb_path}")
        logger.info("")
        logger.info("Next steps:")
        logger.info("1. Review the generated video")
        logger.info("2. Upload to YouTube or your platform")
        logger.info("3. Use the thumbnail for your video cover")
        
    except AVMError as e:
        logger.error(f"❌ Pipeline failed: {e}")
        sys.exit(e.exit_code)
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        sys.exit(20)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="AVM - Audio to Video Maker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  avm all -p mylesson --gpu --burn-subs --fps 30 --zoom 1.15
  avm transcribe -p mylesson --model medium --target-dbfs -16
  avm slides -p mylesson --theme light
  avm render -p mylesson --music examples/music.mp3 --threshold 0.02 --ratio 8
  avm thumb -p mylesson --title "Stoichiometry" --subtitle "Tips for AP Chem"
        """
    )
    
    # Global arguments
    parser.add_argument("--project", "-p", required=True, help="Project slug")
    parser.add_argument("--root", default=".", help="Project root directory")
    parser.add_argument("--force", action="store_true", help="Force recomputation")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    parser.add_argument("--quiet", "-q", action="store_true", help="Quiet mode")
    parser.add_argument("--json-logs", action="store_true", help="JSON structured logs")
    parser.add_argument("--tmpdir", help="Temporary directory")
    parser.add_argument("--gpu", action="store_true", help="Enable GPU acceleration")
    
    # Subcommands
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Transcribe command
    transcribe_parser = subparsers.add_parser("transcribe", help="Transcribe audio")
    transcribe_parser.add_argument("--model", default="small", 
                                  choices=["tiny", "base", "small", "medium", "large-v3"],
                                  help="Whisper model size")
    transcribe_parser.add_argument("--language", help="Language code (auto-detect if not set)")
    transcribe_parser.add_argument("--threads", type=int, default=4, help="Number of threads")
    transcribe_parser.add_argument("--target-dbfs", type=float, default=-14.0, 
                                  help="Target dBFS for audio normalization")
    
    # Slides command
    slides_parser = subparsers.add_parser("slides", help="Render slides")
    slides_parser.add_argument("--md", help="Slides markdown file")
    slides_parser.add_argument("--styles", help="Styles YAML file")
    slides_parser.add_argument("--template", help="HTML template file")
    
    # Render command
    render_parser = subparsers.add_parser("render", help="Render video")
    render_parser.add_argument("--burn-subs", action="store_true", help="Burn subtitles into video")
    render_parser.add_argument("--no-watermark", action="store_true", help="Disable watermark")
    render_parser.add_argument("--intro", help="Intro video file")
    render_parser.add_argument("--outro", help="Outro video file")
    render_parser.add_argument("--music", help="Background music file")
    render_parser.add_argument("--fps", type=int, default=30, help="Video frame rate")
    render_parser.add_argument("--zoom", type=float, default=1.10, help="Ken-Burns zoom factor")
    render_parser.add_argument("--theme", choices=["dark", "light"], default="dark", help="Theme")
    render_parser.add_argument("--threshold", type=float, default=0.02, help="Sidechain threshold")
    render_parser.add_argument("--ratio", type=float, default=8.0, help="Sidechain ratio")
    render_parser.add_argument("--attack-ms", type=float, default=5.0, help="Sidechain attack (ms)")
    render_parser.add_argument("--release-ms", type=float, default=250.0, help="Sidechain release (ms)")
    
    # Thumbnail command
    thumb_parser = subparsers.add_parser("thumb", help="Generate thumbnail")
    thumb_parser.add_argument("--title", help="Thumbnail title")
    thumb_parser.add_argument("--subtitle", help="Thumbnail subtitle")
    thumb_parser.add_argument("--use-pillow", action="store_true", help="Use Pillow instead of HTML")
    
    # All command (inherits all arguments)
    all_parser = subparsers.add_parser("all", help="Run complete pipeline")
    
    # Parse arguments
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # Check dependencies
    check_dependencies(args)
    
    # Route to appropriate command
    try:
        if args.command == "transcribe":
            cmd_transcribe(args)
        elif args.command == "slides":
            cmd_slides(args)
        elif args.command == "render":
            cmd_render(args)
        elif args.command == "thumb":
            cmd_thumb(args)
        elif args.command == "all":
            cmd_all(args)
        else:
            parser.print_help()
            sys.exit(1)
            
    except AVMError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(e.exit_code)
    except KeyboardInterrupt:
        print("\nOperation cancelled by user", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(20)


if __name__ == "__main__":
    main()
