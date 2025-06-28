"""Command Line Interface for MangaBook.

This module provides the CLI functionality for the MangaBook application,
including manga search, selection, and display features.
"""

print("[DEBUG] cli.py: CLI entry point reached")  # DEBUG

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


async def search_manga(query: str, language: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
    """Search for manga by title.
    
    Args:
        query: The search query.
        language: Optional language filter.
        limit: Maximum number of results.
        
    Returns:
        List of manga search results.
    """
    logger.info(f"Searching for manga: {query}")
    
    api = await get_api()
    try:
        response = await api.search_manga(query, limit=limit, language=language)
        
        results = []
        for manga in response.get("data", []):
            manga_id = manga["id"]
            attributes = manga["attributes"]
            
            # Get title in requested language or fall back to English or Japanese
            title = None
            if attributes.get("title"):
                title_dict = attributes["title"]
                if language and language in title_dict:
                    title = title_dict[language]
                elif "en" in title_dict:
                    title = title_dict["en"]
                elif "ja" in title_dict:
                    title = title_dict["ja"]
                else:
                    # Just take the first available title
                    title = next(iter(title_dict.values()), "Unknown")
            
            # Get cover art if available
            cover_url = ""
            for relationship in manga.get("relationships", []):
                if relationship["type"] == "cover_art" and "attributes" in relationship:
                    filename = relationship["attributes"].get("fileName")
                    if filename:
                        cover_url = f"https://uploads.mangadex.org/covers/{manga_id}/{filename}"
            
            manga_data = {
                "id": manga_id,
                "title": format_manga_title(title) if title else "Unknown",
                "original_language": attributes.get("originalLanguage", "unknown"),
                "year": attributes.get("year"),
                "status": attributes.get("status", "unknown"),
                "description": clean_html(attributes.get("description", {}).get("en", "")),
                "cover_url": cover_url,
            }
            results.append(manga_data)
        
        return results
    finally:
        await api.close()


def display_manga_search_results(results: List[Dict[str, Any]]) -> None:
    """Display manga search results in a table format.
    
    Args:
        results: List of manga search results.
    """
    if not results:
        click.secho("No results found.", fg="yellow")
        return
    
    # Prepare table data
    headers = ["#", "Title", "Language", "Status", "Year", "ID"]
    rows = []
    
    for i, manga in enumerate(results):
        rows.append([
            str(i + 1),
            truncate_string(manga.get("title", "Unknown"), 50),
            manga.get("original_language", "unknown"),
            manga.get("status", "unknown"),
            str(manga.get("year", "N/A")),
            manga.get("id", "N/A"),
        ])
    
    # Create and display table
    table = create_table(headers, rows)
    click.echo("\nSearch Results:\n")
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
        chapters = await api.get_chapters(manga_id, language=language)
        
        volumes = {}
        
        for chapter in chapters.get("data", []):
            attributes = chapter.get("attributes", {})
            volume = attributes.get("volume") or "Unknown"
            chapter_num = attributes.get("chapter") or "Unknown"
            
            # Initialize volume entry if not exists
            if volume not in volumes:
                volumes[volume] = {
                    "chapters": [],
                    "count": 0,
                    "scanlation_groups": set()
                }
            
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
                "pages": attributes.get("pages", 0)
            })
            volumes[volume]["count"] += 1
        
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
    
    # Sort volumes numerically
    sorted_volumes = sorted(
        volumes.items(),
        key=lambda x: float(x[0]) if x[0].replace(".", "").isdigit() else float("inf")
    )
    
    for volume, data in sorted_volumes:
        if volume == "null" or volume == "None":
            volume_text = "Unknown"
        else:
            volume_text = f"Volume {volume}"
        
        click.secho(f"\n{volume_text}", fg="bright_blue", bold=True)
        click.echo(f"Chapters: {data['count']}")
        
        if data.get("scanlation_groups"):
            groups = ", ".join(data["scanlation_groups"])
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
    for volume in volumes.keys():
        if volume != "null" and volume != "None" and volume != "Unknown":
            available_volumes.append(volume)
    
    # Sort volumes numerically
    available_volumes.sort(
        key=lambda x: float(x) if x.replace(".", "").isdigit() else float("inf")
    )
    
    if not available_volumes:
        click.secho("No volumes available to select.", fg="yellow")
        return set()
    
    # Prompt for volumes
    click.echo("\nEnter volume selection:")
    click.echo("Examples: '1' (single volume), '1,3,5' (multiple volumes), '1-5' (range), 'all'")
    
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
@click.option('--limit', default=10, help="Maximum number of results")
@click.pass_context
def search(ctx, query, language, limit):
    """Search for manga by title.
    
    Examples:
      mangabook search "one piece"
      mangabook search "naruto" --language ja
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
@click.option('--language', '-l', default='en', help="Language for translation")
@click.option('--output', '-o', help="Output directory")
@click.option('--keep-raw', is_flag=True, help="Keep raw downloaded files")
@click.option('--quality', default=85, help="Image quality (1-100)")
@click.option('--kobo', is_flag=True, default=True, help="Create Kobo-compatible EPUB")
@click.option('--use-enhanced-builder', is_flag=True, default=True, help="Use the enhanced builder for more reliable EPUB generation with strict spec compliance")
@click.option('--no-validate', is_flag=True, help="Skip EPUB validation")
@click.option('--check-local', is_flag=True, default=True, help="Check for valid local files before downloading")
@click.option('--force-download', is_flag=True, help="Force download even if local files exist")
@click.pass_context
def download(ctx, manga_id, volumes, language, output, keep_raw, quality, kobo, 
             use_enhanced_builder, no_validate, check_local, force_download):
    """Download manga volumes and convert to EPUB.
    
    MANGA_ID is the MangaDex ID of the manga.
    
    Examples:
      mangabook download 32d76d19-8a05-4db0-9fc2-e0b0648fe9d0 --volumes "1-10"
      mangabook download 32d76d19-8a05-4db0-9fc2-e0b0648fe9d0 --volumes "1,3,5"
      mangabook download 32d76d19-8a05-4db0-9fc2-e0b0648fe9d0 --volumes "1-3" --check-local
      mangabook download 32d76d19-8a05-4db0-9fc2-e0b0648fe9d0 --volumes "1-3" --force-download
    """
    print(f"[DEBUG] cli.py: download command called with manga_id={manga_id}, volumes={volumes}, output={output}")  # DEBUG
    config = ctx.obj['CONFIG']
    
    # Use config values if options not provided
    if not output:
        output = config.get_output_dir()
    
    # If force_download is specified, disable check_local
    if force_download:
        check_local = False
    
    asyncio.run(download_command(
        manga_id, volumes, language, output, keep_raw, quality, kobo,
        use_enhanced_builder, not no_validate, check_local, force_download
    ))


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
        results = await search_manga(query, language, limit)
        display_manga_search_results(results)
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
                         kobo: bool, use_enhanced_builder: bool = True, validate: bool = True, 
                         check_local: bool = True, force_download: bool = False) -> None:
    """Implementation of the download command."""
    try:
        # Check disk space
        space_info = check_disk_space(output_dir, required_mb=500)
        if not space_info.get("enough_space", True):
            click.secho(f"⚠️  Low disk space: {space_info.get('free_mb', 0)} MB available", fg="yellow")
            if not click.confirm("Continue anyway?", default=False):
                return
        
        # Get manga details
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
            force_download=force_download
        )
        
    except Exception as e:
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
        
        # Check if logged in
        api = await get_api()
        
        # Step 1: Login (optional)
        if click.confirm("Do you want to log in to MangaDex?", default=False):
            success = await login_flow()
            if not success:
                if not click.confirm("Continue without logging in?", default=True):
                    return
        
        # Step 2: Search for manga
        while True:
            query = click.prompt("Enter search term (or leave empty to exit)")
            if not query:
                break
            
            language = click.prompt("Language code", default="en")
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
            config = Config()
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
            
            keep_raw = click.confirm("Keep raw downloaded files?", default=False)
            quality = click.prompt("Image quality (1-100)", default=85, type=int)
            kobo = click.confirm("Create Kobo-compatible EPUB?", default=True)
            validate = click.confirm("Validate generated EPUBs?", default=True)
            
            # Step 7: Process manga
            
            await process_manga(
                manga_id=manga_id,
                manga_title=manga_title,
                volumes=list(selected_volumes),
                output_dir=output_dir,
                keep_raw=keep_raw,
                quality=quality,
                kobo=kobo,
                language=language,
                validate=validate
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
        
        # Ensure directory exists
        output_path = Path(output_dir)
        if not output_path.exists() or not output_path.is_dir():
            click.secho(f"Directory not found: {output_dir}", fg="yellow")
            return
        
        # Find all EPUB files
        epub_files = list(output_path.glob("**/*.epub"))
        kepub_files = list(output_path.glob("**/*.kepub.epub"))
        
        # Combine and sort by modification time
        all_files = epub_files + kepub_files
        all_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        
        if not all_files:
            click.echo("No EPUB files found in the directory.")
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
            
            # Sort by volume number if possible
            def volume_sort_key(item):
                vol = item["volume"]
                if vol.lower().startswith("volume "):
                    try:
                        return float(vol[7:])
                    except ValueError:
                        pass
                return vol
                
            files.sort(key=volume_sort_key)
            
            for file in files:
                format_tag = "[Kobo]" if file["is_kepub"] else "[EPUB]"
                click.echo(f"  {format_tag} {file['volume']} ({file['size_mb']:.1f} MB) - {file['date']}")
        
        click.echo("\nTotal size: {:.1f} MB".format(sum(file["size_mb"] for files in manga_groups.values() for file in files)))
        click.echo("=" * 60)
        
    except Exception as e:
        error = error_handler.handle(e, category=ErrorCategory.UNEXPECTED)
        error_handler.display_error(error)
        logger.error(f"Error in history command: {e}")

if __name__ == "__main__":
    cli()
