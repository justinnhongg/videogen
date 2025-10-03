"""
Thumbnail generation using HTML templates or Pillow.
"""

from pathlib import Path
from typing import Dict, Any, Optional

try:
    from PIL import Image, ImageDraw, ImageFont
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

from jinja2 import Environment, FileSystemLoader, Template

from .errors import RenderError


def generate_thumbnail(config: Dict[str, Any], styles: Dict[str, Any],
                      output_path: Path, use_html: bool = True,
                      logger=None, project: str = "") -> None:
    """
    Generate thumbnail image for the video.
    
    Args:
        config: Project configuration
        styles: Global styles configuration
        output_path: Path to output thumbnail
        use_html: Whether to use HTML template or Pillow
        logger: Logger instance
        project: Project name for logging
    """
    
    thumbnail_config = config.get("thumbnail", {})
    
    if use_html and PLAYWRIGHT_AVAILABLE:
        _generate_thumbnail_html(config, styles, output_path, logger, project)
    elif PILLOW_AVAILABLE:
        _generate_thumbnail_pillow(config, styles, output_path, logger, project)
    else:
        raise RenderError("Either Playwright or Pillow is required for thumbnail generation")


def _generate_thumbnail_html(config: Dict[str, Any], styles: Dict[str, Any],
                            output_path: Path, logger=None, project: str = "") -> None:
    """Generate thumbnail using HTML template and Playwright."""
    
    thumbnail_config = config.get("thumbnail", {})
    title = thumbnail_config.get("title", config.get("title", "Untitled"))
    subtitle = thumbnail_config.get("subtitle", "")
    bg_color = thumbnail_config.get("bg", "#10121A")
    
    # Load HTML template
    template_path = Path(__file__).parent.parent / "templates" / "thumb.html"
    
    if not template_path.exists():
        # Create default template
        _create_default_thumb_template(template_path)
    
    try:
        env = Environment(loader=FileSystemLoader(template_path.parent))
        template = env.get_template(template_path.name)
        
        # Prepare context
        context = {
            "title": title,
            "subtitle": subtitle,
            "bg_color": bg_color,
            "text_color": styles.get("text_color", "#FFFFFF"),
            "brand_color": styles.get("brand_color", "#56B3F1"),
            "font_family": styles.get("font_family", "Inter, system-ui, sans-serif"),
            "logo_path": _get_logo_path(styles, config),
            "logo_width": styles.get("logo", {}).get("width_px", 220),
            "logo_opacity": styles.get("logo", {}).get("opacity", 0.85)
        }
        
        # Render HTML
        html_content = template.render(**context)
        
        # Convert to PNG
        _html_to_png(html_content, output_path, width=1280, height=720)
        
    except Exception as e:
        raise RenderError(f"HTML thumbnail generation failed: {e}")


def _generate_thumbnail_pillow(config: Dict[str, Any], styles: Dict[str, Any],
                              output_path: Path, logger=None, project: str = "") -> None:
    """Generate thumbnail using Pillow."""
    
    thumbnail_config = config.get("thumbnail", {})
    title = thumbnail_config.get("title", config.get("title", "Untitled"))
    subtitle = thumbnail_config.get("subtitle", "")
    bg_color = thumbnail_config.get("bg", "#10121A")
    
    # Create image
    width, height = 1280, 720
    image = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(image)
    
    # Try to load fonts
    try:
        title_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 72)
        subtitle_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 36)
    except:
        try:
            title_font = ImageFont.load_default()
            subtitle_font = ImageFont.load_default()
        except:
            title_font = None
            subtitle_font = None
    
    text_color = styles.get("text_color", "#FFFFFF")
    brand_color = styles.get("brand_color", "#56B3F1")
    
    # Draw title
    if title_font:
        title_bbox = draw.textbbox((0, 0), title, font=title_font)
        title_width = title_bbox[2] - title_bbox[0]
        title_height = title_bbox[3] - title_bbox[1]
        
        title_x = (width - title_width) // 2
        title_y = (height - title_height) // 2 - 40
        
        draw.text((title_x, title_y), title, fill=text_color, font=title_font)
    
    # Draw subtitle
    if subtitle and subtitle_font:
        subtitle_bbox = draw.textbbox((0, 0), subtitle, font=subtitle_font)
        subtitle_width = subtitle_bbox[2] - subtitle_bbox[0]
        
        subtitle_x = (width - subtitle_width) // 2
        subtitle_y = title_y + title_height + 20
        
        draw.text((subtitle_x, subtitle_y), subtitle, fill=brand_color, font=subtitle_font)
    
    # Add logo if available
    logo_path = _get_logo_path(styles, config)
    if logo_path and Path(logo_path).exists():
        try:
            logo = Image.open(logo_path)
            logo_width = styles.get("logo", {}).get("width_px", 220)
            logo_height = int(logo.height * logo_width / logo.width)
            logo = logo.resize((logo_width, logo_height))
            
            # Position in top-right
            logo_x = width - logo_width - 40
            logo_y = 40
            
            # Apply opacity
            if logo.mode == "RGBA":
                logo = logo.convert("RGBA")
                alpha = logo.split()[-1]
                alpha = alpha.point(lambda p: int(p * 0.85))
                logo.putalpha(alpha)
            
            image.paste(logo, (logo_x, logo_y), logo if logo.mode == "RGBA" else None)
        except Exception:
            pass  # Ignore logo loading errors
    
    # Save image
    image.save(output_path, "PNG", quality=95)


def _create_default_thumb_template(template_path: Path) -> None:
    """Create default thumbnail HTML template."""
    
    template_path.parent.mkdir(parents=True, exist_ok=True)
    
    template_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Thumbnail</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            width: 1280px;
            height: 720px;
            background: {{ bg_color }};
            color: {{ text_color }};
            font-family: {{ font_family }};
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            position: relative;
            overflow: hidden;
        }
        
        .container {
            text-align: center;
            max-width: 1000px;
            padding: 0 40px;
        }
        
        .title {
            font-size: 72px;
            font-weight: bold;
            line-height: 1.1;
            margin-bottom: 20px;
            color: {{ text_color }};
        }
        
        .subtitle {
            font-size: 36px;
            color: {{ brand_color }};
            opacity: 0.9;
        }
        
        .logo {
            position: absolute;
            top: 40px;
            right: 40px;
            width: {{ logo_width }}px;
            opacity: {{ logo_opacity }};
        }
        
        .accent-line {
            width: 200px;
            height: 6px;
            background: {{ brand_color }};
            margin: 0 auto 40px;
            border-radius: 3px;
        }
    </style>
</head>
<body>
    {% if logo_path %}
    <img src="{{ logo_path }}" alt="Logo" class="logo">
    {% endif %}
    
    <div class="container">
        <div class="accent-line"></div>
        <h1 class="title">{{ title }}</h1>
        {% if subtitle %}
        <p class="subtitle">{{ subtitle }}</p>
        {% endif %}
    </div>
</body>
</html>"""
    
    with open(template_path, 'w', encoding='utf-8') as f:
        f.write(template_content)


def _html_to_png(html_content: str, output_path: Path, 
                 width: int = 1280, height: int = 720) -> None:
    """Convert HTML to PNG using Playwright."""
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": width, "height": height})
            
            page.set_content(html_content)
            page.wait_for_load_state("networkidle")
            
            page.screenshot(
                path=str(output_path),
                full_page=True,
                type="png"
            )
            
            browser.close()
            
    except Exception as e:
        raise RenderError(f"Failed to convert HTML to PNG: {e}")


def _get_logo_path(styles: Dict[str, Any], config: Dict[str, Any]) -> Optional[str]:
    """Get logo path if watermark is enabled."""
    if not config.get("watermark", True):
        return None
    
    logo_config = styles.get("logo", {})
    return logo_config.get("path")


def create_thumbnail_from_video(video_path: Path, output_path: Path,
                               time_sec: float = 5.0) -> None:
    """Extract thumbnail from video at specified time."""
    
    import subprocess
    
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-ss", str(time_sec),
        "-vframes", "1",
        "-q:v", "2",
        str(output_path)
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise RenderError(f"Failed to extract thumbnail from video: {e}")


def create_thumbnail_with_overlay(base_image: Path, overlay_text: str,
                                 output_path: Path, 
                                 styles: Dict[str, Any]) -> None:
    """Create thumbnail by adding text overlay to base image."""
    
    if not PILLOW_AVAILABLE:
        raise RenderError("Pillow is required for image overlay")
    
    # Load base image
    image = Image.open(base_image)
    
    # Create overlay
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    
    # Try to load font
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 48)
    except:
        font = ImageFont.load_default()
    
    text_color = styles.get("text_color", "#FFFFFF")
    
    # Draw text
    bbox = draw.textbbox((0, 0), overlay_text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    text_x = (image.width - text_width) // 2
    text_y = image.height - text_height - 40
    
    draw.text((text_x, text_y), overlay_text, fill=text_color, font=font)
    
    # Composite images
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    
    final_image = Image.alpha_composite(image, overlay)
    final_image = final_image.convert("RGB")
    
    # Save
    final_image.save(output_path, "PNG", quality=95)
