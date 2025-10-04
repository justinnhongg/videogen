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

### System Health Check
Always start with the system health check:
```bash
make doctor
# or
python avm.py doctor
```

This will show you exactly what's missing and provide installation commands.

### Common Issues

#### 1. **Python Version Issues**
❌ **Problem**: Python version too old
✅ **Solution**: AVM requires Python 3.11+
```bash
# Check version
python --version

# Install Python 3.11+ (macOS with Homebrew)
brew install python@3.11

# Install Python 3.11+ (Ubuntu)
sudo apt update
sudo apt install python3.11 python3.11-pip python3.11-venv
```

#### 2. **FFmpeg/FFprobe Missing**
❌ **Problem**: Video processing tools not found
✅ **Solution**: Install FFmpeg with codec support
```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt update
sudo apt install ffmpeg

# Windows (using Chocolatey)
choco install ffmpeg

# Verify installation
ffmpeg -version
ffprobe -version
```

#### 3. **Whisper Transcription Issues**
❌ **Problem**: No Whisper backend available
✅ **Solution**: Install at least one Whisper backend
```bash
# Option 1: faster-whisper (recommended - faster)
pip install faster-whisper

# Option 2: openai-whisper (original)
pip install openai-whisper

# Option 3: Both for flexibility
pip install faster-whisper openai-whisper

# Verify installation
python -c "from avm.pipeline.transcribe import check_whisper_availability; print(check_whisper_availability())"
```

#### 4. **Playwright Browser Missing**
❌ **Problem**: Chromium browser not installed for slide rendering
✅ **Solution**: Install Playwright browser
```bash
# Install Playwright and browser
pip install playwright
python -m playwright install chromium

# Or use the Makefile
make setup

# Verify installation
python -c "from avm.pipeline.slides import check_playwright_installation; print(check_playwright_installation())"
```

#### 5. **Font Issues for Captions**
❌ **Problem**: System fonts not available for caption rendering
✅ **Solution**: Install common fonts
```bash
# macOS
brew install font-inter font-roboto

# Ubuntu/Debian
sudo apt install fonts-inter fonts-roboto fonts-liberation

# Windows
# Download and install Inter/Roboto fonts manually
```

#### 6. **GPU Acceleration Issues**
❌ **Problem**: CUDA not available for faster-whisper
✅ **Solution**: Check CUDA installation
```bash
# Check CUDA availability
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}')"

# Install CUDA-enabled PyTorch (if needed)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# Use CPU-only if GPU not available
python avm.py all -p my-project  # GPU disabled by default
```

#### 7. **Memory Issues**
❌ **Problem**: Out of memory during processing
✅ **Solution**: Optimize settings
```bash
# Use smaller Whisper model
python avm.py transcribe -p my-project --model small

# Reduce video quality for faster encoding
python avm.py render -p my-project --crf 23 --preset fast

# Process in smaller chunks
python avm.py transcribe -p my-project --threads 2
```

#### 8. **Permission Issues**
❌ **Problem**: Cannot write to build directories
✅ **Solution**: Fix file permissions
```bash
# Make sure you own the project directory
sudo chown -R $USER:$USER avm/projects/

# Ensure write permissions
chmod -R 755 avm/projects/
```

### Performance Tips

- **Transcription Speed**: Use `--model small` for faster processing
- **GPU Acceleration**: Enable with `--gpu` if CUDA available
- **CPU Processing**: Use `--threads 8` for multi-core systems
- **Video Encoding**: Set `--crf 20` for faster encoding (lower quality)
- **Memory Usage**: Use smaller models and lower resolution for large files

### Getting Help

1. **Check System Health**: `make doctor`
2. **Run Tests**: `make test`
3. **Check Logs**: Use `--verbose` flag for detailed output
4. **Clean Build**: `make clean` to remove corrupted artifacts
5. **Force Rebuild**: Use `--force` flag to bypass caching

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