"""Utility functions for MangaBook.

This module contains common utility functions used throughout the application.
"""

import os
import re
import time
import logging
import functools
import html
from pathlib import Path
from typing import List, Dict, Any, Callable, Optional, TypeVar, Union

# Set up logging
logger = logging.getLogger(__name__)

# Type variable for generics
T = TypeVar('T')

# Regular expression for invalid filename characters
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Language code mapping for better display
LANGUAGE_CODES = {
    "ja": "Japanese",
    "en": "English",
    "ko": "Korean",
    "zh": "Chinese",
    "zh-hk": "Chinese (HK)",
    "zh-cn": "Chinese (Simplified)",
    "zh-tw": "Chinese (Traditional)",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "es-la": "Spanish (Latin America)",
    "it": "Italian",
    "pt": "Portuguese",
    "pt-br": "Portuguese (Brazil)",
    "ru": "Russian",
    "ar": "Arabic",
    "th": "Thai",
    "id": "Indonesian",
    "vi": "Vietnamese",
    "pl": "Polish",
    "tr": "Turkish",
    "ms": "Malay",
}

# Status mapping for better display
MANGA_STATUS = {
    "ongoing": "Ongoing",
    "completed": "Completed",
    "hiatus": "On Hiatus",
    "cancelled": "Cancelled",
    "published": "Published",
    # Add fallbacks for renamed or new status values
    "on_hiatus": "On Hiatus",
    "discontinued": "Cancelled",
    "finished": "Completed"
}

# Content rating mapping
CONTENT_RATING = {
    "safe": "Safe",
    "suggestive": "Suggestive",
    "erotica": "Erotica",
    "pornographic": "Adult",
    # Fallbacks
    "nsfw": "Adult"
}


def get_readable_language(lang_code: Optional[str]) -> str:
    """Convert language code to readable language name.
    
    Args:
        lang_code: The language code to convert.
        
    Returns:
        A human-readable language name.
    """
    if not lang_code:
        return "Unknown"
    
    return LANGUAGE_CODES.get(lang_code.lower(), lang_code)


def get_readable_status(status: Optional[str]) -> str:
    """Convert status code to readable status.
    
    Args:
        status: The status code to convert.
        
    Returns:
        A human-readable status.
    """
    if not status:
        return "Unknown"
    
    return MANGA_STATUS.get(status.lower(), status.capitalize())


def get_readable_content_rating(rating: Optional[str]) -> str:
    """Convert content rating code to readable rating.
    
    Args:
        rating: The content rating code to convert.
        
    Returns:
        A human-readable content rating.
    """
    if not rating:
        return "Unknown"
    
    return CONTENT_RATING.get(rating.lower(), rating.capitalize())


def sanitize_filename(filename: str) -> str:
    """Remove invalid characters from a filename.
    
    Args:
        filename: The filename to sanitize.
        
    Returns:
        A sanitized filename safe for file system operations.
    """
    # Replace invalid characters with underscores
    sanitized = INVALID_FILENAME_CHARS.sub('_', filename)
    # Trim leading/trailing whitespace and periods (problematic on some file systems)
    sanitized = sanitized.strip('. ')
    # Ensure we have something left
    if not sanitized:
        return "unnamed"
    return sanitized


def ensure_directory(directory_path: Union[str, Path]) -> Path:
    """Create directory if it doesn't exist.
    
    Args:
        directory_path: Path to the directory to create.
        
    Returns:
        Path: The Path object for the created directory.
        
    Raises:
        OSError: If directory creation fails.
    """
    path = Path(directory_path)
    try:
        path.mkdir(parents=True, exist_ok=True)
        return path
    except OSError as e:
        logger.error(f"Failed to create directory {path}: {e}")
        raise


def generate_manga_path(base_dir: Union[str, Path], manga_title: str) -> Path:
    """Generate a standardized path for a manga.
    
    Args:
        base_dir: Base directory for all manga.
        manga_title: Title of the manga.
        
    Returns:
        Path: The standardized path for the manga.
    """
    safe_title = sanitize_filename(manga_title)
    manga_path = Path(base_dir) / safe_title
    return ensure_directory(manga_path)


def generate_volume_path(manga_path: Union[str, Path], volume_number: Union[str, int]) -> Path:
    """Generate a standardized path for a manga volume.
    
    Args:
        manga_path: Path to the manga directory.
        volume_number: Volume number.
        
    Returns:
        Path: The standardized path for the volume.
    """
    vol_dir = f"volume_{volume_number}"
    volume_path = Path(manga_path) / vol_dir
    return ensure_directory(volume_path)


def format_manga_title(title: str) -> str:
    """Format a manga title for display.
    
    Args:
        title: The raw manga title.
        
    Returns:
        A formatted title suitable for display.
    """
    if not title:
        return "Unknown"
    
    # Remove excess whitespace and line breaks
    formatted = re.sub(r'\s+', ' ', title.strip())
    return formatted


def format_volume_number(volume_num: Union[str, int, float, None]) -> str:
    """Format a volume number for display and file naming.
    
    Args:
        volume_num: The volume number.
        
    Returns:
        A formatted volume number.
    """
    if volume_num is None:
        return "Unknown"
    
    try:
        # Convert to float first to handle both int and decimal strings
        num = float(volume_num)
        # Check if it's a whole number
        if num.is_integer():
            return str(int(num))
        return str(num)
    except (ValueError, TypeError):
        # Handle non-numeric volume identifiers
        return str(volume_num)


def create_table(headers: List[str], rows: List[List[str]], width: int = 80) -> str:
    """Create a text-based table for console display.
    
    Args:
        headers: List of column headers.
        rows: List of rows, where each row is a list of strings.
        width: Maximum width of the table.
        
    Returns:
        A formatted table as a string.
    """
    if not rows:
        return "No data to display."
    
    # Calculate column widths
    num_cols = len(headers)
    col_widths = [len(h) for h in headers]
    
    for row in rows:
        for i, cell in enumerate(row[:num_cols]):
            col_widths[i] = max(col_widths[i], min(len(str(cell)), width // num_cols))
    
    # Create the table
    result = []
    
    # Add header
    header_row = " | ".join(h.ljust(w) for h, w in zip(headers, col_widths))
    result.append(header_row)
    
    # Add separator
    separator = "-+-".join("-" * w for w in col_widths)
    result.append(separator)
    
    # Add data rows
    for row in rows:
        # Ensure row has enough columns
        padded_row = row + [""] * (num_cols - len(row))
        data_row = " | ".join(str(c).ljust(w) for c, w in zip(padded_row[:num_cols], col_widths))
        result.append(data_row)
    
    return "\n".join(result)


def truncate_string(text: str, max_length: int = 80, suffix: str = "...") -> str:
    """Truncate a string to a maximum length.
    
    Args:
        text: The text to truncate.
        max_length: Maximum length of the string.
        suffix: String to append to indicate truncation.
        
    Returns:
        The truncated string.
    """
    if not text:
        return ""
    
    if len(text) <= max_length:
        return text
    
    return text[:max_length - len(suffix)] + suffix


def clean_html(html_text: str) -> str:
    """Remove HTML tags from text and decode entities.
    
    Args:
        html_text: Text containing HTML.
        
    Returns:
        Clean text without HTML tags.
    """
    if not html_text:
        return ""
    
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', ' ', html_text)
    # Decode HTML entities
    text = html.unescape(text)
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text


def retry(max_attempts: int = 3, delay: float = 1.0, backoff: float = 2.0, 
          exceptions: tuple = (Exception,)) -> Callable:
    """Retry decorator with exponential backoff.
    
    Args:
        max_attempts: Maximum number of attempts.
        delay: Initial delay between attempts in seconds.
        backoff: Backoff multiplier.
        exceptions: Exceptions to catch and retry.
        
    Returns:
        Decorator function.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            attempt = 1
            current_delay = delay
            
            while attempt <= max_attempts:
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_attempts:
                        logger.error(f"Failed after {max_attempts} attempts: {e}")
                        raise
                    
                    logger.warning(f"Attempt {attempt} failed: {e}. "
                                   f"Retrying in {current_delay:.2f}s...")
                    time.sleep(current_delay)
                    current_delay *= backoff
                    attempt += 1
        
        return wrapper
    
    return decorator


def exception_handler(func: Callable) -> Callable:
    """Decorator to handle and log exceptions.
    
    Args:
        func: The function to decorate.
        
    Returns:
        Decorated function.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.exception(f"Error in {func.__name__}: {e}")
            raise
    
    return wrapper
