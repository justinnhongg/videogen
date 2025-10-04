# AVM - Audio to Video Maker Makefile
# Provides convenient commands for setup and usage

.PHONY: help install setup test clean demo doctor

# Default target
help:
	@echo "AVM - Audio to Video Maker"
	@echo ""
	@echo "Available commands:"
	@echo "  make install     - Install Python dependencies"
	@echo "  make setup       - Complete setup (install + playwright)"
	@echo "  make test        - Run all tests"
	@echo "  make demo        - Run demo pipeline end-to-end"
	@echo "  make doctor      - Check system health"
	@echo "  make clean       - Clean build artifacts"
	@echo "  make help        - Show this help"

# Install Python dependencies
install:
	@echo "Installing Python dependencies..."
	pip install -r requirements.txt
	@echo "✅ Dependencies installed successfully!"

# Complete setup including Playwright browser
setup: install
	@echo "Setting up Playwright browser..."
	python -m playwright install chromium
	@echo "✅ Setup complete!"
	@echo ""
	@echo "Next steps:"
	@echo "1. Replace placeholder files in avm/projects/demo/ with real content"
	@echo "2. Run: make demo"

# Run all tests
test:
	@echo "Running AVM tests..."
	@echo ""
	@echo "Testing timeline generation..."
	python -m pytest avm/tests/test_timeline.py -q
	@echo ""
	@echo "Testing caption processing..."
	python -m pytest avm/tests/test_captions.py -q
	@echo ""
	@echo "Testing pipeline imports..."
	python -c "import avm.pipeline; print('✅ Pipeline imports successful')"
	@echo ""
	@echo "Testing Whisper availability..."
	python -c "from avm.pipeline.transcribe import check_whisper_availability; print('✅ Whisper check:', check_whisper_availability())"
	@echo ""
	@echo "Testing Playwright installation..."
	python -c "from avm.pipeline.slides import check_playwright_installation; print('✅ Playwright check:', check_playwright_installation())"
	@echo ""
	@echo "✅ All tests completed!"

# Run demo pipeline end-to-end
demo:
	@echo "Running demo pipeline end-to-end..."
	@echo "Note: This will use placeholder files. Replace with real content for actual video generation."
	@echo ""
	python avm.py all -p demo --verbose
	@echo ""
	@echo "✅ Demo pipeline completed!"
	@echo "Check avm/projects/demo/build/ for generated artifacts."

# Check system health
doctor:
	@echo "Running system health check..."
	python avm.py doctor
	@echo ""
	@echo "✅ System health check completed!"

# Clean build artifacts
clean:
	@echo "Cleaning build artifacts..."
	find . -name "build" -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	find . -name "*.pyo" -delete 2>/dev/null || true
	find . -name ".pytest_cache" -type d -exec rm -rf {} + 2>/dev/null || true
	@echo "✅ Cleanup completed!"

# Check system requirements (legacy)
check: doctor

# Development targets
.PHONY: lint format

# Run linting
lint:
	@echo "Running code linting..."
	python -m flake8 avm/ --max-line-length=100 --ignore=E203,W503
	@echo "✅ Linting completed!"

# Format code
format:
	@echo "Formatting code..."
	python -m black avm/ --line-length=100
	@echo "✅ Code formatting completed!"

# Quick development setup
dev-setup: install setup
	@echo "Setting up development environment..."
	pip install pytest flake8 black
	@echo "✅ Development environment ready!"

# Full test suite
test-all: test
	@echo "Running additional integration tests..."
	python avm.py doctor
	@echo "✅ Full test suite completed!"

# Install optional dependencies for better performance
install-optional:
	@echo "Installing optional performance dependencies..."
	pip install faster-whisper moviepy pillow
	@echo "✅ Optional dependencies installed!"

# Create a new project template
new-project:
	@echo "Creating new project template..."
	@read -p "Enter project name: " name; \
	mkdir -p avm/projects/$$name; \
	cp avm/projects/demo/config.yml avm/projects/$$name/; \
	cp avm/projects/demo/slides.md avm/projects/$$name/; \
	echo "✅ Project '$$name' created in avm/projects/$$name/"
	@echo "Add your audio.wav file and customize config.yml and slides.md"