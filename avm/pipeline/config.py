"""
Configuration management with proper precedence handling.
"""

from pathlib import Path
from typing import Dict, Any, Optional
import yaml

from .errors import ConfigError


def load_default_config() -> Dict[str, Any]:
    """Load default configuration values."""
    return {
        "theme": "dark",
        "font_family": "Inter, system-ui, sans-serif",
        "brand_color": "#56B3F1",
        "text_color": "#EDEDED",
        "bg_color": "#0B0B0E",
        "heading_size": 64,
        "body_size": 40,
        "margin_px": 96,
        "watermark": True,
        "burn_captions": False,
        "fps": 30,
        "crf": 18,
        "preset": "medium",
        "zoom": 1.10,
        "logo": {
            "path": "examples/logo.png",
            "opacity": 0.85,
            "width_px": 220,
            "position": "bottom-right"
        },
        "caption": {
            "max_lines": 2,
            "font_size": 40,
            "stroke_px": 3,
            "safe_bottom_pct": 12
        },
        "kenburns": {
            "zoom_start": 1.05,
            "zoom_end": 1.12,
            "pan": "auto",
            "easing": "easeInOutSine"
        },
        "audio": {
            "target_lufs": -14.0,
            "music_db": -28,
            "ducking": {
                "threshold": 0.02,
                "ratio": 8.0,
                "attack_ms": 5.0,
                "release_ms": 250.0
            }
        },
        "timeline": {
            "method": "weighted",
            "min_slide_sec": 5.0,
            "max_slide_sec": 60.0,
            "gap_sec": 0.25
        }
    }


def load_styles_config(styles_path: Path) -> Dict[str, Any]:
    """Load styles configuration from YAML file."""
    if not styles_path.exists():
        return {}
    
    try:
        with open(styles_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid styles YAML: {e}")
    except Exception as e:
        raise ConfigError(f"Failed to load styles: {e}")


def load_project_config(project_dir: Path) -> Dict[str, Any]:
    """Load project-specific configuration."""
    config_path = project_dir / "config.yml"
    
    if not config_path.exists():
        return {}
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid project config YAML: {e}")
    except Exception as e:
        raise ConfigError(f"Failed to load project config: {e}")


def merge_configs(*configs: Dict[str, Any]) -> Dict[str, Any]:
    """Merge multiple configuration dictionaries with proper precedence."""
    result = {}
    
    for config in configs:
        if not config:
            continue
            
        for key, value in config.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                # Recursively merge nested dictionaries
                result[key] = merge_configs(result[key], value)
            else:
                # Overwrite with new value
                result[key] = value
    
    return result


def load_merged_config(styles_path: Path, project_dir: Path, 
                      cli_overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Load configuration with proper precedence:
    defaults < styles.yml < project config < CLI flags
    """
    # Load all configuration layers
    default_config = load_default_config()
    styles_config = load_styles_config(styles_path)
    project_config = load_project_config(project_dir)
    cli_config = cli_overrides or {}
    
    # Merge with proper precedence
    merged = merge_configs(default_config, styles_config, project_config, cli_config)
    
    return merged


def validate_config(config: Dict[str, Any]) -> None:
    """Validate configuration values."""
    # Validate theme
    if "theme" in config and config["theme"] not in ["dark", "light"]:
        raise ConfigError(f"Invalid theme: {config['theme']}. Must be 'dark' or 'light'.")
    
    # Validate FPS
    if "fps" in config:
        fps = config["fps"]
        if not isinstance(fps, int) or fps < 1 or fps > 120:
            raise ConfigError(f"Invalid FPS: {fps}. Must be integer between 1-120.")
    
    # Validate CRF
    if "crf" in config:
        crf = config["crf"]
        if not isinstance(crf, int) or crf < 0 or crf > 51:
            raise ConfigError(f"Invalid CRF: {crf}. Must be integer between 0-51.")
    
    # Validate zoom
    if "zoom" in config:
        zoom = config["zoom"]
        if not isinstance(zoom, (int, float)) or zoom < 1.0 or zoom > 3.0:
            raise ConfigError(f"Invalid zoom: {zoom}. Must be number between 1.0-3.0.")
    
    # Validate audio settings
    if "audio" in config:
        audio = config["audio"]
        if "target_lufs" in audio:
            lufs = audio["target_lufs"]
            if not isinstance(lufs, (int, float)) or lufs > 0 or lufs < -60:
                raise ConfigError(f"Invalid target LUFS: {lufs}. Must be negative number > -60.")
        
        if "ducking" in audio:
            ducking = audio["ducking"]
            if "threshold" in ducking:
                threshold = ducking["threshold"]
                if not isinstance(threshold, (int, float)) or threshold < 0 or threshold > 1:
                    raise ConfigError(f"Invalid threshold: {threshold}. Must be 0-1.")
            
            if "ratio" in ducking:
                ratio = ducking["ratio"]
                if not isinstance(ratio, (int, float)) or ratio < 1:
                    raise ConfigError(f"Invalid ratio: {ratio}. Must be >= 1.")


def get_config_value(config: Dict[str, Any], key_path: str, default: Any = None) -> Any:
    """Get configuration value using dot notation (e.g., 'audio.ducking.threshold')."""
    keys = key_path.split('.')
    value = config
    
    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return default
    
    return value


def set_config_value(config: Dict[str, Any], key_path: str, value: Any) -> None:
    """Set configuration value using dot notation."""
    keys = key_path.split('.')
    current = config
    
    for key in keys[:-1]:
        if key not in current:
            current[key] = {}
        current = current[key]
    
    current[keys[-1]] = value
