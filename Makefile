# AVM - Audio to Video Maker Makefile
# Provides convenient commands for setup and usage

.PHONY: help install setup test clean demo

# Default target
help:
	@echo "AVM - Audio to Video Maker"
	@echo ""
	@echo "Available commands:"
	@echo "  make install     - Install Python dependencies"
	@echo "  make setup       - Complete setup (install + playwright)"
	@echo "  make test        - Run basic tests"
	@echo "  make demo        - Run demo pipeline"
	@echo "  make clean       - Clean build artifacts"
	@echo "  make help        - Show this help"

# Install Python dependencies
install:
	@echo "Installing Python dependencies..."
	pip install -r requirements.txt

# Complete setup including Playwright browser
setup: install
	@echo "Setting up Playwright browser..."
	python -m playwright install chromium
	@echo "Setup complete!"
	@echo ""
	@echo "Next steps:"
	@echo "1. Replace placeholder files in avm/projects/demo/ with real content"
	@echo "2. Run: make demo"

# Run basic tests
test:
	@echo "Running basic tests..."
	python -c "import avm.pipeline; print('✓ Pipeline imports successful')"
	python -c "from avm.pipeline.transcribe import check_whisper_availability; print('✓ Whisper check:', check_whisper_availability())"
	python -c "from avm.pipeline.slides import check_playwright_installation; print('✓ Playwright check:', check_playwright_installation())"

# Run demo pipeline
demo:
	@echo "Running demo pipeline..."
	@echo "Note: This will use placeholder files. Replace with real content for actual video generation."
	python avm.py all -p demo --verbose

# Clean build artifacts
clean:
	@echo "Cleaning build artifacts..."
	find . -name "build" -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	find . -name "*.pyo" -delete 2>/dev/null || true
	find . -name ".pytest_cache" -type d -exec rm -rf {} + 2>/dev/null || true

# Check system requirements
check:
	@echo "Checking system requirements..."
	@echo "Python version:"
	@python --version
	@echo ""
	@echo "FFmpeg version:"
	@ffmpeg -version 2>/dev/null | head -1 || echo "❌ FFmpeg not found - install with: brew install ffmpeg"
	@echo ""
	@echo "Dependencies:"
	@python -c "import faster_whisper; print('✓ faster-whisper available')" 2>/dev/null || echo "❌ faster-whisper not installed"
	@python -c "import moviepy; print('✓ moviepy available')" 2>/dev/null || echo "❌ moviepy not installed"
	@python -c "import playwright; print('✓ playwright available')" 2>/dev/null || echo "❌ playwright not installed"
