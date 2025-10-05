#!/usr/bin/env python3
"""
AVM - Audio to Video Maker CLI

Convert narrated lessons into polished YouTube videos with captions, 
watermarks, and professional motion graphics.
"""

import argparse
import sys
from pathlib import Path
from typing import Optional, Dict, Any

# Add the avm package to path
sys.path.insert(0, str(Path(__file__).parent))

from avm.pipeline import (
    AVMError, TranscriptionError, RenderError, MuxError, ConfigError, ExitCode,
    load_merged_config, validate_config, get_config_value, set_config_value
)
from avm.pipeline.logging import setup_logging, Timer
from avm.pipeline.io_paths import ProjectPaths, load_manifest, save_manifest, should_skip_step, update_manifest_step
from avm.pipeline.transcribe import (
    normalize_wav, run_whisper, check_whisper_availability, get_audio_duration
)
from avm.pipeline.slides import render_slides, check_playwright_installation
from avm.pipeline.assemble import assemble_video, load_timeline_from_json
from avm.pipeline.timeline import build_timeline, save_timeline_to_json, _parse_slides_for_token_counts
from avm.pipeline.export import export_complete_video
from avm.pipeline.thumb import generate_thumbnail
from avm.pipeline.doctor import doctor
from avm.pipeline.storyboard import generate_storyboard, save_storyboard_json, validate_storyboard_schema


def create_cli_overrides(args) -> Dict[str, Any]:
    """Create configuration overrides from CLI arguments."""
    overrides = {}
    
    # Map CLI args to config keys
    if hasattr(args, 'theme'):
        overrides['theme'] = args.theme
    if hasattr(args, 'fps'):
        overrides['fps'] = args.fps
    if hasattr(args, 'zoom'):
        overrides['zoom'] = args.zoom
    if hasattr(args, 'burn_subs'):
        overrides['burn_captions'] = args.burn_subs
    if hasattr(args, 'no_watermark'):
        overrides['watermark'] = not args.no_watermark
    if hasattr(args, 'threshold'):
        set_config_value(overrides, 'audio.ducking.threshold', args.threshold)
    if hasattr(args, 'ratio'):
        set_config_value(overrides, 'audio.ducking.ratio', args.ratio)
    if hasattr(args, 'attack_ms'):
        set_config_value(overrides, 'audio.ducking.attack_ms', args.attack_ms)
    if hasattr(args, 'release_ms'):
        set_config_value(overrides, 'audio.ducking.release_ms', args.release_ms)
    if hasattr(args, 'target_dbfs'):
        set_config_value(overrides, 'audio.target_lufs', args.target_dbfs)
    
    # Storyboard-specific overrides
    if hasattr(args, 'beats'):
        set_config_value(overrides, 'storyboard.beats.count', args.beats)
    if hasattr(args, 'min_duration'):
        set_config_value(overrides, 'storyboard.beats.min_duration_sec', args.min_duration)
    if hasattr(args, 'max_duration'):
        set_config_value(overrides, 'storyboard.beats.max_duration_sec', args.max_duration)
    
    return overrides


def check_dependencies(args) -> None:
    """Check that all required dependencies are available."""
    missing_deps = []
    
    # Special handling for render command
    if args.command == "render":
        # For render command, check captions and burn_subs status
        root_path = Path(args.root) / "avm" if (Path(args.root) / "avm").exists() else Path(args.root)
        paths = ProjectPaths(root_path, args.project)
        captions_exist = paths.captions_srt.exists()
        burn_subs = getattr(args, 'burn_subs', False)
        
        # Check if we need Whisper (for captions)
        # Need Whisper only if:
        # 1. No captions exist AND
        # 2. We're burning captions (burn_subs=True)
        need_whisper = not captions_exist and burn_subs
        
        if need_whisper and not check_whisper_availability():
            missing_deps.append("Whisper (faster-whisper or openai-whisper)")
            print("❌ Missing required dependencies for render:")
            for dep in missing_deps:
                print(f"  - {dep}")
            print("\n💡 Tip: Run 'avm transcribe -p <project>' to generate captions first.")
            print("   Or use '--no-burn-subs' for soft subtitles (no Whisper needed).")
            sys.exit(11)
        
        # FFmpeg is always required for render (video processing)
        try:
            import subprocess
            subprocess.run(["ffmpeg", "-version"], check=True, capture_output=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            missing_deps.append("FFmpeg")
        
        # Playwright is NOT required for render (video assembly is already done)
        
        if missing_deps:
            print("❌ Missing required dependencies for render:")
            for dep in missing_deps:
                print(f"  - {dep}")
            print("\nRun 'avm.py doctor' for detailed system check and installation instructions.")
            sys.exit(11)
        
        # Log friendly note when captions are missing and burn_subs=True
        if not captions_exist and burn_subs:
            print("💡 Note: No captions found. Run 'avm transcribe -p <project>' to generate captions first.")
        
        return
    
    # For all other commands, check all dependencies
    # Check Whisper
    if not check_whisper_availability():
        missing_deps.append("Whisper (faster-whisper or openai-whisper)")
    
    # Check Playwright
    if not check_playwright_installation():
        missing_deps.append("Playwright with Chromium browser")
    
    if missing_deps:
        print("❌ Missing required dependencies:")
        for dep in missing_deps:
            print(f"  - {dep}")
        print("\nRun 'avm.py doctor' for detailed system check and installation instructions.")
        sys.exit(11)


def cmd_transcribe(args) -> None:
    """Transcribe audio to captions."""
    logger = setup_logging(args.verbose, args.quiet, args.json_logs)
    
    paths = ProjectPaths(Path(args.root), args.project)
    
    # Load merged configuration
    styles_path = Path(args.root) / "styles.yml"
    cli_overrides = create_cli_overrides(args)
    config = load_merged_config(styles_path, paths.project_dir, cli_overrides)
    validate_config(config)
    
    # Check if we can skip this step
    manifest = load_manifest(paths.build_dir)
    if should_skip_step([paths.audio_wav], [paths.captions_srt, paths.captions_words_json], args.force):
        logger.info(f"Transcription already complete for {args.project}")
        return
    
    with Timer(logger, "transcribe", args.project, "Transcribing audio") as timer:
        # Normalize audio first
        normalized_audio = paths.build_dir / "audio_normalized.wav"
        target_dbfs = get_config_value(config, 'audio.target_lufs', args.target_dbfs)
        normalize_wav(paths.audio_wav, normalized_audio, target_dbfs=target_dbfs)
        
        # Run Whisper transcription
        run_whisper(
            normalized_audio,
            paths.captions_srt,
            paths.captions_words_json,
            args.model,
            args.language,
            args.gpu,
            args.threads
        )
        
        # Update manifest
        update_manifest_step(
            manifest, "transcribe",
            [paths.audio_wav],
            [paths.captions_srt, paths.captions_words_json],
            timer.duration_ms if hasattr(timer, 'duration_ms') else 0
        )
        save_manifest(paths.build_dir, manifest)
    
    print(f"✅ Transcription complete: {paths.captions_srt}")


def cmd_slides(args) -> None:
    """Render slides to PNG images."""
    logger = setup_logging(args.verbose, args.quiet, args.json_logs)
    
    paths = ProjectPaths(Path(args.root), args.project)
    
    # Load merged configuration
    styles_path = Path(args.styles) if args.styles else Path(args.root) / "styles.yml"
    cli_overrides = create_cli_overrides(args)
    config = load_merged_config(styles_path, paths.project_dir, cli_overrides)
    
    # Skip validation for slides command since it doesn't need audio processing
    # validate_config(config)
    
    # Check if slides file exists (fallback will be created if missing)
    slides_md = Path(args.md) if args.md else paths.slides_md
    if not slides_md.exists():
        logger.info(f"No slides file found: {slides_md}, will create fallback slide")
    
    # Check if we can skip this step
    manifest = load_manifest(paths.build_dir)
    
    if should_skip_step("slides", manifest, [slides_md, styles_path], [paths.slides_dir / "slide_001.png"], force=args.force):
        logger.info(f"Slides already rendered for {args.project}")
        return
    
    with Timer(logger, "slides", args.project, "Rendering slides") as timer:
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
            timer.duration_ms if hasattr(timer, 'duration_ms') else 0
        )
        save_manifest(paths.build_dir, manifest)
    
    print(f"✅ Slides rendered: {len(png_files)} images in {paths.slides_dir}")


def cmd_render(args) -> None:
    """Render final video."""
    logger = setup_logging(args.verbose, args.quiet, args.json_logs)
    
    paths = ProjectPaths(Path(args.root), args.project)
    
    # Load merged configuration
    styles_path = Path(args.root) / "styles.yml"
    cli_overrides = create_cli_overrides(args)
    config = load_merged_config(styles_path, paths.project_dir, cli_overrides)
    validate_config(config)
    
    # Get slide images
    slide_images = sorted(paths.slides_dir.glob("*.png"))
    if not slide_images:
        raise RenderError("No slide images found. Run slides command first.")
    
    # Get or create timeline
    timeline_method = get_config_value(config, 'timeline.method', 'weighted')
    
    if paths.timeline_json.exists() and timeline_method != 'even':
        # Use existing timeline if available and method is weighted
        logger.info("Using existing timeline.json")
        timeline_segments = load_timeline_from_json(paths.timeline_json)
        durations = [segment["end"] - segment["start"] for segment in timeline_segments["segments"]]
    elif paths.captions_words_json.exists() and timeline_method == 'weighted':
        # Create timeline from captions for weighted method
        logger.info("Creating timeline from captions for weighted method")
        token_counts = _parse_slides_for_token_counts(paths.slides_md)
        total_duration = get_audio_duration(paths.audio_wav)
        
        # Add project directory to config for token parsing
        config_with_project = config.copy()
        config_with_project["project_dir"] = paths.project_dir
        
        timeline_segments = build_timeline(
            len(slide_images), total_duration, 'weighted', config_with_project
        )
        save_timeline_to_json(timeline_segments, paths.timeline_json)
        durations = [segment["end"] - segment["start"] for segment in timeline_segments]
    else:
        # Use even method (default fallback)
        logger.info(f"Creating timeline using {timeline_method} method")
        total_duration = get_audio_duration(paths.audio_wav) if paths.audio_wav.exists() else len(slide_images) * 10.0
        
        # Add project directory to config for consistency
        config_with_project = config.copy()
        config_with_project["project_dir"] = paths.project_dir
        
        timeline_segments = build_timeline(
            len(slide_images), total_duration, 'even', config_with_project
        )
        save_timeline_to_json(timeline_segments, paths.timeline_json)
        durations = [segment["end"] - segment["start"] for segment in timeline_segments]
    
    with Timer(logger, "assemble", args.project, "Assembling video") as timer:
        # Get watermark path
        watermark_path = None
        if get_config_value(config, 'watermark', True):
            logo_path = get_config_value(config, 'logo.path')
            if logo_path:
                watermark_path = Path(args.root) / logo_path
        
        # Get intro/outro paths
        intro_path = Path(args.intro) if args.intro else None
        outro_path = Path(args.outro) if args.outro else None
        
        # Assemble video
        fps = get_config_value(config, 'fps', args.fps)
        zoom = get_config_value(config, 'zoom', args.zoom)
        
        assemble_video(
            slide_images, durations,
            watermark_path=watermark_path,
            intro_path=intro_path,
            outro_path=outro_path,
            output_path=paths.video_nocap_mp4,
            fps=fps,
            zoom=zoom,
            logger=logger,
            project=args.project,
            project_path=paths.project_dir
        )
    
    with Timer(logger, "export", args.project, "Exporting final video") as timer:
        # Get music path
        music_path = Path(args.music) if args.music else None
        
        # Export complete video using legacy signature
        burn_subs = get_config_value(config, 'burn_captions', args.burn_subs)
        
        export_complete_video(
            paths.video_nocap_mp4,
            paths.audio_wav,
            music_path,
            paths.captions_srt if paths.captions_srt.exists() else None,
            paths.final_mp4,
            config,
            burn_subs=burn_subs,
            logger=logger,
            project=args.project
        )
        
        # Update manifest
        manifest = load_manifest(paths.build_dir)
        update_manifest_step(
            manifest, "render",
            slide_images + [paths.audio_wav],
            [paths.final_mp4],
            timer.duration
        )
        save_manifest(paths.build_dir, manifest)
    
    print(f"✅ Video rendered: {paths.final_mp4}")


def cmd_thumb(args) -> None:
    """Generate thumbnail."""
    logger = setup_logging(args.verbose, args.quiet, args.json_logs)
    
    paths = ProjectPaths(Path(args.root), args.project)
    
    # Load merged configuration
    styles_path = Path(args.root) / "styles.yml"
    cli_overrides = create_cli_overrides(args)
    config = load_merged_config(styles_path, paths.project_dir, cli_overrides)
    validate_config(config)
    
    with Timer(logger, "thumb", args.project, "Generating thumbnail") as timer:
        # Override thumbnail config with command line args
        if args.title:
            set_config_value(config, 'thumbnail.title', args.title)
        if args.subtitle:
            set_config_value(config, 'thumbnail.subtitle', args.subtitle)
        
        generate_thumbnail(
            config, config, paths.thumb_png,  # Pass config as both config and styles
            use_html=not args.use_pillow,
            logger=logger, project=args.project
        )
        
        # Update manifest
        manifest = load_manifest(paths.build_dir)
        update_manifest_step(
            manifest, "thumb",
            [paths.config_yml, styles_path],
            [paths.thumb_png],
            timer.duration
        )
        save_manifest(paths.build_dir, manifest)
    
    print(f"✅ Thumbnail generated: {paths.thumb_png}")


def cmd_all(args) -> None:
    """Run the complete pipeline."""
    logger = setup_logging(args.verbose, args.quiet, args.json_logs)
    
    logger.info("🚀 Starting complete AVM pipeline")
    
    # Run each step in sequence
    cmd_transcribe(args)
    cmd_slides(args)
    cmd_render(args)
    cmd_thumb(args)
    
    paths = ProjectPaths(Path(args.root), args.project)
    
    print("\n🎉 Pipeline complete! Generated files:")
    print(f"  📹 Video: {paths.final_mp4}")
    print(f"  🖼️  Thumbnail: {paths.thumb_png}")
    print(f"  📝 Captions: {paths.captions_srt}")


def cmd_doctor(args) -> None:
    """Run system health check."""
    # Set up logging for doctor command
    logger = setup_logging(args.verbose, args.quiet, args.json_logs)
    
    # Run the doctor check
    results = doctor(logger=logger, project="doctor")
    
    # Exit with error code if any critical checks failed
    critical_components = ["python", "ffmpeg", "ffprobe"]
    failed_critical = [comp for comp in critical_components 
                      if "❌ FAIL" in results.get(comp, {}).get("status", "")]
    
    if failed_critical:
        print(f"\n⚠️  Critical components failed: {', '.join(failed_critical)}")
        sys.exit(1)


def cmd_storyboard(args) -> None:
    """Generate storyboard JSON from transcripts."""
    # Set up logging
    logger = setup_logging(args.verbose, args.quiet, args.json_logs)
    
    # Load configuration
    project_root = Path(args.root)
    project_path = project_root / "avm" / "projects" / args.project
    
    if not project_path.exists():
        raise AVMError(f"Project directory not found: {project_path}")
    
    # Load merged configuration
    styles_path = project_root / "styles.yml"
    config = load_merged_config(styles_path, project_path)
    
    # Apply CLI overrides
    cli_overrides = create_cli_overrides(args)
    for key, value in cli_overrides.items():
        set_config_value(config, key, value)
    
    # Validate configuration (skip audio validation for storyboard)
    # validate_config(config)  # Skip validation since storyboard doesn't need audio processing
    
    # Generate storyboard
    with Timer(logger, "storyboard", args.project, "Generating storyboard") as timer:
        storyboard = generate_storyboard(project_path, config, logger=logger, project=args.project)
    
    # Save storyboard JSON
    if args.output:
        output_path = args.output
    else:
        output_path = project_path / "build" / "storyboard.json"
    save_storyboard_json(storyboard, output_path)
    
    # Validate the generated storyboard
    validate_storyboard_schema(storyboard)
    
    print(f"✅ Storyboard generated: {output_path}")
    print(f"   📊 Beats: {len(storyboard['beats'])}")
    print(f"   ⏱️  Duration: {storyboard['meta']['duration_sec']:.1f}s")
    print(f"   📝 Title: {storyboard['meta']['title']}")
    
    # Show beat summary
    if args.verbose:
        print("\n📋 Beat Summary:")
        for i, beat in enumerate(storyboard['beats'], 1):
            print(f"   {i}. {beat['start']:.1f}s-{beat['end']:.1f}s: {beat['title']}")
            if beat['bullets']:
                for bullet in beat['bullets'][:2]:  # Show first 2 bullets
                    print(f"      • {bullet}")


def create_parser() -> argparse.ArgumentParser:
    """Create the main argument parser."""
    parser = argparse.ArgumentParser(
        prog="avm",
        description="AVM - Audio to Video Maker CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  avm transcribe -p mylesson
  avm slides -p mylesson --theme light
  avm render -p mylesson --fps 60 --burn-subs
  avm thumb -p mylesson --title "My Video Title"
  avm all -p mylesson
  avm doctor
        """
    )
    
    # Global options
    parser.add_argument(
        "-p", "--project",
        help="Project slug (e.g., 'mylesson')"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Project root directory (default: current directory)"
    )
    parser.add_argument(
        "-f", "--force",
        action="store_true",
        help="Recompute even if cached"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Increase log level to DEBUG"
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Only log errors"
    )
    parser.add_argument(
        "--json-logs",
        action="store_true",
        help="Output logs in JSON format"
    )
    parser.add_argument(
        "--tmpdir",
        type=Path,
        help="Override temporary working directory"
    )
    parser.add_argument(
        "--gpu",
        action="store_true",
        help="Enable GPU for faster-whisper if available"
    )
    
    # Subcommands
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Transcribe command
    transcribe_parser = subparsers.add_parser(
        "transcribe",
        help="Transcribe audio to captions"
    )
    transcribe_parser.add_argument(
        "--model",
        choices=["tiny", "base", "small", "medium", "large", "large-v2", "large-v3"],
        default="small",
        help="Whisper model to use (default: small)"
    )
    transcribe_parser.add_argument(
        "--language",
        default="auto",
        help="Language for transcription (e.g., 'en', 'auto')"
    )
    transcribe_parser.add_argument(
        "--threads",
        type=int,
        default=0,
        help="Number of threads for transcription (0 = auto)"
    )
    transcribe_parser.add_argument(
        "--target-dbfs",
        type=float,
        default=-14.0,
        help="Target audio level in dBFS (default: -14.0)"
    )
    
    # Slides command
    slides_parser = subparsers.add_parser(
        "slides",
        help="Render slides to PNG images"
    )
    slides_parser.add_argument(
        "--md",
        type=Path,
        help="Path to slides.md (default: projects/<slug>/slides.md)"
    )
    slides_parser.add_argument(
        "--styles",
        type=Path,
        help="Path to styles.yml (default: styles.yml)"
    )
    slides_parser.add_argument(
        "--template",
        type=Path,
        help="Path to slide.html template (default: templates/slide.html)"
    )
    slides_parser.add_argument(
        "--theme",
        choices=["dark", "light"],
        help="Override theme from config"
    )
    
    # Render command
    render_parser = subparsers.add_parser(
        "render",
        help="Render final video"
    )
    render_parser.add_argument(
        "--fps",
        type=int,
        default=30,
        help="Video frame rate (default: 30)"
    )
    render_parser.add_argument(
        "--zoom",
        type=float,
        default=1.10,
        help="Ken-Burns zoom factor (default: 1.10)"
    )
    render_parser.add_argument(
        "--burn-subs",
        action="store_true",
        help="Burn captions into video"
    )
    render_parser.add_argument(
        "--no-watermark",
        action="store_true",
        help="Disable watermark overlay"
    )
    render_parser.add_argument(
        "--intro",
        type=Path,
        help="Path to intro video"
    )
    render_parser.add_argument(
        "--outro",
        type=Path,
        help="Path to outro video"
    )
    render_parser.add_argument(
        "--music",
        type=Path,
        help="Path to background music"
    )
    render_parser.add_argument(
        "--threshold",
        type=float,
        default=0.02,
        help="Audio ducking threshold (default: 0.02)"
    )
    render_parser.add_argument(
        "--ratio",
        type=float,
        default=8.0,
        help="Audio ducking ratio (default: 8.0)"
    )
    render_parser.add_argument(
        "--attack-ms",
        type=float,
        default=5.0,
        help="Audio ducking attack time in ms (default: 5.0)"
    )
    render_parser.add_argument(
        "--release-ms",
        type=float,
        default=250.0,
        help="Audio ducking release time in ms (default: 250.0)"
    )
    render_parser.add_argument(
        "--target-dbfs",
        type=float,
        default=-14.0,
        help="Target audio level in dBFS (default: -14.0)"
    )
    
    # Thumbnail command
    thumb_parser = subparsers.add_parser(
        "thumb",
        help="Generate thumbnail"
    )
    thumb_parser.add_argument(
        "--title",
        help="Title for the thumbnail"
    )
    thumb_parser.add_argument(
        "--subtitle",
        help="Subtitle for the thumbnail"
    )
    thumb_parser.add_argument(
        "--use-pillow",
        action="store_true",
        help="Use Pillow instead of HTML template"
    )
    
    # Storyboard command
    storyboard_parser = subparsers.add_parser(
        "storyboard",
        help="Generate storyboard JSON from transcripts"
    )
    storyboard_parser.add_argument(
        "--beats",
        type=int,
        default=5,
        help="Number of beats to generate (default: 5)"
    )
    storyboard_parser.add_argument(
        "--min-duration",
        type=float,
        default=10.0,
        help="Minimum duration per beat in seconds (default: 10.0)"
    )
    storyboard_parser.add_argument(
        "--max-duration",
        type=float,
        default=60.0,
        help="Maximum duration per beat in seconds (default: 60.0)"
    )
    storyboard_parser.add_argument(
        "--output",
        type=Path,
        help="Output path for storyboard JSON (default: build/storyboard.json)"
    )
    
    # All command
    all_parser = subparsers.add_parser(
        "all",
        help="Run the complete pipeline"
    )
    # Add key options from other commands
    all_parser.add_argument("--model", choices=["tiny", "base", "small", "medium", "large", "large-v2", "large-v3"], default="small", help="Whisper model to use")
    all_parser.add_argument("--language", default="auto", help="Language for transcription")
    all_parser.add_argument("--threads", type=int, default=0, help="Number of threads for transcription")
    all_parser.add_argument("--target-dbfs", type=float, default=-14.0, help="Target audio level in dBFS")
    all_parser.add_argument("--fps", type=int, default=30, help="Video frame rate")
    all_parser.add_argument("--zoom", type=float, default=1.10, help="Ken-Burns zoom factor")
    all_parser.add_argument("--burn-subs", action="store_true", help="Burn captions into video")
    all_parser.add_argument("--no-watermark", action="store_true", help="Disable watermark overlay")
    all_parser.add_argument("--intro", type=Path, help="Path to intro video")
    all_parser.add_argument("--outro", type=Path, help="Path to outro video")
    all_parser.add_argument("--music", type=Path, help="Path to background music")
    all_parser.add_argument("--title", help="Title for the thumbnail")
    all_parser.add_argument("--subtitle", help="Subtitle for the thumbnail")
    
    # Doctor command
    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Run system health check"
    )
    doctor_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed information"
    )
    
    return parser


def main() -> int:
    """Main CLI entry point."""
    parser = create_parser()
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Check if project is required for this command
    if args.command != "doctor" and not args.project:
        print("❌ Error: --project/-p is required for this command")
        parser.print_help()
        return 1
    
    try:
        # Check dependencies for most commands
        if args.command not in ["doctor", "storyboard", "slides"]:
            check_dependencies(args)
        
        # Route to appropriate command
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
        elif args.command == "doctor":
            cmd_doctor(args)
        elif args.command == "storyboard":
            cmd_storyboard(args)
        else:
            print(f"Unknown command: {args.command}")
            return 1
        
        return 0
        
    except AVMError as e:
        logger = setup_logging(args.verbose, args.quiet, args.json_logs)
        logger.error(f"AVM Error: {e}")
        return e.exit_code
    except KeyboardInterrupt:
        print("\n⚠️  Operation cancelled by user")
        return 130
    except Exception as e:
        logger = setup_logging(args.verbose, args.quiet, args.json_logs)
        logger.error(f"Unexpected error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())