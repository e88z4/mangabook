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
from .utils import sanitize_filename, ensure_directory, generate_manga_path, generate_volume_path, load_manifest
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
                      force_overwrite: bool = False, use_official_covers: bool = True, 
                      create_kobo_collection: bool = True,
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
        force_overwrite: Whether to overwrite existing files (useful for updating ongoing manga).
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
        
        # Create the manga-collection directory early to ensure it exists
        manga_collection_dir = Path(output_dir) / "manga-collection"
        ensure_directory(manga_collection_dir)
        
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
        if force_overwrite:
            print_info("Force overwrite: Enabled (will overwrite existing files)")
        
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
                
                # Track if any chapter failed image processing
                chapter_processing_failed = False
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
                        results["warnings"].append(f"Failed to process images in {chapter_dir.name} (volume {volume_number})")
                        chapter_processing_failed = True
                        continue
                    # Collect all processed images for this chapter
                    chapter_image_map[chapter_dir.name] = []
                    for source_file, proc_files in processed.items():
                        chapter_image_map[chapter_dir.name].extend(proc_files)
                # Sort chapters by name (which should be in reading order)
                sorted_chapters = sorted(chapter_image_map.items())

                # If any chapter failed, mark the volume as failed and skip EPUB generation
                if chapter_processing_failed:
                    print_error(f"Failed to process images for one or more chapters in volume {volume_number}. Skipping EPUB generation.")
                    results["failed"] += 1
                    results["volumes"][volume_number]["error"] = "Image processing failed for one or more chapters."
                    progress.update(1)
                    continue
                
                # Step 3.3: Generate EPUB and KEPUB files
                try:
                    print_info(f"Generating EPUB/KEPUB files for volume {volume_number}...")
                    
                    # Get chapter info from manifest for metadata
                    volume_manifest = load_manifest(volume_path)
                    chapter_data = volume_manifest.get("chapters", {})
                    
                    # Prepare images in reading order
                    all_images = []
                    for chapter_name, images in sorted_chapters:
                        all_images.extend(sorted(images))
                    
                    if not all_images:
                        print_error(f"No valid images found for volume {volume_number}")
                        results["failed"] += 1
                        results["volumes"][volume_number]["error"] = "No valid images found"
                        progress.update(1)
                        continue
                    
                    # Format volume number with 3-digit zero-padding for filenames
                    try:
                        vol_num_float = float(volume_number)
                        if vol_num_float.is_integer():
                            vol_num_fmt = f"{int(vol_num_float):03d}"
                        else:
                            int_part = int(vol_num_float)
                            vol_num_fmt = f"{int_part:03d}{str(vol_num_float)[str(vol_num_float).find('.'):]}"
                    except ValueError:
                        vol_num_fmt = str(volume_number)

                    # Create standard EPUB
                    epub_filename = f"{sanitize_filename(manga_title)}_vol_{vol_num_fmt}.epub"
                    
                    # Use manga_collection_dir for the epub_path
                    epub_path = manga_collection_dir / epub_filename
                    
                    epub_builder = EnhancedEPUBBuilder(
                        title=f"{manga_title} - Volume {volume_number}",
                        author=f"MangaDex ID: {manga_id}",
                        language=language,
                        identifier=f"mangadex:{manga_id}:vol:{volume_number}",
                        output_dir=manga_collection_dir  # Pass the manga collection directory as output_dir
                    )
                    
                    # Add all images to EPUB
                    for img_path in all_images:
                        epub_builder.add_image(img_path)
                    
                    # Write EPUB file
                    epub_output = epub_builder.write(str(epub_path), force_overwrite=force_overwrite)
                    results["epub_files"].append(epub_output)
                    
                    # Create Kobo-compatible KEPUB if requested
                    if kobo:
                        kepub_filename = f"{sanitize_filename(manga_title)}_vol_{vol_num_fmt}.kepub.epub"
                        # Use manga_collection_dir for kepub_path for consistency with output_dir
                        kepub_path = manga_collection_dir / kepub_filename
                        
                        kepub_builder = EnhancedKepubBuilder(
                            title=f"{manga_title} - Volume {volume_number}",
                            author=f"MangaDex ID: {manga_id}",
                            language=language,
                            identifier=f"mangadex:{manga_id}:vol:{volume_number}",
                            output_dir=manga_collection_dir  # Pass the manga collection directory as output_dir
                        )
                        
                        # Add all images to KEPUB
                        for img_path in all_images:
                            kepub_builder.add_image(img_path)
                        
                        # Write KEPUB file
                        kepub_output = kepub_builder.write(str(kepub_path), force_overwrite=force_overwrite)
                        results["epub_files"].append(kepub_output)
                        
                        # If collection folder specified, create a more readable structure
                        if create_kobo_collection:
                            # Use specified collection_root or default to {output_dir}/manga-collection
                            root_dir = Path(collection_root) if collection_root else Path(output_dir) / "manga-collection"
                            kobo_dir = root_dir / sanitize_filename(manga_title)
                            
                            # Create parent directories
                            ensure_directory(kobo_dir)
                            
                            # Create a readable filename for the collection
                            readable_name = manga_title.replace('_', ' ')
                            collection_filename = f"{readable_name} - Volume {vol_num_fmt}.kepub.epub"
                            collection_path = kobo_dir / collection_filename
                            
                            # Only need to copy the file if the paths are different
                            if str(kepub_path) != str(collection_path):
                                shutil.copy2(kepub_path, collection_path)
                                logger.info(f"Copied KEPUB to collection: {collection_path}")
                                # Add this file to the results too
                                results["epub_files"].append(str(collection_path))
                    
                    print_success(f"Generated EPUB files for volume {volume_number}")
                    
                except Exception as epub_error:
                    error = error_handler.handle(epub_error, category=ErrorCategory.CONVERSION)
                    error_handler.display_error(error)
                    logger.error(f"Error generating EPUB for volume {volume_number}: {epub_error}")
                    results["volumes"][volume_number]["error"] = f"EPUB generation failed: {str(epub_error)}"
                    results["failed"] += 1
                    progress.update(1)
                    continue
            
            except Exception as volume_error:
                error = error_handler.handle(volume_error, category=ErrorCategory.UNEXPECTED)
                error_handler.display_error(error)
                logger.error(f"Error processing volume {volume_number}: {volume_error}")
                results["volumes"][volume_number]["error"] = str(volume_error)
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
            
        # Note: Don't try to access exception variables here
    

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
