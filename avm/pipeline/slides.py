"""Markdown slides rendering utilities powered by Playwright."""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:  # Optional dependency hints
    import markdown_it
    MARKDOWN_AVAILABLE = True
except ImportError:  # pragma: no cover - handled at runtime
    MARKDOWN_AVAILABLE = False

try:
    from jinja2 import Environment, FileSystemLoader, Template
    JINJA2_AVAILABLE = True
except ImportError:  # pragma: no cover - handled at runtime
    JINJA2_AVAILABLE = False

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:  # pragma: no cover - handled at runtime
    PLAYWRIGHT_AVAILABLE = False

import yaml

from .errors import RenderError
from .logging import Timer

_BULLET_WRAP_PATTERN = re.compile(r"<li>([^<]{80,})</li>", re.DOTALL)


def check_playwright_installation() -> tuple[bool, str, str]:
    """Verify that Playwright and Chromium are available."""

    if not PLAYWRIGHT_AVAILABLE:
        return False, "Not installed", "Playwright package not installed. Install with: pip install playwright"

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            version = browser.version()
            browser.close()
        return True, f"Chromium {version}", ""
    except Exception as exc:  # pragma: no cover - depends on local install
        message = str(exc)
        if "chromium" in message.lower() or "browser" in message.lower():
            return False, "Chromium not installed", "Chromium browser not found. Run: playwright install chromium"
        return False, "Installation error", f"Playwright installation issue: {exc}"


def render_slide(section_html: str, out_path: Path, config: Dict[str, Any], logger=None) -> Path:
    """Render a single slide HTML string to a PNG at 1920×1080."""

    try:
        _html_to_png(section_html, out_path)
        if logger:
            logger.debug(f"Rendered slide to {out_path}")
        return out_path
    except RenderError:
        raise
    except Exception as exc:
        raise RenderError(f"Failed to render slide HTML -> PNG: {exc}") from exc


def render_slides(
    slides_md: Path,
    styles_yml: Path,
    template_html: Path,
    output_dir: Path,
    config: Dict[str, Any],
    logger=None,
    project: str = "",
) -> List[Path]:
    """Render markdown slides into PNG files using Playwright."""

    if not JINJA2_AVAILABLE:
        raise RenderError("jinja2 is required for template rendering")

    available, _, error_hint = check_playwright_installation()
    if not available:
        raise RenderError(f"Playwright not properly installed: {error_hint}")

    styles = _load_and_merge_styles(styles_yml, config)
    template = _load_template(template_html)
    slides = _parse_slides_with_fallback(slides_md, project)
    output_dir.mkdir(parents=True, exist_ok=True)

    rendered_paths: List[Path] = []

    with Timer(logger, "slides", project, f"Rendering {len(slides)} slides"):
        for index, slide_data in enumerate(slides, start=1):
            if logger:
                logger.info(f"Rendering slide {index} of {len(slides)} — {slide_data['title']}")

            destination = output_dir / f"slide_{index:03d}.png"
            _render_slide_with_retries(
                slide_data,
                styles,
                template,
                config,
                destination,
                index,
                logger,
            )
            rendered_paths.append(destination)

    return rendered_paths


def _render_slide_with_retries(
    slide_data: Dict[str, str],
    styles: Dict[str, Any],
    template: Template,
    config: Dict[str, Any],
    output_path: Path,
    slide_num: int,
    logger=None,
) -> Path:
    max_attempts = 3
    last_error: Optional[Exception] = None

    for attempt in range(1, max_attempts + 1):
        try:
            return _render_slide(slide_data, styles, template, config, output_path, slide_num, logger)
        except Exception as exc:  # pragma: no cover - retriable branch
            last_error = exc
            if attempt < max_attempts:
                delay = 0.5 * (2 ** (attempt - 1))
                if logger:
                    logger.warning(
                        f"Slide {slide_num} render attempt {attempt} failed; retrying in {delay:.1f}s: {exc}"
                    )
                time.sleep(delay)
            else:
                break

    raise RenderError(f"Failed to render slide {slide_num} after {max_attempts} attempts: {last_error}")


def _render_slide(
    slide_data: Dict[str, str],
    styles: Dict[str, Any],
    template: Template,
    config: Dict[str, Any],
    output_path: Path,
    slide_num: int,
    logger=None,
) -> Path:
    content_html = _markdown_to_html(slide_data["content"]) if slide_data.get("content") else ""
    content_html = _apply_text_wrapping(content_html, styles)
    content_html = _wrap_bullet_lines(content_html)

    context = {
        "title": slide_data.get("title", f"Slide {slide_num}"),
        "content": content_html,
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
        "margin_px": styles.get("margin_px", 96),
    }

    slide_html = template.render(**context)
    render_slide(slide_html, output_path, config, logger)
    return output_path


def _wrap_bullet_lines(html: str, max_chars: int = 80) -> str:
    def _wrap(match: re.Match[str]) -> str:
        text = match.group(1).replace("\n", " ").strip()
        words = text.split()
        lines: List[str] = []
        current = ""
        for word in words:
            attempt = f"{current} {word}".strip()
            if len(attempt) <= max_chars:
                current = attempt
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return f"<li>{'<br>'.join(lines)}</li>"

    return _BULLET_WRAP_PATTERN.sub(_wrap, html)


def _load_and_merge_styles(styles_yml: Path, config: Dict[str, Any]) -> Dict[str, Any]:
    styles: Dict[str, Any] = {}

    if styles_yml.exists():
        try:
            with open(styles_yml, "r", encoding="utf-8") as stream:
                styles = yaml.safe_load(stream) or {}
        except yaml.YAMLError as exc:
            raise RenderError(f"Invalid styles YAML: {exc}") from exc

    project_styles = config.get("slides", {})
    styles.update(project_styles)

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


def _load_template(template_html: Path) -> Template:
    if not template_html.exists():
        raise RenderError(f"Template file not found: {template_html}")

    if not JINJA2_AVAILABLE:
        raise RenderError("jinja2 is required for template rendering")

    try:
        environment = Environment(loader=FileSystemLoader(template_html.parent))
        return environment.get_template(template_html.name)
    except Exception as exc:
        raise RenderError(f"Failed to load template: {exc}") from exc


def _parse_slides_with_fallback(slides_md: Path, project: str) -> List[Dict[str, str]]:
    if not slides_md.exists():
        title = project.title().replace("_", " ").replace("-", " ") or "Presentation"
        content = f"# {title}\n\nWelcome to this presentation."
        return [{"title": title, "content": content}]

    return _parse_slides(slides_md)


def _parse_slides(slides_md: Path) -> List[Dict[str, str]]:
    with open(slides_md, "r", encoding="utf-8") as handle:
        raw = handle.read()

    slides: List[Dict[str, str]] = []
    sections = re.split(r"^##\s+(.+)$", raw, flags=re.MULTILINE)

    if sections and sections[0].strip():
        first = sections[0].strip()
        title_match = re.match(r"^#\s+(.+)$", first, re.MULTILINE)
        if title_match:
            title = title_match.group(1).strip()
            body = re.sub(r"^#\s+.+$", "", first, flags=re.MULTILINE).strip()
        else:
            title = "Introduction"
            body = first
        slides.append({"title": title, "content": body})

    for idx in range(1, len(sections), 2):
        if idx + 1 >= len(sections):
            break
        title = sections[idx].strip() or f"Slide {len(slides) + 1}"
        body = sections[idx + 1].strip()
        slides.append({"title": title, "content": body})

    if not slides:
        title_match = re.match(r"^#\s+(.+)$", raw, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else "Slide 1"
        body = re.sub(r"^#\s+.+$", "", raw, flags=re.MULTILINE).strip()
        slides.append({"title": title, "content": body})

    return slides


def _markdown_to_html(markdown_content: str) -> str:
    if not MARKDOWN_AVAILABLE:
        return markdown_content.replace("\n", "<br>\n")

    parser = markdown_it.MarkdownIt()
    return parser.render(markdown_content)


def _apply_text_wrapping(html_content: str, styles: Dict[str, Any]) -> str:
    max_chars = styles.get("max_chars_per_line", 52)
    if max_chars <= 0:
        return html_content

    wrapped_lines: List[str] = []
    for line in html_content.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("<"):
            wrapped_lines.append(line)
            continue

        words = stripped.split()
        current = ""
        for word in words:
            attempt = f"{current} {word}".strip()
            if len(attempt) <= max_chars:
                current = attempt
            else:
                if current:
                    wrapped_lines.append(current + "<br>")
                current = word
        if current:
            wrapped_lines.append(current)

    return "\n".join(wrapped_lines) if wrapped_lines else html_content


def _get_logo_path(styles: Dict[str, Any], config: Dict[str, Any]) -> Optional[str]:
    if not config.get("watermark", True):
        return None
    logo_config = styles.get("logo", {})
    return logo_config.get("path")


def _html_to_png(html_content: str, output_path: Path) -> None:
    if not PLAYWRIGHT_AVAILABLE:
        raise RenderError("Playwright is required for slide rendering")

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            page.set_content(html_content, wait_until="networkidle")
            page.wait_for_timeout(200)  # allow fonts/images to settle
            page.screenshot(
                path=str(output_path),
                type="png",
                clip={"x": 0, "y": 0, "width": 1920, "height": 1080},
            )
            browser.close()
    except Exception as exc:
        message = str(exc)
        if "chromium" in message.lower() or "browser" in message.lower():
            raise RenderError(
                "Playwright Chromium not found. Please run: playwright install chromium"
            ) from exc
        raise RenderError(f"Failed to render HTML to PNG: {exc}") from exc


def install_playwright_browser() -> bool:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except subprocess.CalledProcessError as exc:
        stderr_tail = (exc.stderr or "")[-800:]
        raise RenderError(f"Failed to install Playwright browser\n{stderr_tail}") from exc
    except FileNotFoundError as exc:
        raise RenderError("Python interpreter not found for Playwright installation.") from exc


def render_slides_legacy(
    slides_md: Path,
    styles_yml: Path,
    template_html: Path,
    output_dir: Path,
    config: Dict[str, Any],
    logger=None,
    project: str = "",
) -> List[Path]:
    return render_slides(slides_md, styles_yml, template_html, output_dir, config, logger, project)
