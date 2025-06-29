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
from .epub.enhanced_builder import EnhancedEPUBBuilder, EnhancedKepubBuilder
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
                      kobo: bool = True, use_enhanced_builder: bool = True, language: str = "en", 
                      validate: bool = True, check_local: bool = True, force_download: bool = False,
                      use_official_covers: bool = True, create_kobo_collection: bool = True,
                      collection_root: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """Download manga volumes and convert to EPUB.
    
    Args:
        manga_id: MangaDex ID of the manga.
        manga_title: Title of the manga.
        volumes: List of volume numbers to download.
        output_dir: Output directory.
        keep_raw: Whether to keep raw downloaded files.
        quality: Image quality (1-100).
        kobo: Whether to create Kobo-compatible EPUB.
        use_enhanced_builder: Whether to use the enhanced builder (recommended for large volumes).
        language: Language code.
        validate: Whether to validate generated EPUBs.
        check_local: Whether to check for existing files before downloading.
        force_download: Whether to force download even if local files exist.
        use_official_covers: Whether to use official MangaDex volume covers when available.
        create_kobo_collection: Whether to create a canonical Kobo collection folder.
        collection_root: Root directory for the manga collection. If not specified,
                        defaults to '{output_dir}/manga-collection'.
        
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
        
        # Print local file options
        if check_local:
            print_info("Local file checking: Enabled (will skip valid existing files)")
        if force_download:
            print_info("Force download: Enabled (will re-download all files)")
        
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
                check_local=check_local,
                force_download=force_download,
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
                
                # Find chapter directories
                chapter_dirs = [d for d in volume_path.iterdir() if d.is_dir() and d.name.startswith("chapter_")]
                # Group processed images by chapter
                chapter_image_map = {}
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
                    # Collect all processed images for this chapter
                    chapter_image_map[chapter_dir.name] = []
                    for source_file, proc_files in processed.items():
                        chapter_image_map[chapter_dir.name].extend(proc_files)
                # Sort chapters by name (which should be in reading order)
                sorted_chapters = sorted(chapter_image_map.items())
                
                # Step 3.3: Create EPUB
                all_images = [img for _, imgs in sorted_chapters for img in imgs]
                if all_images:
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
                    
                    # Determine cover image
                    cover_image = None
                    
                    # Use official MangaDex cover if enabled
                    if use_official_covers:
                        # Get the official MangaDex cover for this volume
                        official_cover_url = await api.get_volume_cover_art(manga_id, volume_number)
                        if official_cover_url:
                            # Download the official cover
                            official_cover_path = volume_path / "official_cover.jpg"
                            downloaded_cover = await api.download_cover_image(official_cover_url, official_cover_path)
                            if downloaded_cover:
                                cover_image = official_cover_path
                                logger.info(f"Using official MangaDex cover for volume {volume_number}")
                    
                    # Fall back to the first image if no official cover or feature disabled
                    if not cover_image:
                        if use_official_covers:
                            logger.info(f"No official cover found, using first image as cover")
                        else:
                            logger.info(f"Official covers disabled, using first image as cover")
                        cover_image = all_images[0] if all_images else None
                    
                    # Get reading direction from image processor
                    reading_direction = img_processor.detect_reading_direction(volume_path)
                    
                    # Create EPUB
                    if use_enhanced_builder:
                        # Use the enhanced builder that handles large manga volumes better
                        if kobo:
                            # Create Kobo EPUB with enhanced builder
                            builder_class = EnhancedKepubBuilder
                            epub_ext = ".kepub.epub"
                        else:
                            # Create standard EPUB with enhanced builder
                            builder_class = EnhancedEPUBBuilder
                            epub_ext = ".epub"
                    else:
                        # Use the original builders
                        if kobo:
                            # Create Kobo EPUB
                            builder_class = KepubBuilder
                            epub_ext = ".kepub.epub"
                        else:
                            # Create standard EPUB
                            builder_class = EPUBBuilder
                            epub_ext = ".epub"
                    
                    # Determine the output directory and filename based on collection settings
                    builder_output_dir = output_dir
                    
                    # If we're creating a Kobo collection, prepare the collection directory
                    if kobo and create_kobo_collection:
                        # Create collection root if specified, otherwise use default
                        coll_root = Path(collection_root) if collection_root else Path(output_dir) / "manga-collection"
                        # Create manga-specific directory inside the collection root
                        manga_coll_dir = coll_root / sanitize_filename(manga_title)
                        ensure_directory(manga_coll_dir)
                        # Set the builder to output to the manga collection directory
                        builder_output_dir = manga_coll_dir
                        
                        # For collections, use a more reader-friendly filename format
                        # Special handling for ungrouped chapters
                        if volume_number == "0":
                            # For ungrouped chapters, use a special naming convention
                            chapter_numbers = []
                            for chapter_name, _ in sorted_chapters:
                                # Try to extract chapter number from the chapter name
                                try:
                                    chapter_num = chapter_name.split()[1]  # Assuming format "Chapter X"
                                    chapter_numbers.append(chapter_num)
                                except (IndexError, ValueError):
                                    pass
                            
                            # Create a range or list of chapter numbers
                            if chapter_numbers:
                                if len(chapter_numbers) == 1:
                                    chapter_range = chapter_numbers[0]
                                else:
                                    chapter_range = f"{chapter_numbers[0]}-{chapter_numbers[-1]}"
                                epub_filename = f"{manga_title} - Chapters {chapter_range}{epub_ext}"
                            else:
                                epub_filename = f"{manga_title} - Ungrouped Chapters{epub_ext}"
                        else:
                            try:
                                volume_num = int(float(volume_number))  # Handle volume numbers like "1.0"
                                epub_filename = f"{manga_title} - Volume {volume_num:03d}{epub_ext}"
                            except ValueError:
                                # Handle non-numeric volume numbers
                                epub_filename = f"{manga_title} - Volume {volume_number}{epub_ext}"
                    else:
                        # Standard filename with underscores for non-collection output
                        # Special handling for ungrouped chapters
                        if volume_number == "0":
                            epub_filename = f"{safe_title}_ungrouped_chapters{epub_ext}"
                        else:
                            epub_filename = f"{safe_title}{epub_ext}"
                    
                    # builder_output_dir is already set above, so we don't need to modify it here
                        
                    builder = builder_class(
                        title=vol_title,
                        output_dir=builder_output_dir,  # This now correctly points to either the collection dir or main output dir
                        language=language,
                        author=author
                    )
                    
                    # Always set reading direction to rtl (right-to-left) for manga
                    builder.set_reading_direction('rtl')
                    
                    # Set cover if available
                    if cover_image:
                        builder.set_cover(cover_image)
                        
                        # If the cover is the first image and the official MangaDex cover wasn't used,
                        # exclude it from the content to avoid duplication
                        if cover_image == all_images[0]:
                            content_images = all_images[1:]
                        else:
                            content_images = all_images
                    else:
                        content_images = all_images
                    
                    # Add chapters and images
                    for chapter_name, images in sorted_chapters:
                        if images:
                            # If this chapter contains the cover image that was already used as the cover,
                            # and it's the first image of the chapter, remove it to avoid duplication
                            chapter_images = images
                            if cover_image and images and cover_image == images[0]:
                                chapter_images = images[1:]
                                
                            if chapter_images:
                                builder.add_chapter(chapter_name, chapter_name, chapter_images)
                    
                    # The epub_filename is already set above based on collection settings
                        
                    # Pass just the filename to builder.write, which will combine it with its output_dir
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
        
        # Print download statistics if available
        download_stats = {}
        for vol_num, vol_result in results.get("volumes", {}).items():
            if isinstance(vol_result, dict) and "stats" in vol_result:
                for key, value in vol_result["stats"].items():
                    download_stats[key] = download_stats.get(key, 0) + value
        
        if download_stats:
            print_header("Download Statistics", width=60)
            print_info(f"Files downloaded: {download_stats.get('downloaded', 0)}")
            print_info(f"Files skipped (already valid): {download_stats.get('skipped', 0)}")
            print_info(f"Files failed: {download_stats.get('failed', 0)}")
            print_info(f"Download retries: {download_stats.get('retries', 0)}")
        
        # Step 5: Summary
        # Calculate end time
        end_time = datetime.now()
        elapsed_time = end_time - start_time
        results["completed_at"] = str(end_time)
        results["elapsed_seconds"] = elapsed_time.total_seconds()
        
        # Since Kobo files are now directly placed in the manga-collection folder, 
        # we don't need to collect them again, just report the location
        if kobo and create_kobo_collection and results["successful"] > 0:
            # Use specified collection_root or default to {output_dir}/manga-collection
            root_dir = Path(collection_root) if collection_root else Path(output_dir) / "manga-collection"
            kobo_dir = root_dir / sanitize_filename(manga_title.replace('_', ' '))
            
            # Just record the collection info for reporting
            kobo_files = list(kobo_dir.glob("*.kepub.epub"))
            count = len(kobo_files)
            
            if count > 0:
                print_success(f"Created {count} Kobo files for '{manga_title}' in {kobo_dir}")
                print_info(f"Collection root: {root_dir}")
                
                # Record results similar to what collect_kobo_files would return
                results["kobo_collection"] = {
                    "success": True,
                    "manga_title": manga_title,
                    "kobo_dir": str(kobo_dir),
                    "collection_root": str(root_dir),
                    "files": [{"source": str(f), "destination": str(f), "success": True} for f in kobo_files]
                }
            else:
                print_warning(f"No Kobo files found in {kobo_dir}")
                results["kobo_collection"] = {
                    "success": False, 
                    "message": "No Kobo files found",
                    "manga_title": manga_title,
                    "kobo_dir": str(kobo_dir)
                }
        
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


async def collect_kobo_files(output_dir: Union[str, Path], manga_title: str, 
                        create_symlinks: bool = False, 
                        collection_root: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """Collect all .kepub.epub files for a manga into a canonical folder structure.
    
    Creates a folder structure like:
    {manga-collection-root}/
      {manga_title}/
        {volume1}.kepub.epub
        {volume2}.kepub.epub
    
    Args:
        output_dir: Base directory where manga volumes are stored.
        manga_title: Title of the manga.
        create_symlinks: Whether to create symlinks instead of copying files.
        collection_root: Root directory for the manga collection. If not specified,
                         will use '{output_dir}/manga-collection' as the root directory.
        
    Returns:
        Dict with results of the collection process.
    """
    output_dir = Path(output_dir)
    safe_manga_name = sanitize_filename(manga_title)
    manga_dir = output_dir / safe_manga_name
    
    # Find all volume directories
    volume_dirs = list(manga_dir.glob("volume_*"))
    if not volume_dirs:
        logger.warning(f"No volume directories found for manga '{manga_title}'")
        return {"success": False, "message": "No volume directories found"}
    
    # Create canonical Kobo collection structure
    if collection_root:
        collection_root = Path(collection_root)
    else:
        # Default collection root is in the output directory
        collection_root = output_dir / "manga-collection"
        
    # Create manga-specific directory inside the collection root
    kobo_dir = collection_root / sanitize_filename(manga_title.replace('_', ' '))
    ensure_directory(kobo_dir)
    
    results = {
        "manga_title": manga_title,
        "kobo_dir": str(kobo_dir),
        "collection_root": str(collection_root),
        "files": [],
        "success": True
    }
    
    # Find all .kepub.epub files in volume directories
    for volume_dir in volume_dirs:
        kepub_files = list(volume_dir.glob("*.kepub.epub"))
        for kepub_file in kepub_files:
            # Extract volume number from the filename or directory name
            # First try to get it from the filename
            import re
            volume_match = re.search(r'volume[_\s-]*(\d+)', kepub_file.stem, re.IGNORECASE)
            
            if not volume_match:
                # Try to extract from the directory name
                volume_match = re.search(r'volume[_\s-]*(\d+)', volume_dir.name, re.IGNORECASE)
                
            volume_num = volume_match.group(1) if volume_match else "unknown"
            
            # Create a nicely formatted destination filename
            # Use manga title with spaces instead of underscores for better readability
            readable_manga_name = manga_title.replace('_', ' ')
            dest_filename = f"{readable_manga_name} - Volume {volume_num}.kepub.epub"
            dest_path = kobo_dir / dest_filename
            
            try:
                if create_symlinks:
                    # Create a symbolic link
                    if dest_path.exists():
                        dest_path.unlink()
                    os.symlink(kepub_file, dest_path)
                    logger.info(f"Created symbolic link: {dest_path} -> {kepub_file}")
                else:
                    # Copy the file
                    shutil.copy2(kepub_file, dest_path)
                    logger.info(f"Copied: {kepub_file} -> {dest_path}")
                
                results["files"].append({
                    "source": str(kepub_file),
                    "destination": str(dest_path),
                    "success": True
                })
            except Exception as e:
                logger.error(f"Error processing {kepub_file}: {e}")
                results["files"].append({
                    "source": str(kepub_file),
                    "destination": str(dest_path),
                    "success": False,
                    "error": str(e)
                })
    
    # Create a README file with instructions
    from datetime import datetime
    readme_content = f"""# Manga Collection for Kobo

This directory contains manga files organized by series for easy access on Kobo e-readers:

```
{collection_root.name}/
  Manga Title 1/
    volume1.kepub.epub
    volume2.kepub.epub
  Manga Title 2/
    volume1.kepub.epub
    ...
```

## Upload Instructions

1. Connect your Kobo device to your computer via USB
2. Copy entire series folders to the 'Books' directory on your Kobo
3. Safely disconnect your device
4. The books will appear in your library automatically, organized by series

Generated by MangaBook on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    
    # Create README in collection root
    readme_path = collection_root / "README.md"
    try:
        with open(readme_path, 'w', encoding='utf-8') as f:
            f.write(readme_content)
        logger.info(f"Created README file: {readme_path}")
    except Exception as e:
        logger.error(f"Error creating README file: {e}")
    
    # Print summary
    if results["files"]:
        logger.info(f"Collected {len(results['files'])} Kobo files for '{manga_title}' in {kobo_dir}")
    else:
        logger.warning(f"No .kepub.epub files found for '{manga_title}'")
        results["success"] = False
        results["message"] = "No .kepub.epub files found"
    
    return results
