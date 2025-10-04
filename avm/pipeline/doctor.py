"""
Doctor module for checking system dependencies and health.
"""

import subprocess
import sys
import platform
from pathlib import Path
from typing import Dict, List, Tuple, Optional

from .errors import AVMError


def doctor(logger=None, project: str = "") -> Dict[str, Dict[str, str]]:
    """
    Comprehensive system health check for AVM dependencies.
    
    Args:
        logger: Logger instance
        project: Project name for logging
    
    Returns:
        Dictionary with check results for all components
    """
    
    if logger:
        logger.info("Running AVM Doctor system health check")
    
    results = {}
    
    # Python version check
    is_ok, version, error = check_python_version()
    results["python"] = {
        "status": "✅ OK" if is_ok else "❌ FAIL",
        "version": version,
        "error": error
    }
    
    # FFmpeg check
    is_ok, version, error = check_ffmpeg()
    results["ffmpeg"] = {
        "status": "✅ OK" if is_ok else "❌ FAIL",
        "version": version,
        "error": error
    }
    
    # FFprobe check
    is_ok, version, error = check_ffprobe()
    results["ffprobe"] = {
        "status": "✅ OK" if is_ok else "❌ FAIL",
        "version": version,
        "error": error
    }
    
    # Whisper availability check
    is_ok, version, error = check_whisper()
    results["whisper"] = {
        "status": "✅ OK" if is_ok else "❌ FAIL",
        "version": version,
        "error": error
    }
    
    # Playwright Chromium check
    is_ok, version, error = check_playwright_chromium()
    results["playwright"] = {
        "status": "✅ OK" if is_ok else "❌ FAIL",
        "version": version,
        "error": error
    }
    
    # Font availability check
    is_ok, version, error = check_fonts()
    results["fonts"] = {
        "status": "✅ OK" if is_ok else "❌ FAIL",
        "info": version,
        "error": error
    }
    
    # YUV420P support check
    is_ok, version, error = check_yuv420p_support()
    results["yuv420p"] = {
        "status": "✅ OK" if is_ok else "❌ FAIL",
        "info": version,
        "error": error
    }
    
    # Print results
    print_doctor_results(results)
    
    # Suggest fixes for any failures
    suggest_fixes(results)
    
    if logger:
        logger.info("AVM Doctor system health check completed")
    
    return results


def check_python_version() -> Tuple[bool, str, str]:
    """
    Check if Python version meets requirements (>= 3.11).
    
    Returns:
        (is_compatible, version, error_message)
    """
    version = sys.version_info
    version_str = f"{version.major}.{version.minor}.{version.micro}"
    
    if version >= (3, 11):
        return True, version_str, ""
    else:
        return False, version_str, f"Python {version_str} is too old. AVM requires Python 3.11+"


def check_ffmpeg() -> Tuple[bool, str, str]:
    """
    Check if FFmpeg is available and get version info.
    
    Returns:
        (is_available, version, error_message)
    """
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"], 
            capture_output=True, 
            text=True, 
            timeout=10
        )
        if result.returncode == 0:
            # Extract version from first line
            version_line = result.stdout.split('\n')[0]
            version = version_line.replace('ffmpeg version ', '').split(' ')[0]
            return True, version, ""
        else:
            return False, "", f"FFmpeg returned error code {result.returncode}"
    except FileNotFoundError:
        return False, "", "FFmpeg not found in PATH"
    except subprocess.TimeoutExpired:
        return False, "", "FFmpeg check timed out"
    except Exception as e:
        return False, "", f"Error checking FFmpeg: {e}"


def check_ffprobe() -> Tuple[bool, str, str]:
    """
    Check if FFprobe is available and get version info.
    
    Returns:
        (is_available, version, error_message)
    """
    try:
        result = subprocess.run(
            ["ffprobe", "-version"], 
            capture_output=True, 
            text=True, 
            timeout=10
        )
        if result.returncode == 0:
            # Extract version from first line
            version_line = result.stdout.split('\n')[0]
            version = version_line.replace('ffprobe version ', '').split(' ')[0]
            return True, version, ""
        else:
            return False, "", f"FFprobe returned error code {result.returncode}"
    except FileNotFoundError:
        return False, "", "FFprobe not found in PATH"
    except subprocess.TimeoutExpired:
        return False, "", "FFprobe check timed out"
    except Exception as e:
        return False, "", f"Error checking FFprobe: {e}"


def check_whisper() -> Tuple[bool, str, str]:
    """
    Check if Whisper (faster-whisper or openai-whisper) is available.
    
    Returns:
        (is_available, version, error_message)
    """
    # Check faster-whisper first (preferred)
    try:
        import faster_whisper
        version = getattr(faster_whisper, '__version__', 'unknown')
        return True, f"faster-whisper {version}", ""
    except ImportError:
        pass
    
    # Check openai-whisper as fallback
    try:
        import whisper
        version = getattr(whisper, '__version__', 'unknown')
        return True, f"openai-whisper {version}", ""
    except ImportError:
        pass
    
    return False, "", "Neither faster-whisper nor openai-whisper is installed"


def check_playwright_chromium() -> Tuple[bool, str, str]:
    """
    Check if Playwright is installed and Chromium browser is available.
    
    Returns:
        (is_available, version, error_message)
    """
    try:
        # Check if playwright module is available
        import playwright
        version = getattr(playwright, '__version__', 'unknown')
        
        # Check if Chromium is installed by trying to launch it
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                browser.close()
            return True, f"playwright {version} with Chromium", ""
        except Exception as e:
            return False, f"playwright {version}", f"Chromium not installed: {e}"
            
    except ImportError:
        return False, "", "Playwright not installed"


def check_fonts() -> Tuple[bool, str, str]:
    """
    Check if system fonts are available for caption rendering.
    
    Returns:
        (is_available, font_info, error_message)
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
        
        # Try to load common system fonts for captions
        font_paths = [
            "/System/Library/Fonts/Helvetica.ttc",  # macOS
            "/System/Library/Fonts/Arial.ttf",      # macOS alternative
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Linux
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",  # Linux alternative
            "C:/Windows/Fonts/arial.ttf",  # Windows
            "C:/Windows/Fonts/calibri.ttf"  # Windows alternative
        ]
        
        available_fonts = []
        for font_path in font_paths:
            if Path(font_path).exists():
                available_fonts.append(Path(font_path).name)
        
        if available_fonts:
            return True, f"Found fonts: {', '.join(available_fonts)}", ""
        else:
            # Try default font as fallback
            try:
                font = ImageFont.load_default()
                return True, "Using default PIL font", ""
            except Exception:
                return False, "", "No suitable fonts found for caption rendering"
                
    except ImportError:
        return False, "", "Pillow (PIL) not installed for font checking"


def check_yuv420p_support() -> Tuple[bool, str, str]:
    """
    Check if FFmpeg supports yuv420p pixel format.
    
    Returns:
        (is_supported, info, error_message)
    """
    try:
        # Test yuv420p support by trying to encode a test video
        result = subprocess.run([
            "ffmpeg", "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=1",
            "-pix_fmt", "yuv420p", "-t", "0.1", "-f", "null", "-"
        ], capture_output=True, text=True, timeout=15)
        
        if result.returncode == 0:
            return True, "yuv420p pixel format supported", ""
        else:
            return False, "", f"yuv420p not supported: {result.stderr[:100]}"
            
    except FileNotFoundError:
        return False, "", "FFmpeg not found (required for yuv420p check)"
    except subprocess.TimeoutExpired:
        return False, "", "yuv420p check timed out"
    except Exception as e:
        return False, "", f"Error checking yuv420p support: {e}"


def print_doctor_results(results: Dict[str, Dict[str, str]]) -> None:
    """
    Print doctor check results in a formatted way.
    
    Args:
        results: Results from doctor check
    """
    print("🏥 AVM Doctor - System Health Check")
    print("=" * 50)
    
    for component, info in results.items():
        status = info["status"]
        version_key = "version" if "version" in info else "info"
        version = info.get(version_key, "")
        error = info.get("error", "")
        
        # Format component name
        component_name = component.replace("_", " ").title()
        
        print(f"\n{status} {component_name}")
        if version:
            print(f"   Version: {version}")
        if error:
            print(f"   Error: {error}")
        else:
            print(f"   Status: Working correctly")


def suggest_fixes(results: Dict[str, Dict[str, str]]) -> None:
    """
    Suggest actionable fixes for failed checks.
    
    Args:
        results: Results from doctor check
    """
    failed_components = [comp for comp, info in results.items() 
                        if "❌ FAIL" in info["status"]]
    
    if not failed_components:
        print("\n🎉 All checks passed! Your system is ready for AVM.")
        return
    
    print(f"\n🔧 Installation tips for {len(failed_components)} failed component(s):")
    print("=" * 60)
    
    # Get platform-specific installation commands
    system = platform.system().lower()
    
    for component in failed_components:
        print(f"\n📦 {component.replace('_', ' ').title()}:")
        
        if component == "python":
            print("   Python 3.11+ is required. Install from:")
            print("   • https://python.org/downloads/")
            print("   • Use pyenv: pyenv install 3.11.0")
            
        elif component == "ffmpeg":
            if system == "darwin":  # macOS
                print("   brew install ffmpeg")
            elif system == "linux":
                print("   sudo apt update && sudo apt install ffmpeg")
            elif system == "windows":
                print("   Download from https://ffmpeg.org/download.html")
            else:
                print("   Install FFmpeg from https://ffmpeg.org/download.html")
                
        elif component == "ffprobe":
            print("   FFprobe comes with FFmpeg. Install FFmpeg first.")
            
        elif component == "whisper":
            print("   pip install faster-whisper")
            print("   # OR")
            print("   pip install openai-whisper")
            
        elif component == "playwright":
            print("   pip install playwright")
            print("   playwright install chromium")
            
        elif component == "fonts":
            if system == "darwin":  # macOS
                print("   Fonts should be available by default.")
                print("   If missing, install Xcode Command Line Tools:")
                print("   xcode-select --install")
            elif system == "linux":
                print("   sudo apt install fonts-dejavu-core")
                print("   # OR")
                print("   sudo apt install fonts-liberation")
            elif system == "windows":
                print("   Windows should have fonts by default.")
                print("   If missing, install Arial/Calibri from Windows Fonts.")
                
        elif component == "yuv420p":
            print("   yuv420p support comes with FFmpeg.")
            print("   Make sure you have a recent FFmpeg version.")
            print("   Update FFmpeg if the issue persists.")


def get_installation_commands() -> Dict[str, List[str]]:
    """
    Get platform-specific installation commands for missing dependencies.
    
    Returns:
        Dictionary mapping component names to installation commands
    """
    system = platform.system().lower()
    
    commands = {
        "ffmpeg": {
            "macos": ["brew install ffmpeg"],
            "ubuntu": ["sudo apt update", "sudo apt install ffmpeg"],
            "windows": ["Download from https://ffmpeg.org/download.html"]
        },
        "playwright": {
            "all": ["pip install playwright", "playwright install chromium"]
        },
        "whisper": {
            "all": ["pip install faster-whisper", "# or", "pip install openai-whisper"]
        },
        "fonts": {
            "macos": ["xcode-select --install"],
            "ubuntu": ["sudo apt install fonts-dejavu-core"],
            "windows": ["Fonts should be available by default"]
        }
    }
    
    return commands


# Legacy functions for backward compatibility
def check_playwright() -> Tuple[bool, str, str]:
    """Legacy function for backward compatibility."""
    return check_playwright_chromium()


def check_moviepy() -> Tuple[bool, str, str]:
    """
    Check if MoviePy is available.
    
    Returns:
        (is_available, version, error_message)
    """
    try:
        import moviepy
        version = getattr(moviepy, '__version__', 'unknown')
        return True, version, ""
    except ImportError:
        return False, "", "MoviePy not installed"


def check_disk_space(path: Path, required_gb: float = 5.0) -> Tuple[bool, str, str]:
    """
    Check available disk space at the given path.
    
    Args:
        path: Path to check disk space for
        required_gb: Required space in GB
        
    Returns:
        (has_space, available_info, error_message)
    """
    try:
        import shutil
        
        # Get disk usage
        total, used, free = shutil.disk_usage(path)
        
        # Convert to GB
        free_gb = free / (1024**3)
        total_gb = total / (1024**3)
        
        available_info = f"{free_gb:.1f}GB free of {total_gb:.1f}GB total"
        
        if free_gb >= required_gb:
            return True, available_info, ""
        else:
            return False, available_info, f"Only {free_gb:.1f}GB free, need {required_gb}GB"
            
    except Exception as e:
        return False, "", f"Error checking disk space: {e}"


def run_doctor_check(project_root: Path, verbose: bool = False) -> Dict[str, Dict[str, str]]:
    """Legacy function for backward compatibility."""
    return doctor()