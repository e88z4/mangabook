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
    retry,
    exception_handler
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
        
        if self.session is None:
            self.session = aiohttp.ClientSession()
        
        # If no output directory specified, get from config
        if not self.output_dir:
            config = Config()
            self.output_dir = config.get_output_dir()
    
    async def close(self) -> None:
        """Close the HTTP session."""
        if self.session:
            await self.session.close()
            self.session = None
    
    async def get_best_scanlation_group(self, manga_id: str, language: str = "en") -> Optional[str]:
        """Choose the best scanlation group for a manga.
        
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
        
        # Count occurrences of each group
        group_counts = {}
        for chapter in chapters:
            for relationship in chapter.get("relationships", []):
                if relationship["type"] == "scanlation_group" and "id" in relationship:
                    group_id = relationship["id"]
                    group_counts[group_id] = group_counts.get(group_id, 0) + 1
        
        if not group_counts:
            logger.warning(f"No scanlation groups found for manga {manga_id}")
            return None
        
        # Find the most frequent group
        best_group = max(group_counts.items(), key=lambda x: x[1])
        logger.info(f"Selected scanlation group {best_group[0]} with {best_group[1]} chapters")
        
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
                                     data_saver: bool = False) -> Tuple[int, int]:
        """Download all images for a chapter.
        
        Args:
            chapter_id: MangaDex ID for the chapter.
            output_path: Directory to save images.
            data_saver: Whether to use data-saver images.
            
        Returns:
            Tuple[int, int]: (Number of successful downloads, total images)
        """
        await self.initialize()
        
        # Get image URLs
        image_data = await self.api.get_chapter_images(chapter_id, data_saver)
        
        if not image_data or not image_data.get("urls"):
            logger.error(f"No images found for chapter {chapter_id}")
            return 0, 0
        
        output_dir = Path(output_path)
        ensure_directory(output_dir)
        
        urls = image_data["urls"]
        total = len(urls)
        successful = 0
        
        # Create progress bar
        progress = tqdm(total=total, desc=f"Downloading chapter {chapter_id}", unit="img")
        
        # Download images
        tasks = []
        for i, url in enumerate(urls):
            # Create filename with leading zeros for proper sorting
            filename = f"{i+1:03d}.jpg"  # Assume JPG, we'll handle format detection later
            path = output_dir / filename
            
            tasks.append(self._download_image(url, path))
        
        # Use gather_with_concurrency for parallel downloads
        results = await gather_with_concurrency(self.max_concurrent, *tasks, 
                                            show_progress=True, 
                                            desc=f"Downloading chapter {chapter_id}", 
                                            unit="img",
                                            total=len(tasks))
        
        successful = sum(1 for result in results if result)
        
        progress.close()
        
        logger.info(f"Downloaded {successful}/{total} images for chapter {chapter_id}")
        return successful, total
    
    async def download_volume(self, manga_id: str, manga_title: str, volume_number: str,
                             chapter_ids: Optional[Set[str]] = None, 
                             language: str = "en") -> Dict[str, Any]:
        """Download all chapters in a volume.
        
        Args:
            manga_id: MangaDex ID for the manga.
            manga_title: Title of the manga.
            volume_number: Volume number to download.
            chapter_ids: Optional set of specific chapter IDs to download.
            language: Preferred language for translations.
            
        Returns:
            Dict with download results.
        """
        await self.initialize()
        
        # Get volume information - use API cache if enabled
        cache_key = f"manga_volumes:{manga_id}:{language}"
        volumes = None
        
        if self.use_cache:
            volumes = api_cache.get(cache_key)
        
        if volumes is None:
            volumes = await self.api.get_manga_volumes(manga_id, language)
            if self.use_cache and volumes:
                api_cache.set(cache_key, volumes)
        
        if not volumes or volume_number not in volumes:
            logger.error(f"Volume {volume_number} not found for manga {manga_title}")
            return {
                "success": False,
                "message": f"Volume {volume_number} not found",
                "chapters_downloaded": 0,
                "total_chapters": 0
            }
        
        volume_data = volumes[volume_number]
        chapters = volume_data.get("chapters", {})
        
        if not chapters:
            logger.error(f"No chapters found for volume {volume_number} of {manga_title}")
            return {
                "success": False,
                "message": "No chapters found",
                "chapters_downloaded": 0,
                "total_chapters": 0
            }
        
        # Create paths
        manga_path = generate_manga_path(self.output_dir, manga_title)
        volume_path = generate_volume_path(manga_path, volume_number)
        
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
            
            # Create chapter directory
            chapter_dir = volume_path / f"chapter_{chapter_num}_{chapter_title}"
            ensure_directory(chapter_dir)
            
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
            
            successful, total = await self.download_chapter_images(chapter_id, output_dir)
            
            return {
                "success": successful > 0,
                "chapter_id": chapter_id,
                "number": job["number"],
                "title": job["title"],
                "successful_images": successful,
                "total_images": total
            }
        
        desc = f"Downloading {manga_title} vol.{volume_number}"
        download_results = await self.download_manager.download_chapters(
            chapter_jobs, 
            chapter_downloader,
            desc=desc
        )
        
        successful_chapters = download_results["completed"]
        
        logger.info(f"Downloaded {successful_chapters}/{total_chapters} chapters for volume {volume_number}")
        
        return {
            "success": successful_chapters > 0,
            "message": f"Downloaded {successful_chapters}/{total_chapters} chapters",
            "chapters_downloaded": successful_chapters,
            "total_chapters": total_chapters,
            "manga_path": str(manga_path),
            "volume_path": str(volume_path),
            "chapters": download_results["chapters"]
        }


async def download_manga_volumes(manga_id: str, manga_title: str, volumes: List[str],
                               output_dir: Optional[str] = None, 
                               keep_raw: bool = False,
                               language: str = "en",
                               max_concurrent_volumes: int = 2,
                               max_concurrent_chapters: int = 5,
                               use_cache: bool = True) -> Dict[str, Any]:
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
        
    Returns:
        Dict with download results.
    """
    downloader = ChapterDownloader(
        output_dir=output_dir, 
        keep_raw=keep_raw,
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
            "completed_at": None
        }
        
        # Function to download a single volume
        async def download_volume(volume_number):
            logger.info(f"Downloading volume {volume_number} of {manga_title}")
            
            result = await downloader.download_volume(
                manga_id=manga_id,
                manga_title=manga_title,
                volume_number=volume_number,
                language=language
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
        
        results["completed_at"] = datetime.now().isoformat()
        
        return results
    
    finally:
        await downloader.close()
