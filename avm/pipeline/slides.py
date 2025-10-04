"""
Markdown slides rendering to PNG via Playwright.
"""

import re
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

try:
    import markdown_it
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
    
    if not JINJA2_AVAILABLE:
        raise RenderError("jinja2 is required for template rendering")
    
    if not check_playwright_installation():
        raise RenderError(
            "Playwright not properly installed. Run: playwright install chromium"
        )
    
    with Timer(logger, "slides", project, f"Rendering slides from {slides_md.name}"):
        # Load styles and merge with project config
        styles = _load_and_merge_styles(styles_yml, config)
        
        # Load template
        template = _load_template(template_html)
        
        # Parse slides (with fallback for missing file)
        slides = _parse_slides_with_fallback(slides_md, project)
        
        # Render each slide
        png_files = []
        for i, slide_content in enumerate(slides, 1):
            png_path = _render_slide_with_retries(
                slide_content, styles, template, config,
                output_dir / f"slide_{i:03d}.png", i, logger
            )
            png_files.append(png_path)
        
        return png_files


def _load_and_merge_styles(styles_yml: Path, config: Dict[str, Any]) -> Dict[str, Any]:
    """Load styles from YAML and merge with project config."""
    styles = {}
    
    # Load base styles
    if styles_yml.exists():
        try:
            with open(styles_yml, 'r', encoding='utf-8') as f:
                styles = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            raise RenderError(f"Invalid styles YAML: {e}")
    
    # Merge with project config (project config takes precedence)
    project_styles = config.get("slides", {})
    styles.update(project_styles)
    
    # Set defaults
    styles.setdefault("theme", "dark")
    styles.setdefault("font_family", "Inter, system-ui, sans-serif")
    styles.setdefault("brand_color", "#56B3F1")
    styles.setdefault("text_color", "#EDEDED")
    styles.setdefault("bg_color", "#0B0B0E")
    styles.setdefault("heading_size", 64)
    styles.setdefault("body_size", 40)
    styles.setdefault("margin_px", 96)
    styles.setdefault("max_chars_per_line", 52)
    
    return styles


def _load_template(template_html: Path):
    """Load Jinja2 template."""
    if not template_html.exists():
        raise RenderError(f"Template file not found: {template_html}")
    
    try:
        env = Environment(loader=FileSystemLoader(template_html.parent))
        return env.get_template(template_html.name)
    except Exception as e:
        raise RenderError(f"Failed to load template: {e}")


def _parse_slides_with_fallback(slides_md: Path, project: str) -> List[Dict[str, str]]:
    """
    Parse slides.md with fallback to single slide with project title.
    
    Args:
        slides_md: Path to slides markdown file
        project: Project name for fallback
        
    Returns:
        List of slide dictionaries with title and content
    """
    if not slides_md.exists():
        # Fallback: create 1 slide with project title
        return [{
            "title": project.title().replace("_", " ").replace("-", " "),
            "content": f"# {project.title().replace('_', ' ').replace('-', ' ')}\n\nWelcome to this presentation."
        }]
    
    return _parse_slides(slides_md)


def _parse_slides(slides_md: Path) -> List[Dict[str, str]]:
    """
    Parse markdown file into slide sections.
    Split on top-level "##" headings; first "# " as title if present.
    """
    with open(slides_md, 'r', encoding='utf-8') as f:
        content = f.read()
    
    slides = []
    
    # Split on ## headings (top-level)
    sections = re.split(r'^##\s+(.+)$', content, flags=re.MULTILINE)
    
    # Handle first section (before any ##)
    if sections[0].strip():
        first_section = sections[0].strip()
        
        # Check if it starts with # (title)
        title_match = re.match(r'^#\s+(.+)$', first_section, re.MULTILINE)
        if title_match:
            title = title_match.group(1).strip()
            content_start = re.sub(r'^#\s+.+$', '', first_section, flags=re.MULTILINE).strip()
        else:
            title = "Introduction"
            content_start = first_section
        
        slides.append({
            "title": title,
            "content": content_start
        })
    
    # Process remaining sections (## title + content pairs)
    for i in range(1, len(sections), 2):
        if i + 1 < len(sections):
            title = sections[i].strip()
            content = sections[i + 1].strip()
            
            slides.append({
                "title": title,
                "content": content
            })
    
    # If no slides found, create one from entire content
    if not slides:
        title_match = re.match(r'^#\s+(.+)$', content, re.MULTILINE)
        if title_match:
            title = title_match.group(1).strip()
            content_body = re.sub(r'^#\s+.+$', '', content, flags=re.MULTILINE).strip()
        else:
            title = "Slide 1"
            content_body = content
        
        slides.append({
            "title": title,
            "content": content_body
        })
    
    return slides


def _render_slide_with_retries(slide_data: Dict[str, str], styles: Dict[str, Any],
                              template, config: Dict[str, Any],
                              output_path: Path, slide_num: int, logger=None) -> Path:
    """Render a single slide with retries for Playwright flakiness."""
    
    max_retries = 2
    last_error = None
    
    for attempt in range(max_retries + 1):
        try:
            return _render_slide(slide_data, styles, template, config, output_path, slide_num)
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                if logger:
                    logger.warning(f"Slide {slide_num} render attempt {attempt + 1} failed, retrying: {e}")
                time.sleep(0.5)  # Brief delay before retry
            else:
                if logger:
                    logger.error(f"Slide {slide_num} failed after {max_retries + 1} attempts")
                raise RenderError(f"Failed to render slide {slide_num} after {max_retries + 1} attempts: {last_error}")
    
    return output_path


def _render_slide(slide_data: Dict[str, str], styles: Dict[str, Any],
                 template, config: Dict[str, Any],
                 output_path: Path, slide_num: int) -> Path:
    """Render a single slide to PNG."""
    
    # Convert markdown content to HTML
    html_content = _markdown_to_html(slide_data["content"])
    
    # Apply text wrapping based on max_chars_per_line
    html_content = _apply_text_wrapping(html_content, styles)
    
    # Prepare template context
    context = {
        "title": slide_data["title"],
        "content": html_content,
        "slide_num": slide_num,
        "author": config.get("author", ""),
        "logo_path": _get_logo_path(styles, config),
        "logo_width": styles.get("logo", {}).get("width_px", 220),
        "logo_opacity": styles.get("logo", {}).get("opacity", 0.85),
        "theme": styles.get("theme", "dark"),
        "font_family": styles.get("font_family", "Inter, system-ui, sans-serif"),
        "brand_color": styles.get("brand_color", "#56B3F1"),
        "text_color": styles.get("text_color", "#EDEDED"),
        "bg_color": styles.get("bg_color", "#0B0B0E"),
        "heading_size": styles.get("heading_size", 64),
        "body_size": styles.get("body_size", 40),
        "margin_px": styles.get("margin_px", 96)
    }
    
    # Render HTML
    html = template.render(**context)
    
    # Convert HTML to PNG using Playwright
    _html_to_png(html, output_path)
    
    return output_path


def _markdown_to_html(markdown_content: str) -> str:
    """Convert markdown content to HTML using markdown-it-py."""
    if not MARKDOWN_AVAILABLE:
        # Fallback: simple HTML conversion
        return markdown_content.replace('\n', '<br>\n')
    
    md = markdown_it.MarkdownIt()
    return md.render(markdown_content)


def _apply_text_wrapping(html_content: str, styles: Dict[str, Any]) -> str:
    """
    Apply text wrapping based on max_chars_per_line setting.
    Simple greedy wrap by pixel width using approximate character width.
    """
    max_chars = styles.get("max_chars_per_line", 52)
    if max_chars <= 0:
        return html_content
    
    # Simple text wrapping for basic content
    # This is a basic implementation - for production, consider using a proper text layout engine
    lines = html_content.split('\n')
    wrapped_lines = []
    
    for line in lines:
        if len(line.strip()) <= max_chars or line.strip().startswith('<'):
            # Keep short lines or HTML tags as-is
            wrapped_lines.append(line)
        else:
            # Simple word wrapping
            words = line.split()
            current_line = ""
            
            for word in words:
                if len(current_line + " " + word) <= max_chars:
                    if current_line:
                        current_line += " " + word
                    else:
                        current_line = word
                else:
                    if current_line:
                        wrapped_lines.append(current_line)
                    current_line = word
            
            if current_line:
                wrapped_lines.append(current_line)
    
    return '\n'.join(wrapped_lines)


def _get_logo_path(styles: Dict[str, Any], config: Dict[str, Any]) -> Optional[str]:
    """Get logo path if watermark is enabled."""
    if not config.get("watermark", True):
        return None
    
    logo_config = styles.get("logo", {})
    return logo_config.get("path")


def _html_to_png(html_content: str, output_path: Path) -> None:
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
        # Check if it's a Chromium installation issue
        if "chromium" in str(e).lower() or "browser" in str(e).lower():
            raise RenderError(
                f"Playwright Chromium not found. Please run: playwright install chromium\n"
                f"Original error: {e}"
            )
        raise RenderError(f"Failed to render HTML to PNG: {e}")


def install_playwright_browser() -> bool:
    """Install Playwright Chromium browser."""
    try:
        result = subprocess.run([
            sys.executable, "-m", "playwright", "install", "chromium"
        ], check=True, capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError as e:
        error_msg = f"Failed to install Playwright browser: {e}"
        if e.stderr:
            error_msg += f"\nPlaywright error: {e.stderr}"
        raise RenderError(error_msg)
    except FileNotFoundError:
        raise RenderError("Python interpreter not found for Playwright installation.")


# Legacy function for backward compatibility
def render_slides_legacy(slides_md: Path, styles_yml: Path, template_html: Path,
                        output_dir: Path, config: Dict[str, Any],
                        logger=None, project: str = "") -> List[Path]:
    """Legacy render_slides function for backward compatibility."""
    return render_slides(slides_md, styles_yml, template_html, output_dir, config, logger, project)