"""
Thumbnail generation using HTML templates and Playwright/Pillow.
"""

import tempfile
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

from jinja2 import Environment, FileSystemLoader

from .errors import RenderError


def generate_thumbnail(config: Dict[str, Any], styles: Dict[str, Any], 
                      output_path: Path, use_html: bool = True,
                      logger=None, project: str = "") -> None:
    """
    Generate thumbnail using HTML template and Playwright/Pillow.
    
    Args:
        config: Project configuration with title, subtitle, brand info
        styles: Styles configuration with colors, fonts, logo
        output_path: Path to output thumbnail (build/thumb.png)
        use_html: Whether to prefer HTML rendering (Playwright) over Pillow
        logger: Logger instance
        project: Project name for logging
    """
    
    # Extract content from config and styles
    title = config.get("title", "Video Title")
    subtitle = config.get("subtitle", "")
    brand_color = styles.get("brand_color", "#FF6B6B")
    logo_path = _get_logo_path(styles, config)
    
    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        if use_html and PLAYWRIGHT_AVAILABLE:
            _generate_thumbnail_html(config, styles, output_path, logger, project)
        elif PILLOW_AVAILABLE:
            _generate_thumbnail_pillow(config, styles, output_path, logger, project)
        else:
            raise RenderError("Either Playwright or Pillow is required for thumbnail generation")
            
    except Exception as e:
        raise RenderError(f"Thumbnail generation failed: {e}")


def _generate_thumbnail_html(config: Dict[str, Any], styles: Dict[str, Any],
                           output_path: Path, logger=None, project: str = "") -> None:
    """
    Generate thumbnail using HTML template and Playwright.
    
    Args:
        config: Project configuration with title, subtitle, brand info
        styles: Styles configuration with colors, fonts, logo
        output_path: Path to output thumbnail
        logger: Logger instance
        project: Project name for logging
    """
    
    # Extract content from config and styles
    title = config.get("title", "Video Title")
    subtitle = config.get("subtitle", "")
    brand_color = styles.get("brand_color", "#FF6B6B")
    logo_path = _get_logo_path(styles, config)
    
    # Get template path
    template_path = Path(__file__).parent.parent / "templates" / "thumb.html"
    
    # Create default template if it doesn't exist
    if not template_path.exists():
        _create_default_thumb_template(template_path)
    
    try:
        # Load and render template
        env = Environment(loader=FileSystemLoader(template_path.parent))
        template = env.get_template(template_path.name)
        
        # Prepare context
        context = {
            "title": title,
            "subtitle": subtitle or "",
            "bg_color": styles.get("bg_color", "#10121A"),
            "text_color": styles.get("text_color", "#FFFFFF"),
            "brand_color": brand_color,
            "font_family": styles.get("font_family", "Inter, system-ui, sans-serif"),
            "logo_path": logo_path,
            "logo_width": styles.get("logo_width", 220),
            "logo_opacity": styles.get("logo_opacity", 0.85)
        }
        
        # Render HTML
        html_content = template.render(**context)
        
        # Convert to PNG using Playwright
        _html_to_png(html_content, output_path, width=1280, height=720)
        
        if logger:
            logger.info(f"Generated thumbnail using Playwright: {output_path}")
            
    except Exception as e:
        raise RenderError(f"Playwright thumbnail generation failed: {e}")


def _generate_thumbnail_pillow(config: Dict[str, Any], styles: Dict[str, Any],
                              output_path: Path, logger=None, project: str = "") -> None:
    """
    Generate thumbnail using Pillow as fallback.
    
    Args:
        config: Project configuration with title, subtitle, brand info
        styles: Styles configuration with colors, fonts, logo
        output_path: Path to output thumbnail
        logger: Logger instance
        project: Project name for logging
    """
    
    if not PILLOW_AVAILABLE:
        raise RenderError("Pillow is required for fallback thumbnail generation")
    
    try:
        # Extract content from config and styles
        title = config.get("title", "Video Title")
        subtitle = config.get("subtitle", "")
        brand_color = styles.get("brand_color", "#FF6B6B")
        logo_path = _get_logo_path(styles, config)
        
        # Create image with 1280x720 default size
        width, height = 1280, 720
        bg_color = styles.get("bg_color", "#10121A")
        text_color = styles.get("text_color", "#FFFFFF")
        
        # Convert hex colors to RGB
        bg_rgb = _hex_to_rgb(bg_color)
        text_rgb = _hex_to_rgb(text_color)
        brand_rgb = _hex_to_rgb(brand_color)
        
        # Create gradient background
        image = _create_gradient_background(width, height, bg_rgb, brand_rgb)
        draw = ImageDraw.Draw(image)
        
        # Try to load fonts
        title_font = _load_font(72)
        subtitle_font = _load_font(36)
        
        # Draw title
        if title_font:
            # Get text dimensions
            bbox = draw.textbbox((0, 0), title, font=title_font)
            title_width = bbox[2] - bbox[0]
            title_height = bbox[3] - bbox[1]
            
            # Center title
            title_x = (width - title_width) // 2
            title_y = (height - title_height) // 2 - 40
            
            # Draw title with shadow for better readability
            draw.text((title_x + 2, title_y + 2), title, fill=(0, 0, 0, 128), font=title_font)
            draw.text((title_x, title_y), title, fill=text_rgb, font=title_font)
        
        # Draw subtitle
        if subtitle and subtitle_font:
            bbox = draw.textbbox((0, 0), subtitle, font=subtitle_font)
            subtitle_width = bbox[2] - bbox[0]
            
            subtitle_x = (width - subtitle_width) // 2
            subtitle_y = title_y + title_height + 20
            
            draw.text((subtitle_x, subtitle_y), subtitle, fill=brand_rgb, font=subtitle_font)
        
        # Add logo if provided (top-right positioning)
        if logo_path and Path(logo_path).exists():
            _add_logo_to_image(image, logo_path, styles)
        
        # Save image
        image.save(output_path, "PNG", quality=95)
        
        if logger:
            logger.info(f"Generated thumbnail using Pillow: {output_path}")
            
    except Exception as e:
        raise RenderError(f"Pillow thumbnail generation failed: {e}")


def _get_logo_path(styles: Dict[str, Any], config: Dict[str, Any]) -> Optional[str]:
    """Get logo path from styles or config."""
    # Check watermark config first
    watermark_config = config.get("watermark", {})
    if watermark_config.get("enabled", False):
        return watermark_config.get("path")
    
    # Check styles
    return styles.get("logo_path")


def _create_gradient_background(width: int, height: int, bg_rgb: tuple, brand_rgb: tuple):
    """Create a gradient background using Pillow."""
    if not PILLOW_AVAILABLE:
        raise RenderError("Pillow is required for gradient background creation")
    
    image = Image.new("RGB", (width, height), bg_rgb)
    draw = ImageDraw.Draw(image)
    
    # Create a subtle gradient effect
    for y in range(height):
        # Interpolate between background and brand color
        ratio = y / height
        r = int(bg_rgb[0] + (brand_rgb[0] - bg_rgb[0]) * ratio * 0.1)
        g = int(bg_rgb[1] + (brand_rgb[1] - bg_rgb[1]) * ratio * 0.1)
        b = int(bg_rgb[2] + (brand_rgb[2] - bg_rgb[2]) * ratio * 0.1)
        
        # Clamp values
        r = max(0, min(255, r))
        g = max(0, min(255, g))
        b = max(0, min(255, b))
        
        draw.line([(0, y), (width, y)], fill=(r, g, b))
    
    return image


def _create_default_thumb_template(template_path: Path) -> None:
    """Create a default thumbnail HTML template."""
    template_path.parent.mkdir(parents=True, exist_ok=True)
    
    default_template = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Video Thumbnail</title>
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
            font-family: {{ font_family }};
            overflow: hidden;
            position: relative;
        }
        
        .container {
            width: 100%;
            height: 100%;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            position: relative;
            padding: 40px;
        }
        
        .title {
            font-size: 72px;
            font-weight: 700;
            color: {{ text_color }};
            text-align: center;
            margin-bottom: 20px;
            text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.5);
            line-height: 1.2;
        }
        
        .subtitle {
            font-size: 36px;
            font-weight: 400;
            color: {{ brand_color }};
            text-align: center;
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
            position: absolute;
            bottom: 60px;
            left: 50%;
            transform: translateX(-50%);
            width: 200px;
            height: 4px;
            background: {{ brand_color }};
            border-radius: 2px;
        }
        
        .gradient-overlay {
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: linear-gradient(135deg, transparent 0%, rgba(0, 0, 0, 0.1) 100%);
            pointer-events: none;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="gradient-overlay"></div>
        
        {% if logo_path %}
        <img src="file://{{ logo_path }}" alt="Logo" class="logo">
        {% endif %}
        
        <h1 class="title">{{ title }}</h1>
        {% if subtitle %}
        <p class="subtitle">{{ subtitle }}</p>
        {% endif %}
        
        <div class="accent-line"></div>
    </div>
</body>
</html>"""
    
    with open(template_path, 'w', encoding='utf-8') as f:
        f.write(default_template)


def _html_to_png(html_content: str, output_path: Path, 
                           width: int = 1280, height: int = 720) -> None:
    """
    Convert HTML to PNG using Playwright.
    
    Args:
        html_content: HTML content to render
        output_path: Path to output PNG file
        width: Image width in pixels
        height: Image height in pixels
    """
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": width, "height": height})
            
            # Set content and wait for load
            page.set_content(html_content)
            page.wait_for_load_state("networkidle")
            
            # Take screenshot
            page.screenshot(
                path=str(output_path),
                full_page=True,
                type="png"
            )
            
            browser.close()
            
    except Exception as e:
        raise RenderError(f"Playwright screenshot failed: {e}")


def _add_logo_to_image(image, logo_path: str, styles: Dict[str, Any]) -> None:
    """
    Add logo to image using Pillow.
    
    Args:
        image: PIL Image object
        logo_path: Path to logo file
        styles: Styles configuration
    """
    
    try:
        logo = Image.open(logo_path)
        
        # Resize logo
        logo_width = styles.get("logo_width", 220)
        logo_height = int(logo.height * logo_width / logo.width)
        logo = logo.resize((logo_width, logo_height), Image.Resampling.LANCZOS)
        
        # Position in top-right corner
        logo_x = image.width - logo_width - 40
        logo_y = 40
        
        # Apply opacity if needed
        logo_opacity = styles.get("logo_opacity", 0.85)
        if logo_opacity < 1.0 and logo.mode == "RGBA":
            alpha = logo.split()[-1]
            alpha = alpha.point(lambda p: int(p * logo_opacity))
            logo.putalpha(alpha)
        
        # Paste logo onto image
        if logo.mode == "RGBA":
            image.paste(logo, (logo_x, logo_y), logo)
        else:
            image.paste(logo, (logo_x, logo_y))
            
    except Exception as e:
        # Ignore logo loading errors
        pass


def _load_font(size: int):
    """
    Load font with specified size.
    
    Args:
        size: Font size in pixels
    
    Returns:
        PIL Font object or None if loading fails
    """
    
    font_paths = [
        "/System/Library/Fonts/Helvetica.ttc",  # macOS
        "/System/Library/Fonts/Arial.ttf",      # macOS alternative
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Linux
        "/Windows/Fonts/arial.ttf",             # Windows
        "/Windows/Fonts/calibri.ttf"            # Windows alternative
    ]
    
    for font_path in font_paths:
        if Path(font_path).exists():
            try:
                return ImageFont.truetype(font_path, size)
            except Exception:
                continue
    
    # Fallback to default font
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def _hex_to_rgb(hex_color: str) -> tuple:
    """
    Convert hex color to RGB tuple.
    
    Args:
        hex_color: Hex color string (e.g., "#FF0000")
    
    Returns:
        RGB tuple (r, g, b)
    """
    
    hex_color = hex_color.lstrip('#')
    if len(hex_color) == 3:
        hex_color = ''.join([c*2 for c in hex_color])
    
    try:
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return (255, 255, 255)  # Default to white


def create_thumbnail_from_video(video_path: Path, output_path: Path,
                               time_sec: float = 5.0) -> None:
    """
    Extract thumbnail from video at specified time using FFmpeg.
    
    Args:
        video_path: Path to input video file
        output_path: Path to output thumbnail file
        time_sec: Time position in seconds
    """
    
    import subprocess
    
    if not video_path.exists():
        raise RenderError(f"Video file not found: {video_path}")
    
    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-ss", str(time_sec),
        "-vframes", "1",
        "-q:v", "2",
        str(output_path)
    ]
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        error_msg = f"Failed to extract thumbnail from video: {e}"
        if e.stderr:
            error_msg += f"\nFFmpeg error: {e.stderr}"
        raise RenderError(error_msg)
    except FileNotFoundError:
        raise RenderError("FFmpeg not found. Please install FFmpeg.")


def create_thumbnail_with_overlay(base_image: Path, overlay_text: str,
                                 output_path: Path, 
                                 styles: Dict[str, Any]) -> None:
    """
    Create thumbnail by adding text overlay to base image.
    
    Args:
        base_image: Path to base image file
        overlay_text: Text to overlay
        output_path: Path to output image file
        styles: Styles configuration
    """
    
    if not PILLOW_AVAILABLE:
        raise RenderError("Pillow is required for image overlay")
    
    if not base_image.exists():
        raise RenderError(f"Base image not found: {base_image}")
    
    try:
        # Load base image
        image = Image.open(base_image)
        
        # Create overlay
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        
        # Load font
        font = _load_font(48)
        text_color = styles.get("text_color", "#FFFFFF")
        text_rgb = _hex_to_rgb(text_color)
        
        # Draw text
        if font:
            bbox = draw.textbbox((0, 0), overlay_text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            
            text_x = (image.width - text_width) // 2
            text_y = image.height - text_height - 40
            
            # Draw text with shadow
            draw.text((text_x + 2, text_y + 2), overlay_text, fill=(0, 0, 0, 128), font=font)
            draw.text((text_x, text_y), overlay_text, fill=text_rgb, font=font)
        
        # Composite images
        if image.mode != "RGBA":
            image = image.convert("RGBA")
        
        final_image = Image.alpha_composite(image, overlay)
        final_image = final_image.convert("RGB")
        
        # Save
        final_image.save(output_path, "PNG", quality=95)
        
    except Exception as e:
        raise RenderError(f"Failed to create thumbnail with overlay: {e}")


# Legacy functions for backward compatibility
def generate_thumbnail_legacy(config: Dict[str, Any], styles: Dict[str, Any],
                             output_path: Path, use_html: bool = True,
                             logger=None, project: str = "") -> None:
    """
    Legacy function for backward compatibility.
    
    Args:
        config: Project configuration
        styles: Global styles configuration
        output_path: Path to output thumbnail
        use_html: Whether to use HTML template or Pillow
        logger: Logger instance
        project: Project name for logging
    """
    
    # Extract values from config
    title = config.get("title", "Untitled")
    subtitle = config.get("subtitle", "")
    brand_color = styles.get("brand_color", "#56B3F1")
    logo_path = styles.get("logo", {}).get("path")
    
    # Use new function
    generate_thumbnail(title, subtitle, brand_color, logo_path, output_path, 
                      styles, logger, project)