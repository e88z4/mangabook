"""Configuration management for MangaBook.

This module handles loading, saving, and managing user configuration settings.
The configuration is stored in ~/.mangabook/config.json.
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

# Set up logging
logger = logging.getLogger(__name__)

# Default configuration values
DEFAULT_CONFIG = {
    "output_directory": str(Path.cwd() / "downloaded_volume"),
    "keep_raw_files": False,
    "image_quality": 85,
    "default_language": "en",
}

# Constants
CONFIG_DIR = Path.home() / ".mangabook"
CONFIG_FILE = CONFIG_DIR / "config.json"


def ensure_config_dir() -> None:
    """Create the configuration directory if it doesn't exist.
    
    Sets appropriate permissions (700) for security.
    
    Raises:
        OSError: If directory creation fails or permissions can't be set.
    """
    try:
        CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        logger.debug(f"Config directory ensured at {CONFIG_DIR}")
    except OSError as e:
        logger.error(f"Failed to create config directory: {e}")
        raise


def load_config() -> Dict[str, Any]:
    """Load configuration from file or return default config.
    
    Returns:
        Dict[str, Any]: The loaded configuration or default values.
    """
    ensure_config_dir()
    
    if not CONFIG_FILE.exists():
        logger.info("Config file doesn't exist. Creating with defaults.")
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
    
    try:
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)
        
        # Update with any missing default values
        updated = False
        for key, value in DEFAULT_CONFIG.items():
            if key not in config:
                config[key] = value
                updated = True
        
        if updated:
            save_config(config)
        
        logger.debug("Config loaded successfully")
        return config
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Error loading config file: {e}")
        logger.info("Using default configuration")
        return DEFAULT_CONFIG.copy()


def save_config(config: Dict[str, Any]) -> bool:
    """Save configuration to file.
    
    Args:
        config: The configuration dictionary to save.
        
    Returns:
        bool: True if saving was successful, False otherwise.
    """
    ensure_config_dir()
    
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
        os.chmod(CONFIG_FILE, 0o600)  # Secure file permissions
        logger.debug("Config saved successfully")
        return True
    except OSError as e:
        logger.error(f"Error saving config file: {e}")
        return False


def get_config_value(key: str, default: Any = None) -> Any:
    """Get a configuration value.
    
    Args:
        key: The configuration key to retrieve.
        default: Default value if key doesn't exist.
        
    Returns:
        The value for the specified key or default if not found.
    """
    config = load_config()
    return config.get(key, default)


def set_config_value(key: str, value: Any) -> bool:
    """Set a configuration value.
    
    Args:
        key: The configuration key to set.
        value: The value to store.
        
    Returns:
        bool: True if setting was successful, False otherwise.
    """
    config = load_config()
    config[key] = value
    return save_config(config)


class Config:
    """Configuration manager class for MangaBook."""
    
    def __init__(self):
        """Initialize the configuration manager."""
        self._config = load_config()
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value.
        
        Args:
            key: The configuration key to retrieve.
            default: Default value if key doesn't exist.
            
        Returns:
            The value for the specified key or default if not found.
        """
        return self._config.get(key, default)
    
    def set(self, key: str, value: Any) -> bool:
        """Set a configuration value.
        
        Args:
            key: The configuration key to set.
            value: The value to store.
            
        Returns:
            bool: True if setting was successful, False otherwise.
        """
        self._config[key] = value
        return self.save()
    
    def update(self, updates: Dict[str, Any]) -> bool:
        """Update multiple configuration values at once.
        
        Args:
            updates: Dictionary of key-value pairs to update.
            
        Returns:
            bool: True if update was successful, False otherwise.
        """
        self._config.update(updates)
        return self.save()
    
    def save(self) -> bool:
        """Save the current configuration to disk.
        
        Returns:
            bool: True if saving was successful, False otherwise.
        """
        return save_config(self._config)
    
    def reset(self) -> bool:
        """Reset configuration to default values.
        
        Returns:
            bool: True if reset was successful, False otherwise.
        """
        self._config = DEFAULT_CONFIG.copy()
        return self.save()
    
    def get_output_dir(self) -> str:
        """Get the output directory for manga downloads.
        
        Returns:
            str: The configured output directory.
        """
        output_dir = self.get("output_directory")
        os.makedirs(output_dir, exist_ok=True)
        return output_dir
    
    def get_config_dir(self) -> str:
        """Return the path to the configuration directory."""
        return str(CONFIG_DIR)
