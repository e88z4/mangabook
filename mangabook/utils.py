"""Utility functions for MangaBook.

This module contains common utility functions used throughout the application.
"""

import os
import re
import time
import logging
import functools
import html
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Callable, Optional, TypeVar, Union

# Set up logging
logger = logging.getLogger(__name__)

# Type variable for generics
T = TypeVar('T')

# Regular expression for POSIX-incompatible characters
# POSIX doesn't allow '/' (path separator) and '\0' (null character) in filenames
POSIX_INVALID_CHARS = re.compile(r'[/\x00]')

# Pattern for characters that may cause issues in some shells or tools
# This includes control characters, spaces and special shell characters
PROBLEMATIC_CHARS = re.compile(r'[<>:"|?*\\\x00-\x1f\s]')


def sanitize_filename(filename: str, posix_only: bool = False) -> str:
    """Remove invalid characters from a filename for filesystem compatibility.
    
    This function makes filenames compatible with filesystem requirements.
    With posix_only=True, it only removes characters disallowed by POSIX (/ and null).
    Otherwise, it also replaces potentially problematic characters for cross-platform use.
    
    Args:
        filename: The filename to sanitize.
        posix_only: If True, only strip characters not allowed in POSIX (/ and null).
                   If False, also replace other problematic characters (default).
        
    Returns:
        A sanitized filename safe for file system operations.
    """
    if not filename:
        return "unnamed"
    
    # Choose which pattern to use based on the posix_only flag
    pattern = POSIX_INVALID_CHARS if posix_only else PROBLEMATIC_CHARS
    
    # Replace invalid characters with underscores
    sanitized = pattern.sub('_', filename)
    
    # Trim leading/trailing whitespace and periods
    # (leading dots make files hidden in POSIX systems)
    sanitized = sanitized.strip('. ')
    
    # Ensure we don't have just dots or empty string
    if not sanitized or all(c == '.' for c in sanitized):
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
    
    Creates a directory for a manga using a sanitized version of the manga title.
    
    Args:
        base_dir: Base directory for all manga.
        manga_title: Title of the manga.
        
    Returns:
        Path: The standardized path for the manga.
    """
    safe_title = sanitize_filename(manga_title)
    manga_path = Path(base_dir) / safe_title
    return ensure_directory(manga_path)


def generate_volume_path(manga_path: Union[str, Path], volume_number: Union[str, int, float]) -> Path:
    """Generate a standardized path for a manga volume with zero-padding.
    
    Creates a directory for a manga volume with a consistent 3-digit zero-padded format.
    Special handling for volume "0" which indicates ungrouped chapters.
    
    Args:
        manga_path: Path to the manga directory.
        volume_number: Volume number. "0" indicates ungrouped chapters.
        
    Returns:
        Path: The standardized path for the volume.
    """
    # Special handling for ungrouped chapters (volume "0")
    if volume_number == "0" or volume_number == 0:
        vol_dir = "ungrouped_chapters"
        volume_path = Path(manga_path) / vol_dir
        return ensure_directory(volume_path)
    
    # Convert volume number to a clean format (handling floats, etc.)
    vol_num = format_volume_number(volume_number)
    
    # Try to convert to float for padding, fall back to string if not possible
    try:
        vol_num_float = float(vol_num)
        # Check if it's an integer value
        if vol_num_float.is_integer():
            # Format with 3-digit padding for whole numbers
            vol_num_fmt = f"{int(vol_num_float):03d}"
        else:
            # For decimal volumes, keep the decimal part but pad the integer part
            int_part = int(vol_num_float)
            decimal_part = vol_num_float - int_part
            vol_num_fmt = f"{int_part:03d}{vol_num[vol_num.find('.'):]}"
    except ValueError:
        # If not numeric, just use as is
        vol_num_fmt = vol_num
    
    vol_dir = f"volume_{vol_num_fmt}"
    volume_path = Path(manga_path) / vol_dir
    return ensure_directory(volume_path)


def generate_chapter_path(volume_path: Union[str, Path], 
                        chapter_number: Union[str, int, float], 
                        chapter_title: Optional[str] = None) -> Path:
    """Generate a standardized path for a manga chapter with zero-padding.
    
    Creates a directory for a manga chapter with a consistent 4-digit zero-padded format.
    
    Args:
        volume_path: Path to the volume directory.
        chapter_number: Chapter number.
        chapter_title: Optional title of the chapter.
        
    Returns:
        Path: The standardized path for the chapter.
    """
    # Clean the chapter number format
    chap_num = format_volume_number(chapter_number)  # Reuse volume formatter for chapters
    
    # Try to convert to float for padding, fall back to string if not possible
    try:
        chap_num_float = float(chap_num)
        # Check if it's an integer value
        if chap_num_float.is_integer():
            # Format with 4-digit padding for whole numbers
            chap_num_fmt = f"{int(chap_num_float):04d}"
        else:
            # For decimal chapters, keep the decimal part but pad the integer part
            int_part = int(chap_num_float)
            decimal_part = chap_num_float - int_part
            chap_num_fmt = f"{int_part:04d}{chap_num[chap_num.find('.'):]}"
    except ValueError:
        # If not numeric, just use as is
        chap_num_fmt = chap_num
    
    # Create directory name with optional title
    if chapter_title:
        safe_title = sanitize_filename(chapter_title)
        chapter_dir = f"chapter_{chap_num_fmt}_{safe_title}"
    else:
        chapter_dir = f"chapter_{chap_num_fmt}"
    
    chapter_path = Path(volume_path) / chapter_dir
    return ensure_directory(chapter_path)


def generate_page_path(chapter_path: Union[str, Path], 
                     page_number: Union[str, int], 
                     extension: str = "jpg") -> Path:
    """Generate a standardized path for a manga page with zero-padding.
    
    Creates a file path for a manga page with a consistent 3-digit zero-padded format.
    
    Args:
        chapter_path: Path to the chapter directory.
        page_number: Page number.
        extension: File extension (default: jpg).
        
    Returns:
        Path: The standardized path for the page.
    """
    # Ensure the extension doesn't have a leading dot
    clean_ext = extension.lstrip('.')
    
    # Handle page number as integer with 3-digit zero-padding
    page_num = int(page_number) if isinstance(page_number, (int, float)) or \
               (isinstance(page_number, str) and page_number.isdigit()) else 0
    
    # Format with 3-digit padding
    page_filename = f"{page_num:03d}.{clean_ext}"
    
    return Path(chapter_path) / page_filename


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


def create_volume_manifest(manga_id: str, manga_title: str, volume_number: Union[str, int, float]) -> Dict[str, Any]:
    """Create an initial manifest structure for a manga volume.
    
    Args:
        manga_id: MangaDex ID for the manga.
        manga_title: Title of the manga.
        volume_number: Volume number.
        
    Returns:
        Dict containing the initial manifest structure.
    """
    current_time = datetime.now().isoformat()
    
    return {
        "manga_id": manga_id,
        "manga_title": manga_title,
        "volume_number": volume_number,
        "created_at": current_time,
        "last_updated": current_time,
        "chapters": {},
        "status": "incomplete"
    }


def save_manifest(manifest: Dict[str, Any], volume_path: Union[str, Path]) -> bool:
    """Save a manifest to disk.
    
    Args:
        manifest: The manifest data to save.
        volume_path: Path to the volume directory.
        
    Returns:
        bool: True if successful, False otherwise.
    """
    path = Path(volume_path) / "manifest.json"
    print(f"[DEBUG] save_manifest: Saving manifest to {path}")  # DEBUG
    try:
        # Update the last_updated timestamp
        manifest["last_updated"] = datetime.now().isoformat()
        
        # Write the manifest to file
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        print(f"[DEBUG] save_manifest: Successfully saved manifest to {path}")  # DEBUG
        return True
    except Exception as e:
        print(f"[DEBUG] save_manifest: Failed to save manifest to {path}: {e}")  # DEBUG
        logger.error(f"Failed to save manifest to {path}: {e}")
        return False


def load_manifest(volume_path: Union[str, Path]) -> Optional[Dict[str, Any]]:
    """Load a manifest from disk.
    
    Args:
        volume_path: Path to the volume directory.
        
    Returns:
        Dict containing the manifest data if successful, None otherwise.
    """
    path = Path(volume_path) / "manifest.json"
    try:
        if not path.exists():
            logger.warning(f"Manifest file does not exist: {path}")
            return None
            
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load manifest from {path}: {e}")
        return None


def update_manifest_chapter(manifest: Dict[str, Any], chapter_data: Dict[str, Any]) -> Dict[str, Any]:
    """Add or update a chapter in the manifest.
    
    Args:
        manifest: The manifest to update.
        chapter_data: Data for the chapter to add/update.
        
    Returns:
        The updated manifest.
    """
    chapter_id = chapter_data.get("id")
    if not chapter_id:
        logger.warning("Chapter data missing ID, cannot update manifest")
        return manifest
    
    # Get existing chapter data if it exists
    chapters = manifest.get("chapters", {})
    current_chapter = chapters.get(chapter_id, {})
    
    # Merge the new data with existing data, with new data taking precedence
    updated_chapter = {
        **current_chapter,
        **chapter_data,
        "last_updated": datetime.now().isoformat()
    }
    
    # Ensure status is set
    if "status" not in updated_chapter:
        updated_chapter["status"] = "incomplete"
    
    # Update the manifest
    chapters[chapter_id] = updated_chapter
    manifest["chapters"] = chapters
    manifest["last_updated"] = datetime.now().isoformat()
    
    # Check if all chapters are complete to update volume status
    all_complete = all(
        chapter.get("status") == "complete"
        for chapter in chapters.values()
    )
    
    if all_complete and chapters:
        manifest["status"] = "complete"
    else:
        manifest["status"] = "incomplete"
    
    return manifest


def update_manifest_page(
    manifest: Dict[str, Any], 
    chapter_id: str, 
    page_data: Dict[str, Any]
) -> Dict[str, Any]:
    """Add or update a page in a chapter in the manifest.
    
    Args:
        manifest: The manifest to update.
        chapter_id: ID of the chapter containing the page.
        page_data: Data for the page to add/update.
        
    Returns:
        The updated manifest.
    """
    chapters = manifest.get("chapters", {})
    chapter = chapters.get(chapter_id, {})
    
    # Initialize pages dict if it doesn't exist
    if "pages" not in chapter:
        chapter["pages"] = {}
    
    page_number = str(page_data.get("page_number", "unknown"))
    
    # Get existing page data if it exists
    current_page = chapter["pages"].get(page_number, {})
    
    # Merge the new data with existing data
    updated_page = {
        **current_page,
        **page_data,
        "last_updated": datetime.now().isoformat()
    }
    
    # Ensure status is set
    if "status" not in updated_page:
        updated_page["status"] = "invalid"
    
    # Update the page in the chapter
    chapter["pages"][page_number] = updated_page
    
    # Update chapter in manifest
    chapters[chapter_id] = chapter
    manifest["chapters"] = chapters
    
    # Update chapter status based on pages
    all_valid = all(
        page.get("status") == "valid"
        for page in chapter["pages"].values()
    )
    
    if all_valid and chapter["pages"]:
        chapter["status"] = "complete"
    else:
        chapter["status"] = "incomplete"
    
    # Update volume status based on chapters
    all_chapters_complete = all(
        chapter.get("status") == "complete"
        for chapter in chapters.values()
    )
    
    if all_chapters_complete and chapters:
        manifest["status"] = "complete"
    else:
        manifest["status"] = "incomplete"
    
    # Update timestamp
    manifest["last_updated"] = datetime.now().isoformat()
    
    return manifest


def is_valid_image(file_path: Union[str, Path]) -> bool:
    """Check if a file is a valid image.
    
    Args:
        file_path: Path to the image file.
        
    Returns:
        bool: True if the file exists, has non-zero size, and is a valid image.
    """
    try:
        from PIL import Image
        
        path = Path(file_path)
        
        # Check if file exists and has size > 0
        if not path.exists() or path.stat().st_size == 0:
            return False
        
        # Try to open as an image
        with Image.open(path) as img:
            img.verify()  # Verify it's a valid image
            
        return True
    except Exception as e:
        logger.debug(f"Image validation failed for {file_path}: {e}")
        return False


def validate_chapter_files(
    chapter_path: Union[str, Path], 
    manifest: Dict[str, Any],
    chapter_id: str
) -> Dict[str, bool]:
    """Validate all image files in a chapter.
    
    Args:
        chapter_path: Path to the chapter directory.
        manifest: The manifest containing expected pages.
        chapter_id: ID of the chapter to validate.
        
    Returns:
        Dict mapping page numbers to validation status.
    """
    results = {}
    
    try:
        # Get chapter data from manifest
        chapter_data = manifest.get("chapters", {}).get(chapter_id, {})
        pages_data = chapter_data.get("pages", {})
        
        # Get all image files in the directory
        path = Path(chapter_path)
        image_files = [f for f in path.glob("*.jpg") or path.glob("*.png") or path.glob("*.jpeg")]
        
        # Validate each expected page
        for page_num, page_data in pages_data.items():
            file_path = page_data.get("file_path")
            if file_path:
                valid = is_valid_image(file_path)
                results[page_num] = valid
                
                # Update manifest with validation result
                page_data["status"] = "valid" if valid else "invalid"
                manifest = update_manifest_page(manifest, chapter_id, page_data)
            else:
                results[page_num] = False
        
        return results
    except Exception as e:
        logger.error(f"Error validating chapter files: {e}")
        return results
