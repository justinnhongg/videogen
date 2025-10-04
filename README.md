# AVM - Audio to Video Maker

Convert narrated lessons into polished YouTube videos with captions, watermarks, and professional motion graphics.

## Features

- **Audio Transcription**: Automatic speech-to-text using Whisper
- **Slide Rendering**: Markdown slides to beautiful 1080p images
- **Ken-Burns Motion**: Subtle pan/zoom effects for visual interest
- **Professional Audio**: Voice normalization and music ducking
- **Captions**: Burned or soft subtitles with proper timing
- **Branding**: Watermarks, intro/outro videos
- **Thumbnails**: Auto-generated YouTube thumbnails

## Quick Start (5 Commands)

Get up and running in minutes:

```bash
# 1. Install dependencies
make install

# 2. Setup Playwright browser
make setup

# 3. Check system health
make doctor

# 4. Run tests
make test

# 5. Generate demo video
make demo
```

That's it! Your demo video will be generated in `avm/projects/demo/build/`.

## Detailed Setup

### 1. Install Dependencies

```bash
# Install system dependencies
brew install ffmpeg  # macOS
# sudo apt install ffmpeg  # Ubuntu

# Install Python dependencies
make install

# Setup Playwright browser
make setup
```

### 2. Create Your Project

```bash
# Create project directory
mkdir -p avm/projects/my-lesson

# Add your files
cp your-audio.wav avm/projects/my-lesson/audio.wav
cp your-slides.md avm/projects/my-lesson/slides.md
cp your-config.yml avm/projects/my-lesson/config.yml
```

### 3. Run the Pipeline

```bash
# Full pipeline
python avm.py all -p my-lesson

# Individual steps
python avm.py transcribe -p my-lesson
python avm.py slides -p my-lesson
python avm.py render -p my-lesson
python avm.py thumb -p my-lesson
```

## Project Structure

```
avm/
├── avm.py                 # CLI entry point
├── pipeline/              # Core processing modules
├── templates/             # HTML templates
├── examples/              # Sample assets
├── projects/              # Your video projects
│   └── my-lesson/
│       ├── audio.wav      # Input audio
│       ├── slides.md      # Slide content
│       ├── config.yml     # Project config
│       └── build/         # Generated artifacts
├── styles.yml             # Global styling
└── requirements.txt       # Python dependencies
```

## Configuration

### Global Styles (`styles.yml`)

```yaml
theme: "dark"
font_family: "Inter, system-ui, sans-serif"
brand_color: "#56B3F1"
text_color: "#EDEDED"
bg_color: "#0B0B0E"
heading_size: 64
body_size: 40

logo:
  path: "examples/logo.png"
  opacity: 0.85
  width_px: 220
  position: "bottom-right"

kenburns:
  zoom_start: 1.05
  zoom_end: 1.12
  pan: "auto"
```

### Project Config (`projects/my-lesson/config.yml`)

```yaml
slug: "my-lesson"
title: "Introduction to Physics"
author: "Dr. Smith"
watermark: true
burn_captions: false

timeline:
  method: "weighted"
  min_slide_sec: 5.0
  max_slide_sec: 60.0

thumbnail:
  title: "Physics Basics"
  subtitle: "For Beginners"
```

## CLI Usage

### Global Options

```bash
python avm.py --project my-lesson [OPTIONS] COMMAND

Options:
  -p, --project TEXT    Project slug (required)
  --root PATH          Project root directory
  --force              Force recomputation
  -v, --verbose        Verbose logging
  -q, --quiet          Quiet mode
  --json-logs          Structured JSON logs
  --gpu                Enable GPU acceleration
```

### Commands

#### Transcribe
```bash
python avm.py transcribe -p my-lesson [OPTIONS]

Options:
  --model [tiny|base|small|medium|large-v3]  Whisper model size
  --language TEXT                            Language code
  --threads INTEGER                          Number of threads
```

#### Slides
```bash
python avm.py slides -p my-lesson [OPTIONS]

Options:
  --md PATH           Slides markdown file
  --styles PATH       Styles YAML file
  --template PATH     HTML template file
```

#### Render
```bash
python avm.py render -p my-lesson [OPTIONS]

Options:
  --burn-captions     Burn captions into video
  --no-watermark      Disable watermark
  --intro PATH        Intro video file
  --outro PATH        Outro video file
  --music PATH        Background music file
  --crf INTEGER       Video quality (lower = better)
  --preset TEXT       Encoding preset
```

#### Thumbnail
```bash
python avm.py thumb -p my-lesson [OPTIONS]

Options:
  --title TEXT        Thumbnail title
  --subtitle TEXT     Thumbnail subtitle
  --use-pillow        Use Pillow instead of HTML
```

#### Doctor
```bash
python avm.py doctor

# Check system health and dependencies
```

## Examples

### Basic Usage
```bash
# Simple pipeline
python avm.py all -p my-lesson

# With GPU acceleration
python avm.py all -p my-lesson --gpu

# Burn captions into video
python avm.py all -p my-lesson --burn-captions
```

### Advanced Usage
```bash
# Custom model and settings
python avm.py transcribe -p my-lesson --model medium --language en

# Custom rendering settings
python avm.py render -p my-lesson --crf 20 --preset slow --music bg-music.mp3

# Custom thumbnail
python avm.py thumb -p my-lesson --title "Advanced Physics" --subtitle "Quantum Mechanics"
```

## Makefile Commands

```bash
make install     # Install Python dependencies
make setup       # Complete setup (install + playwright)
make test        # Run all tests
make demo        # Run demo pipeline end-to-end
make doctor      # Check system health
make clean       # Clean build artifacts
make help        # Show all available commands
```

## Troubleshooting

### Common Issues

1. **FFmpeg not found**
   ```bash
   brew install ffmpeg  # macOS
   sudo apt install ffmpeg  # Ubuntu
   ```

2. **Playwright browser missing**
   ```bash
   make setup  # or: python -m playwright install chromium
   ```

3. **Whisper model download**
   - Models are downloaded automatically on first use
   - Ensure stable internet connection

4. **GPU acceleration not working**
   - Check CUDA installation for NVIDIA GPUs
   - Use `--gpu` flag to enable

### Performance Tips

- Use `--model small` for faster transcription
- Enable GPU with `--gpu` if available
- Use `--threads 8` for faster CPU processing
- Set `--crf 20` for faster encoding (lower quality)

## Development

### Running Tests
```bash
make test
```

### Clean Build Artifacts
```bash
make clean
```

### Check System Requirements
```bash
make doctor
```

### Development Setup
```bash
make dev-setup  # Install dev dependencies
make lint       # Run code linting
make format     # Format code
```

## License

MIT License - see LICENSE file for details.