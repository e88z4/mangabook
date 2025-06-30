"""Command Line Interface for MangaBook.

This module provides the CLI functionality for the MangaBook application,
including manga search, selection, and display features.
"""

import asyncio
import logging
import re
import os
import sys
from typing import List, Dict, Any, Optional, Tuple, Union, Set
import click
from tqdm import tqdm
from pathlib import Path
from datetime import datetime

from .api import get_api, MangaDexAPI
from .utils import (
    create_table, 
    truncate_string, 
    clean_html, 
    format_manga_title,
    format_volume_number,
    ensure_directory
)
from .config import Config
from .error import initialize_error_handler, error_handler, ErrorCategory
from .workflow import process_manga, check_environment, check_disk_space, validate_epub

# Set up logging
logger = logging.getLogger(__name__)

# Regular expressions for parsing volume selections
VOLUME_RANGE_PATTERN = re.compile(r'^(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)$')
VOLUME_LIST_PATTERN = re.compile(r'^(\d+(?:\.\d+)?)(?:,(\d+(?:\.\d+)?))*$')


async def search_manga(query: str, language: Optional[str] = None, limit: int = 10, offset: int = 0) -> List[Dict[str, Any]]:
    """Search for manga by title.
    
    Args:
        query: The search query.
        language: Optional language filter for content (not for search).
        limit: Maximum number of results.
        offset: Number of results to skip (for pagination).
        
    Returns:
        List of manga search results.
    """
    logger.info(f"Searching for manga: {query} (offset: {offset}, limit: {limit})")
    
    api = await get_api()
    try:
        # Search without restricting by language to get all potential matches
        response = await api.search_manga(query, limit=limit, offset=offset, language=None)
        
        results = []
        for manga in response.get("data", []):
            manga_id = manga["id"]
            attributes = manga["attributes"]
            
            # Get all available titles in all languages
            titles = {}
            if attributes.get("title"):
                titles = attributes["title"]
            
            # Get alternative titles in all languages
            if attributes.get("altTitles"):
                for alt_title_dict in attributes["altTitles"]:
                    for lang, alt_title in alt_title_dict.items():
                        if lang not in titles:
                            titles[lang] = alt_title
            
            # Determine the best title to display
            # Priority: requested language > English > Japanese > first available
            title = None
            if language and language in titles:
                title = titles[language]
            elif "en" in titles:
                title = titles["en"]
            elif "ja" in titles:
                title = titles["ja"]
            else:
                # Just take the first available title
                title = next(iter(titles.values()), "Unknown")
            
            # Get cover art if available
            cover_url = ""
            for relationship in manga.get("relationships", []):
                if relationship["type"] == "cover_art" and "attributes" in relationship:
                    filename = relationship["attributes"].get("fileName")
                    if filename:
                        cover_url = f"https://uploads.mangadex.org/covers/{manga_id}/{filename}"
            
            # Available languages for this manga
            available_languages = set()
            if attributes.get("availableTranslatedLanguages"):
                available_languages = set(attributes.get("availableTranslatedLanguages", []))
            
            manga_data = {
                "id": manga_id,
                "title": format_manga_title(title) if title else "Unknown",
                "original_language": attributes.get("originalLanguage", "unknown"),
                "year": attributes.get("year"),
                "status": attributes.get("status", "unknown"),
                "description": clean_html(attributes.get("description", {}).get(language or "en", "")),
                "cover_url": cover_url,
                "all_titles": titles,
                "available_languages": available_languages
            }
            results.append(manga_data)
        
        return results
    finally:
        await api.close()


def display_manga_search_results(results: List[Dict[str, Any]], page: int = 1, limit: int = 10) -> None:
    """Display manga search results in a table format.
    
    Args:
        results: List of manga search results.
        page: Current page number.
        limit: Number of results per page.
    """
    if not results:
        click.secho("No results found.", fg="yellow")
        return
    
    # Prepare table data
    headers = ["#", "Title", "Original Language", "Available Languages", "Status", "Year", "ID"]
    rows = []
    
    for i, manga in enumerate(results):
        # Format available languages list
        available_langs = manga.get("available_languages", set())
        langs_str = ", ".join(sorted(available_langs)) if available_langs else "None"
        
        # Calculate item number based on page and limit
        item_num = ((page - 1) * limit) + i + 1
        
        rows.append([
            str(item_num),
            truncate_string(manga.get("title", "Unknown"), 50),
            manga.get("original_language", "unknown"),
            truncate_string(langs_str, 20),
            manga.get("status", "unknown"),
            str(manga.get("year", "N/A")),
            manga.get("id", "N/A"),
        ])
    
    # Create and display table
    table = create_table(headers, rows)
    click.echo(f"\nSearch Results (Page {page}):\n")
    click.echo(table)


def select_from_list(items: List[Any], prompt: str = "Enter number") -> Optional[int]:
    """Prompt user to select an item from a list.
    
    Args:
        items: List of items.
        prompt: Prompt message.
        
    Returns:
        Selected index or None if cancelled.
    """
    while True:
        try:
            selection = click.prompt(prompt, type=str, default="", show_default=False)
            
            if not selection:
                return None
            
            index = int(selection) - 1
            if 0 <= index < len(items):
                return index
            else:
                click.secho(f"Please enter a number between 1 and {len(items)}", fg="yellow")
        except ValueError:
            click.secho("Please enter a valid number", fg="yellow")


async def get_manga_details(manga_id: str) -> Dict[str, Any]:
    """Get detailed information about a manga.
    
    Args:
        manga_id: MangaDex ID of the manga.
        
    Returns:
        Dict with manga details.
    """
    logger.info(f"Getting manga details: {manga_id}")
    
    api = await get_api()
    try:
        manga = await api.get_manga(manga_id)
        
        if not manga:
            return {}
        
        # Debug: Print the structure of the manga response
        logger.debug(f"Manga response keys: {manga.keys()}")
        if 'data' in manga:
            logger.debug("Using 'data' field in response")
            manga = manga['data']
            if not manga:
                return {}
            logger.debug(f"Manga data keys: {manga.keys()}")
        
        # Check if attributes exists
        if 'attributes' not in manga:
            logger.error(f"'attributes' not found in manga data: {manga}")
            return {
                "id": manga_id,
                "title": "Unknown",
                "error": "Invalid API response structure"
            }
        
        # Extract basic manga data
        attributes = manga["attributes"]
        
        # Get title (prioritize English, then fall back to other languages)
        title = None
        if attributes.get("title"):
            title_dict = attributes["title"]
            if "en" in title_dict:
                title = title_dict["en"]
            else:
                # Just take the first available title
                title = next(iter(title_dict.values()), "Unknown")
        
        # Extract other information
        details = {
            "id": manga_id,
            "title": format_manga_title(title) if title else "Unknown",
            "description": clean_html(attributes.get("description", {}).get("en", "")),
            "status": attributes.get("status", "unknown"),
            "year": attributes.get("year"),
            "tags": [],
            "original_language": attributes.get("originalLanguage", "unknown"),
            "last_chapter": attributes.get("lastChapter"),
            "content_rating": attributes.get("contentRating", "unknown"),
            "authors": [],
            "artists": [],
            "cover_url": "",
        }
        
        # Extract tags
        for tag in attributes.get("tags", []):
            if tag.get("attributes", {}).get("name", {}).get("en"):
                details["tags"].append(tag["attributes"]["name"]["en"])
        
        # Extract cover and other relationships
        for relationship in manga.get("relationships", []):
            if relationship["type"] == "cover_art" and "attributes" in relationship:
                filename = relationship["attributes"].get("fileName")
                if filename:
                    details["cover_url"] = f"https://uploads.mangadex.org/covers/{manga_id}/{filename}"
            elif relationship["type"] == "author" and "attributes" in relationship:
                name = relationship["attributes"].get("name")
                if name:
                    details["authors"].append(name)
            elif relationship["type"] == "artist" and "attributes" in relationship:
                name = relationship["attributes"].get("name")
                if name:
                    details["artists"].append(name)
        
        return details
    finally:
        await api.close()


def display_manga_details(details: Dict[str, Any]) -> None:
    """Display detailed information about a manga.
    
    Args:
        details: Dict with manga details.
    """
    if not details:
        click.secho("No details available.", fg="yellow")
        return
    
    # Title
    click.echo("\n" + "=" * 60)
    click.secho(f"{details['title']}", fg="bright_blue", bold=True)
    click.echo("=" * 60)
    
    # Basic info
    click.secho("Basic Information:", fg="green", bold=True)
    click.echo(f"ID: {details['id']}")
    if details.get("year"):
        click.echo(f"Year: {details['year']}")
    click.echo(f"Status: {details['status'].title()}")
    click.echo(f"Language: {details['original_language']}")
    click.echo(f"Content Rating: {details['content_rating'].title()}")
    
    # Authors and artists
    if details.get("authors"):
        click.echo(f"Author(s): {', '.join(details['authors'])}")
    if details.get("artists"):
        click.echo(f"Artist(s): {', '.join(details['artists'])}")
    
    # Tags
    if details.get("tags"):
        click.echo(f"Tags: {', '.join(details['tags'])}")
    
    # Description
    if details.get("description"):
        click.echo("\n" + "-" * 60)
        click.secho("Description:", fg="green", bold=True)
        click.echo(details["description"])
        click.echo("-" * 60)


async def get_volumes(manga_id: str, language: str = "en") -> Dict[str, Dict[str, Any]]:
    """Get volumes and chapters for a manga.
    
    Args:
        manga_id: MangaDex ID of the manga.
        language: The language code.
        
    Returns:
        Dict mapping volume numbers to chapter information.
    """
    logger.info(f"Getting volumes for manga: {manga_id}")
    
    api = await get_api()
    try:
        # Use get_all_chapters instead of get_chapters to handle pagination
        chapter_list = await api.get_all_chapters(manga_id, language=language)
        
        volumes = {}
        
        # Create a special entry for ungrouped chapters (not in any volume)
        volumes["0"] = {
            "chapters": [],
            "count": 0,
            "scanlation_groups": set(),
            "display_name": "Ungrouped Chapters"
        }
        
        for chapter in chapter_list:
            attributes = chapter.get("attributes", {})
            volume = attributes.get("volume") or "0"  # Use "0" for chapters without a volume
            chapter_num = attributes.get("chapter") or "Unknown"
            
            # Initialize volume entry if not exists
            if volume not in volumes:
                volumes[volume] = {
                    "chapters": [],
                    "count": 0,
                    "scanlation_groups": set(),
                    "display_name": f"Volume {volume}"
                }
            elif volume == "0":
                # Special handling for ungrouped chapters
                volumes[volume]["display_name"] = "Ungrouped Chapters"
            
            # Extract scanlation group
            for relationship in chapter.get("relationships", []):
                if relationship["type"] == "scanlation_group" and "attributes" in relationship:
                    group_name = relationship["attributes"].get("name", "Unknown Group")
                    volumes[volume]["scanlation_groups"].add(group_name)
            
            # Add chapter
            volumes[volume]["chapters"].append({
                "id": chapter["id"],
                "number": chapter_num,
                "title": attributes.get("title", ""),
                "pages": attributes.get("pages", 0),
                "volume": volume
            })
            volumes[volume]["count"] += 1
        
        # Remove empty ungrouped chapters entry if not used
        if volumes["0"]["count"] == 0:
            volumes.pop("0")
        
        # Sort chapters within each volume numerically
        for volume_data in volumes.values():
            volume_data["chapters"].sort(
                key=lambda c: float(c["number"]) if c["number"].replace(".", "").isdigit() else float("inf")
            )
            
        return volumes
    finally:
        await api.close()


def display_volumes(volumes: Dict[str, Dict[str, Any]]) -> None:
    """Display volume information for a manga.
    
    Args:
        volumes: Dict with volume information.
    """
    if not volumes:
        click.secho("No volumes available.", fg="yellow")
        return
    
    click.echo("\nAvailable Volumes:")
    
    # Custom sort key function for proper numeric sorting of volumes
    def volume_sort_key(volume_item):
        vol = volume_item[0]
        # Handle special case for ungrouped chapters
        if vol == "0":
            return float('inf')  # Place at the end
        
        # Try to convert to float for numeric sorting, fall back to string if not possible
        try:
            return float(vol)
        except ValueError:
            return vol
    
    # Sort volumes numerically
    sorted_volumes = sorted(volumes.items(), key=volume_sort_key)
    
    # Debug output for volume sorting validation
    logger.debug(f"Sorted volumes: {[v[0] for v in sorted_volumes]}")
    
    # Debug output for volume sorting validation
    logger.debug(f"Sorted volumes: {[v[0] for v in sorted_volumes]}")
    
    for volume, data in sorted_volumes:
        if volume == "0":
            volume_text = "Ungrouped Chapters"
        elif volume == "null" or volume == "None":
            volume_text = "Unknown Volume"
        else:
            volume_text = f"Volume {volume}"
        
        click.secho(f"\n{volume_text}", fg="bright_blue", bold=True)
        click.echo(f"Chapters: {data['count']}")
        
        if data.get("scanlation_groups"):
            groups = ", ".join(sorted(data["scanlation_groups"]))
            click.echo(f"Scanlation Group(s): {groups}")
        
        # List chapters
        for chapter in data["chapters"]:
            if chapter["title"]:
                click.echo(f"  Chapter {chapter['number']}: {chapter['title']}")
            else:
                click.echo(f"  Chapter {chapter['number']}")
                

def parse_volume_selection(input_str: str, available_volumes: List[str]) -> Set[str]:
    """Parse user input for volume selection.
    
    Args:
        input_str: User input string.
        available_volumes: List of available volume numbers.
        
    Returns:
        Set of selected volume numbers.
    """
    selected = set()
    
    if input_str.lower() == "all":
        # Select all volumes
        selected.update(available_volumes)
    else:
        # Split by comma
        for part in input_str.split(","):
            part = part.strip()
            
            # Check for range
            range_match = VOLUME_RANGE_PATTERN.match(part)
            if range_match:
                # Get start and end volume numbers
                start_vol = range_match.group(1)
                end_vol = range_match.group(2)
                
                # Convert to float for numerical comparison
                try:
                    start_num = float(start_vol)
                    end_num = float(end_vol)
                    
                    # Get all volumes in range
                    for vol in available_volumes:
                        try:
                            vol_num = float(vol)
                            if start_num <= vol_num <= end_num:
                                selected.add(vol)
                        except ValueError:
                            pass  # Skip non-numeric volumes
                except ValueError:
                    # Invalid range format
                    click.echo(f"Invalid volume range: {part}")
            else:
                # Check if it's a single volume
                if part in available_volumes:
                    selected.add(part)
                else:
                    try:
                        # Handle case where "2" is input but "2.0" is in available_volumes
                        vol_num = float(part)
                        matching_vol = next((v for v in available_volumes if float(v) == vol_num), None)
                        if matching_vol:
                            selected.add(matching_vol)
                        else:
                            click.echo(f"Volume not found: {part}")
                    except ValueError:
                        click.echo(f"Invalid volume: {part}")
    
    return selected


def volume_selection_prompt(volumes: Dict[str, Dict[str, Any]]) -> Set[str]:
    """Prompt user to select volumes.
    
    Args:
        volumes: Dict with volume information.
        
    Returns:
        Set of selected volume numbers.
    """
    # Get available volume numbers
    available_volumes = []
    has_ungrouped = False
    
    for volume in volumes.keys():
        if volume == "0":
            has_ungrouped = True
        elif volume != "null" and volume != "None" and volume != "Unknown":
            available_volumes.append(volume)
    
    # Sort volumes numerically
    def volume_sort_key(vol):
        try:
            return float(vol)
        except ValueError:
            return float('inf')  # Non-numeric volumes go at the end
            
    available_volumes.sort(key=volume_sort_key)
    
    # Debug output to check volume sorting
    logger.debug(f"Available volumes for selection (sorted): {available_volumes}")
    
    # Debug output to check volume sorting
    logger.debug(f"Available volumes for selection (sorted): {available_volumes}")
    
    # Add ungrouped chapters at the end if they exist
    if has_ungrouped:
        click.secho("\nUngrouped chapters are available!", fg="bright_yellow")
        click.echo("To select ungrouped chapters, include '0' in your selection.")
        available_volumes.append("0")  # Add ungrouped chapters to available options
    
    if not available_volumes:
        click.secho("No volumes available to select.", fg="yellow")
        return set()
    
    # Prompt for volumes
    click.echo("\nEnter volume selection:")
    click.echo("Examples: '1' (single volume), '1,3,5' (multiple volumes), '1-5' (range), 'all'")
    if has_ungrouped:
        click.echo("Include '0' to select ungrouped chapters, e.g. '0,1,2' or 'all'")
    
    while True:
        selection = click.prompt("Volumes", default="all")
        selected = parse_volume_selection(selection, available_volumes)
        
        if selected:
            return selected
        
        click.secho("No valid volumes selected. Please try again.", fg="yellow")


async def login_flow() -> bool:
    """Interactive login flow.
    
    Returns:
        True if login successful, False otherwise.
    """
    from .auth import login, get_auth_status, logout
    
    # Check if already logged in
    status = await get_auth_status()
    if status.get("logged_in", False):
        click.echo(f"Already logged in as: {status.get('username', 'Unknown')}")
        if click.confirm("Log out and login as different user?", default=False):
            await logout()
        else:
            return True
    
    # Get credentials
    username = click.prompt("MangaDex Username")
    password = click.prompt("MangaDex Password", hide_input=True)
    
    # Get OAuth2 credentials if needed
    client_id = None
    client_secret = None
    if click.confirm("Do you want to provide OAuth2 client credentials? (recommended)", default=True):
        client_id = click.prompt("MangaDex OAuth2 Client ID", default="")
        if client_id:
            client_secret = click.prompt("MangaDex OAuth2 Client Secret", hide_input=True)
    
    # Attempt login
    success, message = await login(username, password, client_id, client_secret)
    if success:
        click.secho(f"Logged in as: {username}", fg="green")
        return True
    else:
        click.secho(f"Login failed: {message or 'Unknown error'}", fg="red")
        return False


@click.group()
@click.version_option(version="0.1.0")
@click.option('--debug', is_flag=True, help="Enable debug logging")
@click.option('--log-dir', help="Directory for log files")
@click.pass_context
def cli(ctx, debug, log_dir):
    """MangaBook: Download manga from MangaDex and convert to EPUB.
    
    MangaBook is a command-line tool for downloading manga from MangaDex and 
    creating high-quality EPUB files optimized for Kobo e-readers.
    
    Basic usage:
      - Search for manga: mangabook search "manga title"
      - Get manga info: mangabook info MANGA_ID
      - Download volumes: mangabook download MANGA_ID --volumes "1,3-5"
      - Interactive mode: mangabook interactive
    
    For more information on a specific command, use:
      mangabook COMMAND --help
    """
    # Initialize context object
    ctx.ensure_object(dict)
    
    # Configure logging
    log_level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Store debug flag in context
    ctx.obj['DEBUG'] = debug
    
    # Initialize error handler
    initialize_error_handler(debug=debug, log_dir=log_dir)
    
    # Initialize config
    config = Config()
    ctx.obj['CONFIG'] = config


@cli.command()
@click.argument('query')
@click.option('--language', '-l', help="Language for results (e.g., 'ja' for Japanese, 'en' for English)")
@click.option('--limit', default=20, help="Maximum number of results per page")
@click.pass_context
def search(ctx, query, language, limit):
    """Search for manga by title.
    
    Examples:
      mangabook search "one piece"
      mangabook search "naruto" --language ja
      mangabook search "dragon ball" --limit 30
    """
    asyncio.run(search_command(query, language, limit))


@cli.command()
@click.argument('manga_id')
@click.option('--language', '-l', default='en', help="Language for results")
@click.pass_context
def info(ctx, manga_id, language):
    """Display detailed information about a specific manga.
    
    MANGA_ID is the MangaDex ID of the manga.
    
    Examples:
      mangabook info 32d76d19-8a05-4db0-9fc2-e0b0648fe9d0
    """
    asyncio.run(info_command(manga_id, language))


@cli.command()
@click.argument('manga_id')
@click.option('--volumes', '-v', help="Volumes to download (e.g., '1,3-5,7')")
@click.option('--ungrouped', is_flag=True, help="Download only ungrouped chapters")
@click.option('--updates', is_flag=True, help="Download only ungrouped chapters and overwrite existing files (shortcut for --ungrouped --force-overwrite)")
@click.option('--language', '-l', default='en', help="Language for translation")
@click.option('--output', '-o', help="Output directory")
@click.option('--keep-raw', is_flag=True, help="Keep raw downloaded files")
@click.option('--quality', default=85, help="Image quality (1-100)")
@click.option('--kobo', is_flag=True, default=True, help="Create Kobo-compatible EPUB")
@click.option('--use-enhanced-builder', is_flag=True, default=True, help="Use the enhanced builder for more reliable EPUB generation with strict spec compliance")
@click.option('--use-official-covers', is_flag=True, default=True, help="Use official MangaDex volume covers when available")
@click.option('--create-kobo-collection', is_flag=True, default=True, help="Create a canonical Kobo collection folder for easy device upload")
@click.option('--collection-root', help="Root directory for the manga collection (default: {output-dir}/manga-collection)")
@click.option('--no-validate', is_flag=True, help="Skip EPUB validation")
@click.option('--check-local', is_flag=True, default=True, help="Check for valid local files before downloading")
@click.option('--force-download', is_flag=True, help="Force download even if local files exist")
@click.option('--force-overwrite', is_flag=True, help="Force overwrite existing files (useful for updating ongoing manga)")
@click.pass_context
def download(ctx, manga_id, volumes, ungrouped, updates, language, output, keep_raw, quality, kobo, 
             use_enhanced_builder, use_official_covers, create_kobo_collection, collection_root,
             no_validate, check_local, force_download, force_overwrite):
    """Download manga volumes and convert to EPUB.
    
    MANGA_ID is the MangaDex ID of the manga.
    
    Examples:
      mangabook download 32d76d19-8a05-4db0-9fc2-e0b0648fe9d0 --volumes "1-10"
      mangabook download 32d76d19-8a05-4db0-9fc2-e0b0648fe9d0 --volumes "1,3,5"
      mangabook download 32d76d19-8a05-4db0-9fc2-e0b0648fe9d0 --ungrouped
      mangabook download 32d76d19-8a05-4db0-9fc2-e0b0648fe9d0 --updates
      mangabook download 32d76d19-8a05-4db0-9fc2-e0b0648fe9d0 --volumes "1-3" --check-local
      mangabook download 32d76d19-8a05-4db0-9fc2-e0b0648fe9d0 --volumes "1-3" --collection-root "/path/to/collection"
    """
    config = ctx.obj['CONFIG']
    
    # Use config values if options not provided
    if not output:
        output = config.get_output_dir()
    
    # Handle the updates flag (shortcut for --ungrouped --force-overwrite)
    if updates:
        ungrouped = True
        force_overwrite = True
    
    # If force_download is specified, disable check_local
    if force_download:
        check_local = False
    
    # If ungrouped flag is set, override volumes to download only ungrouped chapters
    if ungrouped:
        volumes = "0"
    
    # Run the download command with proper error handling
    try:
        asyncio.run(download_command(
            manga_id, volumes, language, output, keep_raw, quality, kobo,
            use_enhanced_builder, use_official_covers, create_kobo_collection, 
            collection_root, not no_validate, check_local, force_download,
            force_overwrite
        ))
    except Exception as e:
        # If an exception occurs in the asyncio.run, catch it here
        error_msg = str(e)
        logger.error(f"Error in download command wrapper: {error_msg}")
        click.secho(f"Error: {error_msg}", fg="red")
        sys.exit(1)


@cli.command()
@click.pass_context
def interactive(ctx):
    """Start interactive mode for manga downloading.
    
    This mode guides you through the process of searching, selecting,
    and downloading manga.
    
    Examples:
      mangabook interactive
    """
    asyncio.run(interactive_command())


@cli.command()
@click.option('--username', '-u', help="MangaDex username")
@click.option('--password', '-p', help="MangaDex password", hide_input=True)
@click.option('--client-id', help="MangaDex OAuth2 client ID")
@click.option('--client-secret', help="MangaDex OAuth2 client secret", hide_input=True)
@click.pass_context
def login(ctx, username, password, client_id, client_secret):
    """Log in to MangaDex using OAuth2.
    
    Examples:
      mangabook login -u username -p password
      mangabook login --client-id your_client_id --client-secret your_client_secret
      mangabook login
    """
    asyncio.run(login_command(username, password, client_id, client_secret))


@cli.command()
@click.pass_context
def logout(ctx):
    """Log out from MangaDex.
    
    Examples:
      mangabook logout
    """
    asyncio.run(logout_command())


@cli.command()
@click.option('--path', '-p', help="Output path to check")
@click.option('--full', is_flag=True, help="Show full environment details")
@click.pass_context
def check(ctx, path, full):
    """Check environment for dependencies and issues.
    
    Examples:
      mangabook check
      mangabook check --path /path/to/output
    """
    asyncio.run(check_command(path, full))


@cli.command()
@click.argument('epub_path')
@click.pass_context
def validate(ctx, epub_path):
    """Validate an EPUB file.
    
    EPUB_PATH is the path to the EPUB file to validate.
    
    Examples:
      mangabook validate /path/to/manga.epub
    """
    asyncio.run(validate_command(epub_path))


@cli.command()
@click.argument('output_dir', required=False)
@click.pass_context
def history(ctx, output_dir):
    """Display download history.
    
    OUTPUT_DIR is an optional path to check for downloaded manga.
    
    Examples:
      mangabook history
      mangabook history /path/to/manga
    """
    config = ctx.obj['CONFIG']
    if not output_dir:
        output_dir = config.get_output_dir()
    
    asyncio.run(history_command(output_dir))


@cli.command()
@click.option('--temp-dir', '-t', help="Temporary directory for test files")
@click.option('--fail-fast', '-f', is_flag=True, help="Stop on first test failure")
@click.option('--output', '-o', help="Output file for test results")
@click.pass_context
def test(ctx, temp_dir, fail_fast, output):
    """Run tests to verify MangaBook functionality.
    
    This command runs a series of tests to verify that MangaBook
    is working correctly.
    
    Examples:
      mangabook test
      mangabook test --fail-fast
    """
    from .testing import run_test_command
    asyncio.run(run_test_command(temp_dir, fail_fast, output))


async def search_command(query: str, language: Optional[str], limit: int) -> None:
    """Implementation of the search command."""
    try:
        click.echo(f"Searching for: {query}")
        offset = 0
        page = 1
        
        while True:
            results = await search_manga(query, language, limit, offset)
            display_manga_search_results(results, page, limit)
            
            # Check if there might be more results
            if len(results) >= limit:
                more_results = click.confirm(f"\nThere might be more results. View page {page + 1}?", default=False)
                if more_results:
                    offset += limit
                    page += 1
                    continue
                    
            # No more results or user doesn't want more
            break
            
    except Exception as e:
        error = error_handler.handle(e, category=ErrorCategory.NETWORK)
        error_handler.display_error(error)
        logger.error(f"Error in search command: {e}")


async def info_command(manga_id: str, language: str) -> None:
    """Implementation of the info command."""
    try:
        # Get and display manga details
        details = await get_manga_details(manga_id)
        display_manga_details(details)
        
        # Get and display volumes
        volumes = await get_volumes(manga_id, language)
        display_volumes(volumes)
    except Exception as e:
        error = error_handler.handle(e, category=ErrorCategory.NETWORK)
        error_handler.display_error(error)
        logger.error(f"Error in info command: {e}")


async def download_command(manga_id: str, volumes: Optional[str], language: str,
                         output_dir: str, keep_raw: bool, quality: int, 
                         kobo: bool, use_enhanced_builder: bool = True, use_official_covers: bool = True, 
                         create_kobo_collection: bool = True, collection_root: Optional[str] = None, validate: bool = True, 
                         check_local: bool = True, force_download: bool = False, force_overwrite: bool = False) -> None:
    """Implementation of the download command."""
    # Check disk space
    space_info = check_disk_space(output_dir, required_mb=500)
    if not space_info.get("enough_space", True):
        click.secho(f"⚠️  Low disk space: {space_info.get('free_mb', 0)} MB available", fg="yellow")
        if not click.confirm("Continue anyway?", default=False):
            return
    
    # Get manga details
    try:
        manga_details = await get_manga_details(manga_id)
        manga_title = manga_details.get("title", "Unknown")
        
        click.echo(f"Downloading: {manga_title}")
        
        # Get available volumes
        all_volumes = await get_volumes(manga_id, language)
        
        # Filter out null or unknown volumes
        available_volumes = []
        for volume in all_volumes.keys():
            if volume != "null" and volume != "None" and volume != "Unknown":
                available_volumes.append(volume)
        
        # Sort volumes numerically
        available_volumes.sort(
            key=lambda x: float(x) if x.replace(".", "").isdigit() else float("inf")
        )
        
        if not available_volumes:
            click.secho("No volumes available for download.", fg="yellow")
            return
        
        # Process volume selection
        if volumes:
            selected_volumes = parse_volume_selection(volumes, available_volumes)
        else:
            # Show available volumes
            display_volumes(all_volumes)
            
            # Prompt for volumes
            selected_volumes = volume_selection_prompt(all_volumes)
        
        if not selected_volumes:
            click.secho("No volumes selected.", fg="yellow")
            return
        
        # Sort volumes numerically
        selected_volumes = sorted(
            selected_volumes, 
            key=lambda x: float(x) if x.replace(".", "").isdigit() else float("inf")
        )
        
        click.echo(f"\nSelected volumes: {', '.join(selected_volumes)}")
        
        # Process each volume
        await process_manga(
            manga_id=manga_id, 
            manga_title=manga_title,
            volumes=selected_volumes,
            output_dir=output_dir,
            keep_raw=keep_raw,
            quality=quality,
            kobo=kobo,
            use_enhanced_builder=use_enhanced_builder,
            language=language,
            validate=validate,
            check_local=check_local,
            force_download=force_download,
            force_overwrite=force_overwrite,
            use_official_covers=use_official_covers,
            create_kobo_collection=create_kobo_collection,
            collection_root=collection_root
        )
    except Exception as e:
        # Handle any exceptions that occur during download
        error = error_handler.handle(e, category=ErrorCategory.UNEXPECTED)
        error_handler.display_error(error)
        logger.error(f"Error in download command: {e}")


async def interactive_command() -> None:
    """Implementation of the interactive command."""
    api = None
    try:
        click.echo("=" * 60)
        click.secho("Welcome to MangaBook Interactive Mode!", fg="bright_blue", bold=True)
        click.echo("=" * 60)
        click.echo("This mode will guide you through the process of downloading manga.")
        click.echo("You can exit at any time by pressing Ctrl+C.")
        
        # Load configuration
        config = Config()
        
        # Check if logged in
        api = await get_api()
        
        # Step 1: Check login status
        from .auth import get_auth_status
        status = await get_auth_status()
        
        if status.get("logged_in", False):
            click.echo(f"Currently logged in as: {status.get('username', 'Unknown')}")
        else:
            # Check if user has credentials saved in config
            if not config.get("has_attempted_login", False):
                # Only ask about login if user hasn't been prompted before
                if click.confirm("Do you want to log in to MangaDex?", default=False):
                    success = await login_flow()
                    if not success and not click.confirm("Continue without logging in?", default=True):
                        return
                # Mark that we've attempted login at least once
                config.set("has_attempted_login", True)
        
        # Step 2: Search for manga
        while True:
            query = click.prompt("Enter search term (or leave empty to exit)")
            if not query:
                break
            
            # First ask if user wants to search across all languages
            all_languages = click.confirm("Search across all languages?", default=True)
            language = None if all_languages else click.prompt("Language code", default=config.get("default_language", "en"))
            
            # Perform the search
            results = await search_manga(query, language)
            
            if not results:
                click.secho("No results found.", fg="yellow")
                continue
            
            display_manga_search_results(results)
            
            # Step 3: Select manga
            index = select_from_list(
                items=results,
                prompt="Enter number to select manga (or Enter to search again)"
            )
            
            if index is None:
                continue
                
            manga = results[index]
            manga_id = manga["id"]
            manga_title = manga.get("title", "Unknown")
            
            # Step 3.5: Select language for content
            available_languages = manga.get("available_languages", set())
            
            if not available_languages:
                click.secho("No available languages found for this manga.", fg="yellow")
                language = config.get("default_language", "en")  # Default from config
            else:
                click.echo("\nAvailable languages for this manga:")
                for i, lang in enumerate(sorted(available_languages)):
                    click.echo(f"{i+1}. {lang}")
                
                # Let user select a language
                while True:
                    lang_selection = click.prompt("Enter language code or number", default=config.get("default_language", "en"))
                    
                    # Check if input is a number
                    try:
                        lang_index = int(lang_selection) - 1
                        if 0 <= lang_index < len(available_languages):
                            language = sorted(available_languages)[lang_index]
                            break
                    except ValueError:
                        # Check if input is a language code
                        if lang_selection in available_languages:
                            language = lang_selection
                            break
                    
                    click.secho("Invalid language selection. Please try again.", fg="yellow")
            
            # Step 4: Show manga details
            manga_details = await get_manga_details(manga_id)
            display_manga_details(manga_details)
            
            # Step 5: Show and select volumes
            volumes = await get_volumes(manga_id, language)
            if not volumes:
                click.secho("No volumes found.", fg="yellow")
                continue
            
            display_volumes(volumes)
            selected_volumes = volume_selection_prompt(volumes)
            
            if not selected_volumes:
                click.secho("No volumes selected.", fg="yellow")
                continue
            
            # Step 6: Output options
            output_dir = click.prompt(
                "Output directory",
                default=config.get_output_dir()
            )
            
            # Check disk space
            space_info = check_disk_space(output_dir, required_mb=500)
            if not space_info.get("enough_space", True):
                click.secho(f"⚠️  Low disk space: {space_info.get('free_mb', 0)} MB available", fg="yellow")
                if not click.confirm("Continue anyway?", default=False):
                    continue
            
            # Load download preferences from config
            prefs = config.get_download_preferences()
            
            # Check if preferences should be customized or saved
            if config.get("download_prefs_saved", False):
                # Use saved preferences
                click.echo("\nUsing saved download preferences. To change them, use the 'config' command.")
            else:
                # Ask for preferences and save them
                click.echo("\nPlease set your download preferences:")
                
                prefs["keep_raw"] = click.confirm("Keep raw downloaded files?", default=prefs["keep_raw"])
                prefs["quality"] = click.prompt("Image quality (1-100)", default=prefs["quality"], type=int)
                prefs["kobo"] = click.confirm("Create Kobo-compatible EPUB?", default=prefs["kobo"])
                prefs["validate"] = click.confirm("Validate generated EPUBs?", default=prefs["validate"])
                prefs["use_official_covers"] = click.confirm(
                    "Use official MangaDex volume covers when available?", 
                    default=prefs["use_official_covers"]
                )
                prefs["create_kobo_collection"] = click.confirm(
                    "Create a Kobo collection folder for easy device upload?", 
                    default=prefs["create_kobo_collection"]
                )
                
                # Save preferences if user confirms
                if click.confirm("Save these preferences for future downloads?", default=True):
                    config.save_download_preferences(prefs)
                    config.set("download_prefs_saved", True)
                    click.echo("Preferences saved. You won't be asked for these preferences again.")
            
            # Step 7: Process manga
            await process_manga(
                manga_id=manga_id,
                manga_title=manga_title,
                volumes=list(selected_volumes),
                output_dir=output_dir,
                keep_raw=prefs["keep_raw"],
                quality=prefs["quality"],
                kobo=prefs["kobo"],
                language=language,
                validate=prefs["validate"],
                use_official_covers=prefs["use_official_covers"],
                create_kobo_collection=prefs["create_kobo_collection"],
                use_enhanced_builder=prefs["use_enhanced_builder"],
                check_local=prefs["check_local"],
                force_download=prefs["force_download"]
            )
            
            if not click.confirm("Search for another manga?", default=True):
                break
        click.echo("=" * 60)
        click.secho("Thank you for using MangaBook!", fg="bright_blue", bold=True)
        click.echo("=" * 60)
        
    except Exception as e:
        error = error_handler.handle(e, category=ErrorCategory.UNEXPECTED)
        error_handler.display_error(error)
        logger.error(f"Error in interactive command: {e}")
    finally:
        # Clean up API resources
        if api:
            await api.close()


async def login_command(username: Optional[str] = None, password: Optional[str] = None,
                    client_id: Optional[str] = None, client_secret: Optional[str] = None) -> None:
    """Implementation of the login command."""
    from .auth import login, get_auth_status
    
    try:
        # Check if already logged in
        status = await get_auth_status()
        if status.get("logged_in", False):
            click.echo(f"Already logged in as: {status.get('username', 'Unknown')}")
            if not click.confirm("Log out and login as different user?", default=False):
                return
        
        # Get missing credentials
        if not username:
            username = click.prompt("MangaDex Username")
        if not password:
            password = click.prompt("MangaDex Password", hide_input=True)
        
        # Get OAuth2 credentials if needed
        if not client_id and click.confirm("Do you want to provide OAuth2 client credentials? (recommended)", default=True):
            client_id = click.prompt("MangaDex OAuth2 Client ID", default="")
            if client_id:
                client_secret = click.prompt("MangaDex OAuth2 Client Secret", hide_input=True)
        
        # Attempt login
        success, message = await login(username, password, client_id, client_secret)
        
        if success:
            click.secho(f"Logged in as: {username}", fg="green")
        else:
            click.secho(f"Login failed: {message or 'Unknown error'}", fg="red")
    except Exception as e:
        error = error_handler.handle(e, category=ErrorCategory.AUTHENTICATION)
        error_handler.display_error(error)
        logger.error(f"Error in login command: {e}")


async def logout_command() -> None:
    """Implementation of the logout command."""
    from .auth import logout, get_auth_status
    
    try:
        # Check if logged in
        status = await get_auth_status()
        if not status.get("logged_in", False):
            click.echo("Not currently logged in.")
            return
        
        # Logout
        success, message = await logout()
        
        if success:
            click.secho("Successfully logged out.", fg="green")
        else:
            click.secho(f"Logout failed: {message or 'Unknown error'}", fg="red")
    except Exception as e:
        error = error_handler.handle(e, category=ErrorCategory.AUTHENTICATION)
        error_handler.display_error(error)
        logger.error(f"Error in logout command: {e}")


async def check_command(path: Optional[str] = None, full: bool = False) -> None:
    """Implementation of the check command."""
    try:
        click.echo("Checking MangaBook environment...")
        
        # Check environment
        env = await check_environment()
        
        # Display API status
        if env.get("api", {}).get("accessible", False):
            click.secho("✅ MangaDex API is accessible", fg="green")
        else:
            click.secho("❌ MangaDex API is not accessible", fg="red")
            error = env.get("api", {}).get("error")
            if error:
                click.echo(f"  Error: {error}")
        
        # Display tool status
        click.echo("\nExternal Tools:")
        for tool, status in env.get("tools", {}).items():
            if status.get("available", False):
                click.secho(f"✅ {tool} is available", fg="green")
                if full and status.get("path"):
                    click.echo(f"  Path: {status['path']}")
            else:
                click.secho(f"❌ {tool} is not available", fg="yellow")
        
        # Display dependency status
        click.echo("\nDependencies:")
        for package, status in env.get("dependencies", {}).items():
            if status.get("installed", False):
                click.secho(f"✅ {package} is installed", fg="green")
            else:
                click.secho(f"❌ {package} is not installed", fg="red")
        
        # Check disk space if path provided
        if path:
            space_info = check_disk_space(path)
            click.echo(f"\nDisk Space at {path}:")
            click.echo(f"  Free: {space_info.get('free_mb', 0)} MB")
            click.echo(f"  Total: {space_info.get('total_mb', 0)} MB")
            click.echo(f"  Used: {space_info.get('used_mb', 0)} MB ({space_info.get('used_percent', 0)}%)")
            
            if space_info.get("enough_space", True):
                click.secho("  ✅ Sufficient disk space available", fg="green")
            else:
                click.secho(f"  ⚠️  Insufficient disk space (minimum: {space_info.get('required_mb', 0)} MB)", fg="yellow")
        
        # Check login status
        from .auth import get_auth_status
        status = await get_auth_status()
        click.echo("\nAuthentication:")
        if status.get("logged_in", False):
            click.secho(f"✅ Logged in as: {status.get('username', 'Unknown')}", fg="green")
        else:
            click.secho("❌ Not logged in", fg="yellow")
            click.echo("  Use 'mangabook login' to authenticate")
    except Exception as e:
        error = error_handler.handle(e, category=ErrorCategory.UNEXPECTED)
        error_handler.display_error(error)
        logger.error(f"Error in check command: {e}")


async def validate_command(epub_path: str) -> None:
    """Implementation of the validate command."""
    try:
        click.echo(f"Validating EPUB: {epub_path}")
        
        result = await validate_epub(epub_path)
        
        if result.get("valid") is True:
            click.secho("✅ EPUB is valid!", fg="green")
            if "output" in result:
                click.echo("\nValidation output:")
                click.echo(result["output"])
        elif result.get("valid") is False:
            click.secho("❌ EPUB validation failed", fg="red")
            if "error" in result:
                click.echo(f"\nError: {result['error']}")
            if "output" in result:
                click.echo("\nValidation output:")
                click.echo(result["output"])
        else:
            click.secho("⚠️  Could not validate EPUB", fg="yellow")
            if "error" in result:
                click.echo(f"\nReason: {result['error']}")
            click.echo("\nTip: Install epubcheck for EPUB validation")
            click.echo("  https://github.com/w3c/epubcheck")
    except Exception as e:
        error = error_handler.handle(e, category=ErrorCategory.VALIDATION)
        error_handler.display_error(error)
        logger.error(f"Error in validate command: {e}")


async def history_command(output_dir: str) -> None:
    """Implementation of the history command."""
    try:
        click.echo(f"Checking download history in: {output_dir}")
        
        # First, check the history file and prune old entries
        from .history import manga_history
        
        # Force a pruning of old entries and get stats
        entries_removed = manga_history.prune_history(30)  # Keep last 30 days
        
        # Load history data to check statistics
        history_data = manga_history.history_data
        total_manga = len(history_data.get("manga", {}))
        total_downloads = sum(
            len(manga.get("downloads", [])) 
            for manga in history_data.get("manga", {}).values()
        )
        
        # Get the date of the last pruning
        last_prune = history_data.get("last_prune")
        if last_prune:
            try:
                last_prune_date = datetime.fromisoformat(last_prune)
                last_prune_str = last_prune_date.strftime("%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                last_prune_str = "Unknown"
        else:
            last_prune_str = "Never"
        
        # Ensure directory exists
        output_path = Path(output_dir)
        if not output_path.exists() or not output_path.is_dir():
            click.secho(f"Directory not found: {output_dir}", fg="yellow")
            
            # Show history stats even if directory doesn't exist
            click.echo("\nManga History Statistics:")
            click.echo(f"Total manga in history: {total_manga}")
            click.echo(f"Total download entries: {total_downloads}")
            click.echo(f"Last pruned: {last_prune_str}")
            if entries_removed > 0:
                click.echo(f"Entries pruned in this session: {entries_removed} (older than 30 days)")
            return
        
        # Find all EPUB files
        epub_files = list(output_path.glob("**/*.epub"))
        kepub_files = list(output_path.glob("**/*.kepub.epub"))
        
        # Combine and sort by modification time
        all_files = epub_files + kepub_files
        all_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        
        if not all_files:
            click.echo("No EPUB files found in the directory.")
            
            # Show history stats even if no files found
            click.echo("\nManga History Statistics:")
            click.echo(f"Total manga in history: {total_manga}")
            click.echo(f"Total download entries: {total_downloads}")
            click.echo(f"Last pruned: {last_prune_str}")
            if entries_removed > 0:
                click.echo(f"Entries pruned in this session: {entries_removed} (older than 30 days)")
            return
        
        click.secho(f"\nFound {len(all_files)} EPUB files:", fg="bright_blue")
        click.echo("=" * 60)
        
        # Group by manga title
        manga_groups = {}
        
        for epub in all_files:
            # Try to extract manga title from filename
            filename = epub.stem.replace(".kepub", "")  # Remove .kepub for kepub.epub files
            
            # Extract manga title (assuming format: "Manga Title - Volume X")
            parts = filename.split(" - ")
            if len(parts) > 1:
                manga_title = parts[0]
                volume_info = parts[1]
            else:
                manga_title = filename
                volume_info = ""
            
            if manga_title not in manga_groups:
                manga_groups[manga_title] = []
            
            # Get file size and date
            size_mb = epub.stat().st_size / (1024 * 1024)
            mod_time = datetime.fromtimestamp(epub.stat().st_mtime)
            
            manga_groups[manga_title].append({
                "path": epub,
                "volume": volume_info,
                "size_mb": size_mb,
                "date": mod_time.strftime("%Y-%m-%d %H:%M"),
                "is_kepub": epub.suffix.lower() == ".epub" and ".kepub" in epub.name
            })
        
        # Display grouped by manga
        for manga, files in manga_groups.items():
            click.secho(f"\n{manga}", fg="bright_blue", bold=True)
            
            # Custom sort function for volumes
            def volume_sort_key(file_info):
                vol = file_info["volume"]
                
                # Handle "Volume X" format
                if vol.startswith("Volume "):
                    try:
                        # Extract and convert number
                        return float(vol.replace("Volume ", ""))
                    except ValueError:
                        pass
                
                # Handle "Chapters X-Y" format
                if vol.startswith("Chapters "):
                    try:
                        # Extract first chapter number for sorting
                        chapter_range = vol.replace("Chapters ", "")
                        first_chapter = chapter_range.split("-")[0]
                        return 1000 + float(first_chapter)  # Add 1000 so chapters come after volumes
                    except (ValueError, IndexError):
                        pass
                        
                # For ungrouped chapters or non-standard formats
                if vol.startswith("Ungrouped"):
                    return 9999  # Sort at the end
                    
                return vol
                
            files.sort(key=volume_sort_key)
            
            for file in files:
                format_tag = "[Kobo]" if file["is_kepub"] else "[EPUB]"
                click.echo(f"  {format_tag} {file['volume']} ({file['size_mb']:.1f} MB) - {file['date']}")
        
        click.echo("\nTotal size: {:.1f} MB".format(sum(file["size_mb"] for files in manga_groups.values() for file in files)))
        click.echo("=" * 60)
        
        # Show history stats
        click.echo("\nManga History Statistics:")
        click.echo(f"Total manga in history: {total_manga}")
        click.echo(f"Total download entries: {total_downloads}")
        click.echo(f"Last pruned: {last_prune_str}")
        if entries_removed > 0:
            click.echo(f"Entries pruned in this session: {entries_removed} (older than 30 days)")
        
    except Exception as e:
        error = error_handler.handle(e, category=ErrorCategory.UNEXPECTED)
        error_handler.display_error(error)
        logger.error(f"Error in history command: {e}")

if __name__ == "__main__":
    cli()
