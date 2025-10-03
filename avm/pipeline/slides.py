"""
Markdown slides rendering to PNG via Playwright.
"""

import re
import subprocess
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional

try:
    import markdown
    MARKDOWN_AVAILABLE = True
except ImportError:
    MARKDOWN_AVAILABLE = False

try:
    from jinja2 import Environment, FileSystemLoader, Template
    JINJA2_AVAILABLE = True
except ImportError:
    JINJA2_AVAILABLE = False

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

import yaml

from .errors import RenderError
from .logging import Timer


def check_playwright_installation() -> bool:
    """Check if Playwright and Chromium are properly installed."""
    if not PLAYWRIGHT_AVAILABLE:
        return False
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        return True
    except Exception:
        return False


def render_slides(slides_md: Path, styles_yml: Path, template_html: Path,
                 output_dir: Path, config: Dict[str, Any],
                 logger=None, project: str = "") -> List[Path]:
    """
    Render markdown slides to PNG images.
    
    Args:
        slides_md: Path to markdown slides file
        styles_yml: Path to styles configuration
        template_html: Path to HTML template
        output_dir: Directory to save PNG files
        config: Project configuration
        logger: Logger instance
        project: Project name for logging
        
    Returns:
        List of generated PNG file paths
    """
    
    if not slides_md.exists():
        raise RenderError(f"Slides file not found: {slides_md}")
    
    if not MARKDOWN_AVAILABLE:
        raise RenderError("markdown-it-py is required for slide rendering")
    
    if not JINJA2_AVAILABLE:
        raise RenderError("jinja2 is required for template rendering")
    
    if not check_playwright_installation():
        raise RenderError(
            "Playwright not properly installed. Run: playwright install chromium"
        )
    
    with Timer(logger, "slides", project, f"Rendering slides from {slides_md.name}"):
        # Load styles
        styles = _load_styles(styles_yml)
        
        # Load template
        template = _load_template(template_html)
        
        # Parse slides
        slides = _parse_slides(slides_md)
        
        # Render each slide
        png_files = []
        for i, slide_content in enumerate(slides, 1):
            png_path = _render_slide(
                slide_content, styles, template, config,
                output_dir / f"{i:04d}.png", i
            )
            png_files.append(png_path)
        
        return png_files


def _load_styles(styles_path: Path) -> Dict[str, Any]:
    """Load styles configuration from YAML."""
    if not styles_path.exists():
        raise RenderError(f"Styles file not found: {styles_path}")
    
    try:
        with open(styles_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise RenderError(f"Invalid styles YAML: {e}")


def _load_template(template_path: Path) -> Template:
    """Load Jinja2 template."""
    if not template_path.exists():
        raise RenderError(f"Template file not found: {template_path}")
    
    try:
        env = Environment(loader=FileSystemLoader(template_path.parent))
        return env.get_template(template_path.name)
    except Exception as e:
        raise RenderError(f"Failed to load template: {e}")


def _parse_slides(md_path: Path) -> List[Dict[str, str]]:
    """Parse markdown file into slide sections, splitting on H2 (##) headers."""
    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Split on H2 headers (##) only
    h2_pattern = r'^##\s+(.+)$'
    slides = []
    current_slide = {"title": "", "content": ""}
    
    lines = content.split('\n')
    
    for line in lines:
        match = re.match(h2_pattern, line)
        if match:
            # Save previous slide if it has content
            if current_slide["title"] or current_slide["content"].strip():
                slides.append(current_slide.copy())
            
            # Start new slide
            current_slide = {
                "title": match.group(1).strip(),
                "content": ""
            }
        else:
            # Add line to current slide content
            current_slide["content"] += line + "\n"
    
    # Add final slide
    if current_slide["title"] or current_slide["content"].strip():
        slides.append(current_slide)
    
    # If no H2 headers found, treat entire content as one slide
    if not slides:
        slides.append({
            "title": "Slide 1",
            "content": content
        })
    
    return slides


def _render_slide(slide_data: Dict[str, str], styles: Dict[str, Any],
                 template: Template, config: Dict[str, Any],
                 output_path: Path, slide_num: int) -> Path:
    """Render a single slide to PNG."""
    
    # Convert markdown content to HTML
    html_content = _markdown_to_html(slide_data["content"])
    
    # Prepare template context
    context = {
        "title": slide_data["title"],
        "content": html_content,
        "slide_num": slide_num,
        "author": config.get("author", ""),
        "logo_path": _get_logo_path(styles, config),
        "logo_width": styles.get("logo", {}).get("width_px", 220),
        "logo_opacity": styles.get("logo", {}).get("opacity", 0.85),
        **styles  # Include all style variables
    }
    
    # Render HTML
    html = template.render(**context)
    
    # Convert HTML to PNG using Playwright
    _html_to_png(html, output_path, styles)
    
    return output_path


def _markdown_to_html(markdown_content: str) -> str:
    """Convert markdown content to HTML."""
    md = markdown.Markdown(
        extensions=['fenced_code', 'tables', 'nl2br']
    )
    return md.convert(markdown_content)


def _get_logo_path(styles: Dict[str, Any], config: Dict[str, Any]) -> Optional[str]:
    """Get logo path if watermark is enabled."""
    if not config.get("watermark", True):
        return None
    
    logo_config = styles.get("logo", {})
    return logo_config.get("path")


def _html_to_png(html_content: str, output_path: Path, styles: Dict[str, Any]) -> None:
    """Convert HTML to PNG using Playwright at 1920x1080."""
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(
                viewport={"width": 1920, "height": 1080}
            )
            
            # Set content
            page.set_content(html_content)
            
            # Wait for fonts and images to load
            page.wait_for_load_state("networkidle")
            
            # Take screenshot at exact 1920x1080
            page.screenshot(
                path=str(output_path),
                type="png",
                clip={"x": 0, "y": 0, "width": 1920, "height": 1080}
            )
            
            browser.close()
            
    except Exception as e:
        raise RenderError(f"Failed to render HTML to PNG: {e}")


def install_playwright_browser() -> bool:
    """Install Playwright Chromium browser."""
    try:
        subprocess.run([
            sys.executable, "-m", "playwright", "install", "chromium"
        ], check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError:
        return False
