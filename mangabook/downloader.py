"""Manga downloading functionality.

This module provides functions for downloading manga chapters from MangaDex,
including chapter selection and organization.
"""

import os
import logging
import asyncio
import aiohttp
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Set, Tuple, Union
from tqdm import tqdm
import concurrent.futures
import json
from datetime import datetime

from .api import get_api, MangaDexAPI
from .utils import (
    ensure_directory,
    sanitize_filename,
    generate_manga_path,
    generate_volume_path,
    generate_chapter_path,
    generate_page_path,
    is_valid_image,
    retry,
    exception_handler,
    create_volume_manifest,
    save_manifest,
    load_manifest,
    update_manifest_chapter,
    update_manifest_page,
    validate_chapter_files
)
from .config import Config
from .parallel import DownloadManager, ApiCache, gather_with_concurrency
from .error import error_handler, ErrorCategory

# Set up logging
logger = logging.getLogger(__name__)

# Global API cache
api_cache = ApiCache()


class ChapterDownloader:
    """Handles downloading manga chapters."""
    
    def __init__(self, api: Optional[MangaDexAPI] = None,
                 output_dir: Optional[str] = None,
                 keep_raw: bool = False,
                 max_concurrent: int = 5,
                 use_cache: bool = True):
        """Initialize the chapter downloader.
        
        Args:
            api: Optional MangaDexAPI instance.
            output_dir: Directory to save downloaded files.
            keep_raw: Whether to keep raw downloaded files.
            max_concurrent: Maximum number of concurrent downloads.
            use_cache: Whether to use API response caching.
        """
        self.api = api
        self.output_dir = output_dir
        self.keep_raw = keep_raw
        self.session = None
        self.max_concurrent = max_concurrent
        self.use_cache = use_cache
        self.download_manager = DownloadManager(max_concurrent=max_concurrent)
    
    async def initialize(self) -> None:
        """Initialize the downloader with API and HTTP session."""
        if self.api is None:
            self.api = await get_api()
            # Mark that we created this API instance internally
            self._api_created_internally = True
        else:
            # API was passed in from outside
            self._api_created_internally = False
        
        if self.session is None:
            self.session = aiohttp.ClientSession()
        
        # If no output directory specified, get from config
        if not self.output_dir:
            config = Config()
            self.output_dir = config.get_output_dir()
    
    async def close(self) -> None:
        """Close the HTTP session and API resources."""
        if self.session:
            await self.session.close()
            self.session = None
            
        # Only close the API instance if we created it internally
        # and it's not a shared instance from outside
        if self.api and hasattr(self, '_api_created_internally') and self._api_created_internally:
            await self.api.close()
    
    async def get_best_scanlation_group(self, manga_id: str, language: str = "en") -> Optional[str]:
        """Choose the scanlation group with the highest follower count for a manga.
        
        Args:
            manga_id: MangaDex ID for the manga.
            language: Preferred language for translations.
        
        Returns:
            ID of the best scanlation group, or None if none found.
        """
        # Get all chapters
        chapters = await self.api.get_all_chapters(manga_id, language)
        if not chapters:
            logger.warning(f"No chapters found for manga {manga_id}")
            return None
        
        # Collect all unique scanlation group IDs
        group_ids = set()
        for chapter in chapters:
            for relationship in chapter.get("relationships", []):
                if relationship["type"] == "scanlation_group" and "id" in relationship:
                    group_ids.add(relationship["id"])
        if not group_ids:
            logger.warning(f"No scanlation groups found for manga {manga_id}")
            return None
        
        # Fetch follower counts for all groups
        # MangaDex API: /statistics/group/{uuid}
        group_follower_counts = {}
        for group_id in group_ids:
            try:
                stats = await self.api.get_group_statistics(group_id)
                follower_count = stats.get("statistics", {}).get(group_id, {}).get("follows", 0)
                group_follower_counts[group_id] = follower_count
            except Exception as e:
                logger.warning(f"Failed to fetch stats for group {group_id}: {e}")
                group_follower_counts[group_id] = 0
        if not group_follower_counts:
            logger.warning(f"No follower stats found for scanlation groups of manga {manga_id}")
            return None
        # Select group with highest follower count
        best_group = max(group_follower_counts.items(), key=lambda x: x[1])
        logger.info(f"Selected scanlation group {best_group[0]} with {best_group[1]} followers")
        return best_group[0]
    
    @retry(max_attempts=3, delay=2.0, backoff=2.0)
    async def _download_image(self, url: str, path: Path) -> bool:
        """Download a single image.
        
        Args:
            url: URL of the image to download.
            path: Path to save the image.
            
        Returns:
            bool: True if download was successful, False otherwise.
        """
        try:
            async with self.session.get(url) as response:
                if response.status != 200:
                    logger.error(f"Failed to download image: HTTP {response.status}")
                    return False
                
                # Ensure the directory exists
                path.parent.mkdir(parents=True, exist_ok=True)
                
                # Save the file
                with open(path, "wb") as f:
                    f.write(await response.read())
                
                return True
        except Exception as e:
            logger.error(f"Error downloading image: {e}")
            raise  # Let retry decorator handle it
    
    async def download_chapter_images(self, chapter_id: str, output_path: Union[str, Path],
                                     data_saver: bool = False, 
                                     check_local: bool = True,
                                     force_download: bool = False,
                                     manifest: Optional[Dict[str, Any]] = None) -> Tuple[int, int, Dict[str, Any]]:
        """Download all images for a chapter.
        
        Args:
            chapter_id: MangaDex ID for the chapter.
            output_path: Directory to save images.
            data_saver: Whether to use data-saver images.
            check_local: Whether to check for existing valid files.
            force_download: Whether to ignore local files and force download.
            manifest: Optional manifest to update.
            
        Returns:
            Tuple[int, int, Dict]: (Number of successful downloads, total images, download stats)
        """
        await self.initialize()
        
        # Track download statistics
        stats = {
            "downloaded": 0,
            "skipped": 0,
            "failed": 0,
            "retries": 0
        }
        
        # Get image URLs
        try:
            logger.debug(f"Getting images for chapter: {chapter_id}")
            image_data = await self.api.get_chapter_images(chapter_id, data_saver)
            logger.debug(f"Image data: {image_data}")
            
            if not image_data or not image_data.get("urls"):
                logger.error(f"No images found for chapter {chapter_id}")
                return 0, 0, stats
        except Exception as e:
            logger.error(f"Error getting images for chapter {chapter_id}: {e}")
            return 0, 0, stats
        
        output_dir = Path(output_path)
        ensure_directory(output_dir)
        
        urls = image_data["urls"]
        total = len(urls)
        successful = 0
        
        # Create progress bar
        progress = tqdm(total=total, desc=f"Downloading chapter {chapter_id}", unit="img")
        
        # Initialize chapter data for manifest
        chapter_data = {
            "id": chapter_id,
            "download_timestamp": datetime.now().isoformat(),
            "status": "incomplete",
            "pages": {}
        }
        
        # Download images
        tasks = []
        for i, url in enumerate(urls):
            page_number = i + 1
            
            # Determine file extension from URL if possible
            extension = "jpg" # Default
            if url and '.' in url.split('/')[-1]:
                possible_ext = url.split('.')[-1].lower()
                if possible_ext in ["jpg", "jpeg", "png", "gif", "webp"]:
                    extension = possible_ext
            
            # Create standardized filename with proper padding
            file_path = generate_page_path(output_dir, page_number, extension)
            
            # Create page data for manifest
            page_data = {
                "page_number": page_number,
                "file_path": str(file_path),
                "url": url,
                "status": "invalid"
            }
            
            # Check if we have a valid local file and should use it
            file_exists = file_path.exists()
            file_valid = False

            if file_exists:
                file_valid = is_valid_image(file_path)

            if file_exists and file_valid and check_local and not force_download:
                logger.debug(f"Skipping download of valid local file: {file_path}")
                page_data["status"] = "valid"
                page_data["skipped"] = True
                if manifest:
                    manifest = update_manifest_page(manifest, chapter_id, page_data)
                progress.update(1)
                successful += 1
                stats["skipped"] += 1
                continue
            
            # If force download or no valid local file, queue download
            tasks.append((url, file_path, page_number, page_data))

        # Process downloads with retry logic
        for url, file_path, page_number, page_data in tasks:
            retry_count = 0
            max_retries = 3
            success = False
            temp_file_path = file_path
            if not self.keep_raw:
                # Save to a temp file if not keeping raw
                temp_file_path = file_path.with_suffix(file_path.suffix + ".tmp")
            while not success and retry_count < max_retries:
                try:
                    result = await self._download_image(url, temp_file_path)
                    if result:
                        # Validate downloaded image
                        if is_valid_image(temp_file_path):
                            success = True
                            page_data["status"] = "valid"
                            stats["downloaded"] += 1
                            # Move temp file to final location if not keeping raw
                            if not self.keep_raw:
                                temp_file_path.replace(file_path)
                        else:
                            logger.warning(f"Downloaded file is not a valid image: {temp_file_path}")
                            page_data["status"] = "invalid"
                            retry_count += 1
                            stats["retries"] += 1
                            # Remove invalid temp file
                            if temp_file_path.exists():
                                temp_file_path.unlink()
                            await asyncio.sleep(5)
                            continue
                    else:
                        retry_count += 1
                        stats["retries"] += 1
                        # Remove failed temp file
                        if temp_file_path.exists():
                            temp_file_path.unlink()
                        await asyncio.sleep(5)  # Wait before retrying
                        continue
                except Exception as e:
                    logger.warning(f"Error downloading {url}: {e}")
                    retry_count += 1
                    stats["retries"] += 1
                    # Remove errored temp file
                    if temp_file_path.exists():
                        temp_file_path.unlink()
                    await asyncio.sleep(5)  # Wait before retrying
                    continue
                # Update manifest with the page status
                if manifest:
                    manifest = update_manifest_page(manifest, chapter_id, page_data)
                if success:
                    successful += 1
                else:
                    stats["failed"] += 1
                progress.update(1)
        progress.close()
        
        # Update chapter status in manifest
        if manifest:
            chapter_data["total_pages"] = total
            chapter_data["successful_pages"] = successful
            chapter_data["status"] = "complete" if successful == total else "incomplete"
            manifest = update_manifest_chapter(manifest, chapter_data)
        
        logger.info(f"Downloaded {successful}/{total} images for chapter {chapter_id}")
        return successful, total, stats
    
    async def download_volume(self, manga_id: str, manga_title: str, volume_number: str,
                             chapter_ids: Optional[Set[str]] = None, 
                             language: str = "en",
                             check_local: bool = True,
                             force_download: bool = False) -> Dict[str, Any]:
        """Download all chapters in a volume.
        
        Args:
            manga_id: MangaDex ID for the manga.
            manga_title: Title of the manga.
            volume_number: Volume number to download.
            chapter_ids: Optional set of specific chapter IDs to download.
            language: Preferred language for translations.
            check_local: Whether to check for existing valid files.
            force_download: Whether to ignore local files and force download.
            
        Returns:
            Dict with download results.
        """
        await self.initialize()
        
        # Statistics for tracking downloaded/skipped files
        download_stats = {
            "downloaded": 0,
            "skipped": 0,
            "failed": 0,
            "retries": 0
        }
        
        # Get volume information - use API cache if enabled
        cache_key = f"manga_volumes:{manga_id}:{language}"
        volumes = None
        
        if self.use_cache:
            volumes = api_cache.get(cache_key)
        
        if volumes is None:
            volumes = await self.api.get_manga_volumes(manga_id, language)
            if self.use_cache and volumes:
                api_cache.set(cache_key, volumes)
        
        # The API has already been modified to normalize "none" as "0" for ungrouped chapters
        # This check is kept for redundancy
        if volume_number == "0" and "0" not in volumes and "none" in volumes:
            # Use "none" as the key for ungrouped chapters in the API response
            volume_number = "none"
        
        if not volumes or volume_number not in volumes:
            logger.error(f"Volume {volume_number} not found for manga {manga_title}")
            return {
                "success": False,
                "message": f"Volume {volume_number} not found",
                "chapters_downloaded": 0,
                "total_chapters": 0,
                "stats": download_stats
            }
        
        volume_data = volumes[volume_number]
        chapters = volume_data.get("chapters", {})
        
        if not chapters:
            logger.error(f"No chapters found for volume {volume_number} of {manga_title}")
            return {
                "success": False,
                "message": "No chapters found",
                "chapters_downloaded": 0,
                "total_chapters": 0,
                "stats": download_stats
            }
        
        # Create paths
        manga_path = generate_manga_path(self.output_dir, manga_title)
        volume_path = generate_volume_path(manga_path, volume_number)
        
        # Check for existing manifest or create new one
        manifest = None
        if check_local and not force_download:
            manifest = load_manifest(volume_path)
            
            # If checking for updates, log the found manifest
            if manifest:
                logger.info(f"Found existing manifest for volume {volume_number}")
        
        # Create new manifest if none exists or force download
        if manifest is None or force_download:
            manifest = create_volume_manifest(manga_id, manga_title, volume_number)
            logger.info(f"Created new manifest for volume {volume_number}")
        
        # Filter chapters if specific IDs requested
        chapter_data = []
        for chapter_num, data in chapters.items():
            if chapter_ids is None or data["id"] in chapter_ids:
                chapter_data.append({
                    "id": data["id"],
                    "number": chapter_num,
                    "title": data.get("title", f"Chapter {chapter_num}")
                })
        
        # Sort chapters by number
        chapter_data.sort(key=lambda x: float(x["number"]) if x["number"].replace(".", "").isdigit() else float("inf"))
        
        total_chapters = len(chapter_data)
        
        # Create download jobs for the chapters
        chapter_jobs = []
        for chapter in chapter_data:
            chapter_id = chapter["id"]
            chapter_num = chapter["number"]
            chapter_title = sanitize_filename(chapter["title"])
            
            # Create chapter directory using standardized path
            chapter_dir = generate_chapter_path(volume_path, chapter_num, chapter_title)
            
            # Add to manifest if not already there
            chapter_manifest_data = {
                "id": chapter_id,
                "number": chapter_num,
                "title": chapter_title,
                "directory": str(chapter_dir),
                "download_timestamp": datetime.now().isoformat()
            }
            manifest = update_manifest_chapter(manifest, chapter_manifest_data)
            
            # Save manifest after each chapter update
            save_manifest(manifest, volume_path)
            
            job = {
                "id": chapter_id,
                "number": chapter_num,
                "title": chapter_title,
                "output_dir": str(chapter_dir)
            }
            chapter_jobs.append(job)
        
        # Use the download manager to download all chapters in parallel
        async def chapter_downloader(job):
            chapter_id = job["id"]
            output_dir = job["output_dir"]
            
            successful, total, stats = await self.download_chapter_images(
                chapter_id, 
                output_dir, 
                check_local=check_local,
                force_download=force_download,
                manifest=manifest
            )
            
            # Update global download stats
            for key in download_stats:
                if key in stats:
                    download_stats[key] += stats[key]
            
            # Save manifest after each chapter
            save_manifest(manifest, volume_path)
            
            return {
                "success": successful > 0,
                "chapter_id": chapter_id,
                "number": job["number"],
                "title": job["title"],
                "successful_images": successful,
                "total_images": total,
                "stats": stats
            }
        
        desc = f"Downloading {manga_title} vol.{volume_number}"
        download_results = await self.download_manager.download_chapters(
            chapter_jobs, 
            chapter_downloader,
            desc=desc
        )
        
        successful_chapters = download_results["completed"]
        
        # Final manifest save
        manifest["status"] = "complete" if successful_chapters == total_chapters else "incomplete"
        save_manifest(manifest, volume_path)
        
        logger.info(f"Downloaded {successful_chapters}/{total_chapters} chapters for volume {volume_number}")
        
        return {
            "success": successful_chapters > 0,
            "message": f"Downloaded {successful_chapters}/{total_chapters} chapters",
            "chapters_downloaded": successful_chapters,
            "total_chapters": total_chapters,
            "manga_path": str(manga_path),
            "volume_path": str(volume_path),
            "chapters": download_results["chapters"],
            "manifest": manifest,
            "stats": download_stats
        }


async def download_manga_volumes(manga_id: str, manga_title: str, volumes: List[str],
                               output_dir: Optional[str] = None, 
                               keep_raw: bool = False,
                               language: str = "en",
                               max_concurrent_volumes: int = 2,
                               max_concurrent_chapters: int = 5,
                               use_cache: bool = True,
                               check_local: bool = True,
                               force_download: bool = False) -> Dict[str, Any]:
    """Download multiple volumes of a manga.
    
    Args:
        manga_id: MangaDex ID for the manga.
        manga_title: Title of the manga.
        volumes: List of volume numbers to download.
        output_dir: Directory to save downloaded files.
        keep_raw: Whether to keep raw downloaded files.
        language: Preferred language for translations.
        max_concurrent_volumes: Maximum number of volumes to download concurrently.
        max_concurrent_chapters: Maximum number of chapters to download concurrently.
        use_cache: Whether to use API response caching.
        check_local: Whether to check for existing local files before downloading.
        force_download: Whether to force download even if local files exist.
        
    Returns:
        Dict with download results.
    """
    downloader = ChapterDownloader(
        output_dir=output_dir, 
        keep_raw=keep_raw,  # Use the function argument again
        max_concurrent=max_concurrent_chapters,
        use_cache=use_cache
    )
    
    try:
        await downloader.initialize()
        
        results = {
            "manga_id": manga_id,
            "manga_title": manga_title,
            "volumes": {},
            "successful": 0,
            "failed": 0,
            "total": len(volumes),
            "started_at": datetime.now().isoformat(),
            "completed_at": None,
            "stats": {
                "downloaded": 0,
                "skipped": 0,
                "failed": 0,
                "retries": 0
            }
        }
        
        # Function to download a single volume
        async def download_volume(volume_number):
            logger.info(f"Downloading volume {volume_number} of {manga_title}")
            
            result = await downloader.download_volume(
                manga_id=manga_id,
                manga_title=manga_title,
                volume_number=volume_number,
                language=language,
                check_local=check_local,
                force_download=force_download
            )
            
            return volume_number, result
        
        # Create tasks for parallel volume downloading
        volume_tasks = [download_volume(volume_number) for volume_number in volumes]
        
        # Use gather_with_concurrency to limit parallel volume downloads
        volume_results = await gather_with_concurrency(
            max_concurrent_volumes, 
            *volume_tasks,
            show_progress=True,
            desc=f"Downloading volumes of {manga_title}",
            unit="vol",
            total=len(volumes)
        )
        
        # Process results
        for volume_number, result in volume_results:
            results["volumes"][volume_number] = result
            
            if result["success"]:
                results["successful"] += 1
            else:
                results["failed"] += 1
            
            # Aggregate download statistics
            if "stats" in result:
                for key, value in result["stats"].items():
                    if key in results["stats"]:
                        results["stats"][key] += value
        
        results["completed_at"] = datetime.now().isoformat()
        
        return results
    
    finally:
        await downloader.close()
