"""Workflow module for manga download and conversion.

This module coordinates the downloading and processing of manga volumes, 
including image processing and EPUB generation.
"""

import os
import shutil
import asyncio
import logging
import json
from pathlib import Path
from typing import List, Dict, Any, Optional, Set, Tuple, Union
import click
from tqdm import tqdm
import sys
import subprocess
from datetime import datetime
import traceback

from .api import get_api
from .downloader import ChapterDownloader, download_manga_volumes
from .epub.image import ImageProcessor
from .epub.builder import EPUBBuilder
from .epub.kobo import KepubBuilder
from .utils import sanitize_filename, ensure_directory, generate_manga_path, generate_volume_path
from .error import error_handler, ErrorCategory, MangaBookError
from .ui import (
    print_info, print_success, print_warning, print_error, 
    print_manga_title, print_header, EnhancedProgress, ColorfulFormatter
)
from .history import manga_history

# Set up logging
logger = logging.getLogger(__name__)


async def process_manga(manga_id: str, manga_title: str, volumes: List[str],
                      output_dir: str, keep_raw: bool = False, quality: int = 85,
                      kobo: bool = True, language: str = "en", 
                      validate: bool = True) -> Dict[str, Any]:
    """Download manga volumes and convert to EPUB.
    
    Args:
        manga_id: MangaDex ID of the manga.
        manga_title: Title of the manga.
        volumes: List of volume numbers to download.
        output_dir: Output directory.
        keep_raw: Whether to keep raw downloaded files.
        quality: Image quality (1-100).
        kobo: Whether to create Kobo-compatible EPUB.
        language: Language code.
        validate: Whether to validate generated EPUBs.
        
    Returns:
        Dict with processing results.
    """
    # Track start time
    start_time = datetime.now()
    
    results = {
        "manga_id": manga_id,
        "manga_title": manga_title,
        "volumes": {},
        "successful": 0,
        "failed": 0,
        "skipped": 0,
        "epub_files": [],
        "validation_results": {},
        "missing_content": [],
        "warnings": [],
        "started_at": str(start_time),
    }
    
    # Get the API instance for later use
    api = await get_api()
    
    try:
        # Step 1: Create output directory
        output_dir = Path(output_dir)
        ensure_directory(output_dir)
        
        # Print manga title and volume info
        print_header(f"Processing Manga", width=60)
        print_manga_title(manga_title)
        print_info(f"Manga ID: {manga_id}")
        print_info(f"Volumes: {', '.join(volumes)}")
        
        # Step 2: Initialize downloader with parallel capabilities
        downloader = ChapterDownloader(
            output_dir=str(output_dir), 
            keep_raw=keep_raw,
            max_concurrent=5,  # 5 concurrent chapter downloads
            use_cache=True,    # Use API response caching
            api=api            # Pass the same API instance to avoid resource duplication
        )
        
        await error_handler.safe_execute_async(
            downloader.initialize,
            error_category=ErrorCategory.NETWORK,
            display=True
        )
        
        # Step 3: Process each volume
        total_volumes = len(volumes)
        
        # Use enhanced progress bar with ETA
        progress = EnhancedProgress(
            total=total_volumes,
            desc="Processing volumes",
            unit="vol",
            show_eta=True
        )
        
        for volume_number in volumes:
            print_info(f"\nProcessing volume {ColorfulFormatter.volume(volume_number)}...")
            
            # Step 3.1: Download volume
            download_result = await error_handler.safe_execute_async(
                downloader.download_volume,
                manga_id=manga_id,
                manga_title=manga_title,
                volume_number=volume_number,
                language=language,
                error_category=ErrorCategory.NETWORK,
                display=True
            )
            
            if not download_result:
                print_error(f"Failed to download volume {volume_number}")
                results["failed"] += 1
                results["volumes"][volume_number] = {"success": False, "message": "Download failed"}
                progress.update(1)
                continue
            
            results["volumes"][volume_number] = download_result
            
            if not download_result["success"]:
                print_error(f"Failed to download volume {volume_number}: {download_result['message']}")
                results["failed"] += 1
                progress.update(1)
                continue
            
            # Step 3.2: Process images
            try:
                volume_path = Path(download_result["volume_path"])
                processed_dir = volume_path / "processed"
                
                # Initialize image processor
                img_processor = ImageProcessor(
                    output_dir=processed_dir,
                    quality=quality,
                    split_wide_pages=True
                )
                
                # Process each chapter
                chapter_dirs = [d for d in volume_path.iterdir() if d.is_dir() and d.name.startswith("chapter_")]
                processed_images = []
                
                click.echo(f"Processing {len(chapter_dirs)} chapters...")
                
                for chapter_dir in chapter_dirs:
                    # Process all images in the chapter
                    processed = error_handler.safe_execute(
                        img_processor.process_directory,
                        source_dir=chapter_dir,
                        output_subdir=chapter_dir.name,
                        error_category=ErrorCategory.CONVERSION,
                        display=True
                    )
                    
                    if not processed:
                        results["warnings"].append(f"Failed to process images in {chapter_dir.name}")
                        continue
                        
                    # Collect all processed images
                    for source_file, proc_files in processed.items():
                        processed_images.extend(proc_files)
                
                # Sort the processed images
                processed_images.sort()
                
                # Step 3.3: Create EPUB
                if processed_images:
                    # Get manga details for metadata
                    api = await get_api()
                    manga_data = await api.get_manga(manga_id)
                    
                    author = "Unknown"
                    if manga_data and "attributes" in manga_data:
                        author = manga_data["attributes"].get("author", author)
                    
                    # Prepare volume title
                    vol_title = f"{manga_title} - Volume {volume_number}"
                    
                    # Create safe filename
                    safe_title = sanitize_filename(vol_title)
                    
                    # Determine cover image (first image)
                    cover_image = processed_images[0] if processed_images else None
                    
                    # Get reading direction from image processor
                    reading_direction = img_processor.detect_reading_direction(volume_path)
                    
                    # Create EPUB
                    if kobo:
                        # Create Kobo EPUB
                        builder_class = KepubBuilder
                        epub_ext = ".kepub.epub"
                    else:
                        # Create standard EPUB
                        builder_class = EPUBBuilder
                        epub_ext = ".epub"
                    
                    epub_filename = f"{safe_title}{epub_ext}"
                    
                    builder = builder_class(
                        title=vol_title,
                        output_dir=output_dir,
                        language=language,
                        author=author
                    )
                    
                    # Set reading direction
                    builder.set_reading_direction(reading_direction)
                    
                    # Set cover if available
                    if cover_image:
                        builder.set_cover(cover_image)
                        # Skip the first image in the content if it's used as the cover
                        content_images = processed_images[1:]
                    else:
                        content_images = processed_images
                    
                    # Add images
                    for img in content_images:
                        builder.add_image(img)
                    
                    # Write EPUB
                    epub_path = error_handler.safe_execute(
                        builder.write,
                        epub_filename,
                        error_category=ErrorCategory.FILE_SYSTEM,
                        display=True
                    )
                    
                    if not epub_path:
                        click.echo(f"Failed to create EPUB for volume {volume_number}")
                        results["failed"] += 1
                        progress.update(1)
                        continue
                        
                    click.echo(f"Created {epub_path}")
                    results["epub_files"].append(epub_path)
                    
                    # Validate EPUB if requested
                    if validate:
                        click.echo(f"Validating {epub_path}...")
                        validation_result = await validate_epub(epub_path)
                        results["validation_results"][epub_path] = validation_result
                        
                        if validation_result.get("valid") is False:
                            click.secho(f"⚠️  Validation failed for {epub_path}", fg="yellow")
                            if "error" in validation_result:
                                click.echo(f"  Error: {validation_result['error']}")
                        elif validation_result.get("valid") is True:
                            click.secho(f"✅ Validation passed for {epub_path}", fg="green")
                        else:
                            click.echo(f"⚠️  Could not validate {epub_path}")
                    
                    # Delete raw files if not keeping them
                    if not keep_raw:
                        for chapter_dir in chapter_dirs:
                            try:
                                shutil.rmtree(chapter_dir)
                            except Exception as e:
                                logger.warning(f"Could not delete directory {chapter_dir}: {e}")
                        
                        # Delete processed directory
                        try:
                            shutil.rmtree(processed_dir)
                        except Exception as e:
                            logger.warning(f"Could not delete directory {processed_dir}: {e}")
                else:
                    click.secho(f"⚠️  No processed images found for volume {volume_number}", fg="yellow")
                    results["warnings"].append(f"No processed images found for volume {volume_number}")
                    results["skipped"] += 1
                    progress.update(1)
                    continue
            
            except Exception as e:
                error = error_handler.handle(e, category=ErrorCategory.UNEXPECTED)
                error_handler.display_error(error)
                logger.error(f"Error processing volume {volume_number}: {e}")
                results["volumes"][volume_number]["error"] = str(e)
                results["failed"] += 1
                progress.update(1)
                continue
            
            results["successful"] += 1
            progress.update(1)
        
        # Step 4: Record in history
        if results["successful"] > 0:
            manga_history.record_manga_download(
                manga_id=manga_id,
                manga_title=manga_title,
                volumes=volumes,
                success=True,
                metadata={
                    "epub_files": results["epub_files"],
                    "output_dir": str(output_dir)
                }
            )
        
        # Step 5: Clean up
        await downloader.close()
        progress.close()
        
        # Print summary
        print_header("Summary", width=60)
        print_success(f"Successful volumes: {results['successful']}")
        if results["failed"] > 0:
            print_error(f"Failed volumes: {results['failed']}")
        if results["skipped"] > 0:
            print_warning(f"Skipped volumes: {results['skipped']}")
        print_info(f"Total files created: {len(results['epub_files'])}")
        
        # Step 5: Summary
        # Calculate end time
        end_time = datetime.now()
        elapsed_time = end_time - start_time
        results["completed_at"] = str(end_time)
        results["elapsed_seconds"] = elapsed_time.total_seconds()
        
        display_results_summary(results)
        
        return results
    
    except Exception as e:
        error = error_handler.handle(e, category=ErrorCategory.UNEXPECTED)
        error_handler.display_error(error)
        logger.error(f"Error in process_manga workflow: {e}")
        
        # Calculate end time even on error
        end_time = datetime.now()
        elapsed_time = end_time - start_time
        results["completed_at"] = str(end_time)
        results["elapsed_seconds"] = elapsed_time.total_seconds()
        
        return results
    
    finally:
        # Always ensure resources are properly cleaned up
        if 'downloader' in locals():
            await downloader.close()
        
        return {
            **results,
            "error": str(e)
        }
    

def display_results_summary(results: Dict[str, Any]) -> None:
    """Display a summary of processing results.
    
    Args:
        results: Processing results from process_manga.
    """
    click.echo("\n" + "="*60)
    click.secho("📊 Processing Summary", fg="bright_blue", bold=True)
    click.echo("="*60)
    
    click.echo(f"Manga: {results['manga_title']} (ID: {results['manga_id']})")
    
    # Status counts
    click.echo("\n📈 Status:")
    click.secho(f"✅ Successful: {results['successful']}", fg="green")
    click.secho(f"❌ Failed: {results['failed']}", fg="red" if results['failed'] > 0 else "white")
    click.secho(f"⏭️  Skipped: {results.get('skipped', 0)}", fg="yellow" if results.get('skipped', 0) > 0 else "white")
    
    # Time information
    if 'elapsed_seconds' in results:
        minutes, seconds = divmod(results['elapsed_seconds'], 60)
        click.echo(f"\n⏱️  Time: {int(minutes)}m {int(seconds)}s")
    
    # Generated files
    if results["epub_files"]:
        click.echo("\n📚 Generated EPUB files:")
        for epub_file in results["epub_files"]:
            click.echo(f"- {epub_file}")
    
    # Validation results
    if results.get("validation_results"):
        click.echo("\n🔍 Validation Results:")
        
        valid_count = sum(1 for r in results["validation_results"].values() if r.get("valid") is True)
        invalid_count = sum(1 for r in results["validation_results"].values() if r.get("valid") is False)
        skipped_count = sum(1 for r in results["validation_results"].values() if r.get("valid") is None)
        
        click.echo(f"- Valid: {valid_count}")
        click.echo(f"- Invalid: {invalid_count}")
        
        if skipped_count:
            click.echo(f"- Not validated: {skipped_count}")
            
        if invalid_count > 0:
            click.echo("\n⚠️  Some EPUB files failed validation. Consider installing epubcheck for better results.")
    
    # Warnings
    if results.get("warnings"):
        click.echo("\n⚠️  Warnings:")
        for warning in results["warnings"]:
            click.echo(f"- {warning}")
    
    # Error summary
    error_handler.display_summary()
    click.echo("="*60)


async def validate_epub(epub_path: Union[str, Path]) -> Dict[str, Any]:
    """Validate an EPUB file using epubcheck if available.
    
    Args:
        epub_path: Path to the EPUB file.
        
    Returns:
        Dict with validation results.
    """
    epub_path = Path(epub_path)
    
    if not epub_path.exists():
        return {
            "valid": False,
            "error": f"File not found: {epub_path}"
        }
    
    # Check if epubcheck is available
    epubcheck_path = shutil.which("epubcheck")
    if not epubcheck_path:
        return {
            "valid": None,  # None means validation was not performed
            "error": "EpubCheck not found in PATH"
        }
    
    # Run epubcheck
    try:
        import subprocess
        process = subprocess.run(
            ["epubcheck", str(epub_path)],
            capture_output=True,
            text=True,
            check=False
        )
        
        if process.returncode == 0:
            return {
                "valid": True,
                "output": process.stdout
            }
        else:
            return {
                "valid": False,
                "error": process.stderr,
                "output": process.stdout
            }
    except Exception as e:
        return {
            "valid": False,
            "error": str(e)
        }


def check_disk_space(path: Union[str, Path], required_mb: float = 100.0) -> Dict[str, Any]:
    """Check available disk space at the given path.
    
    Args:
        path: Path to check.
        required_mb: Required space in megabytes.
        
    Returns:
        Dict with disk space information.
    """
    path = Path(path)
    
    try:
        # Get disk usage statistics
        import shutil
        usage = shutil.disk_usage(path)
        
        # Convert to MB
        free_mb = usage.free / (1024 * 1024)
        total_mb = usage.total / (1024 * 1024)
        used_mb = usage.used / (1024 * 1024)
        
        enough_space = free_mb >= required_mb
        
        return {
            "free_mb": round(free_mb, 2),
            "total_mb": round(total_mb, 2),
            "used_mb": round(used_mb, 2),
            "used_percent": round(used_mb / total_mb * 100, 2),
            "enough_space": enough_space,
            "required_mb": required_mb
        }
    except Exception as e:
        logger.error(f"Error checking disk space: {e}")
        return {
            "error": str(e),
            "enough_space": False,
            "required_mb": required_mb
        }


async def check_environment() -> Dict[str, Any]:
    """Check the environment for tools and dependencies.
    
    Returns:
        Dict with environment information.
    """
    environment = {
        "tools": {},
        "dependencies": {}
    }
    
    # Check for external tools
    tools = ["epubcheck"]
    for tool in tools:
        tool_path = shutil.which(tool)
        environment["tools"][tool] = {
            "available": tool_path is not None,
            "path": tool_path
        }
    
    # Check Python dependencies
    for package in ["ebooklib", "PIL", "click", "tqdm", "requests", "aiohttp"]:
        try:
            __import__(package.split(".")[0])  # Import the top-level package
            environment["dependencies"][package] = {"installed": True}
        except ImportError:
            environment["dependencies"][package] = {"installed": False}
    
    # Test API connectivity
    try:
        api = await get_api()
        test_result = await api.ping()
        environment["api"] = {
            "accessible": test_result is not None,
            "response": test_result
        }
    except Exception as e:
        environment["api"] = {
            "accessible": False,
            "error": str(e)
        }
    
    return environment
