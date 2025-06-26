"""Batch processing for manga downloads.

This module provides functionality for batch processing of manga downloads.
"""

import os
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Set, Union, Tuple
from datetime import datetime
import json
import time

from .api import get_api
from .downloader import ChapterDownloader, download_manga_volumes
from .workflow import process_manga
from .config import Config
from .history import manga_history
from .ui import print_info, print_success, print_warning, print_error, print_manga_title, print_header

# Set up logging
logger = logging.getLogger(__name__)


class DownloadQueue:
    """Queue for manga downloads."""
    
    def __init__(self, queue_file: Optional[Union[str, Path]] = None):
        """Initialize download queue.
        
        Args:
            queue_file: Path to queue file. If None, use default.
        """
        self.config = Config()
        
        if queue_file is None:
            queue_file = Path(self.config.get_config_dir()) / "download_queue.json"
        else:
            queue_file = Path(queue_file)
        
        self.queue_file = queue_file
        self.queue_data = self._load_queue()
        
        # Initialize current job
        self.current_job = None
    
    def _load_queue(self) -> Dict[str, Any]:
        """Load queue from file.
        
        Returns:
            Dict with queue data.
        """
        if not self.queue_file.exists():
            return {
                "queue": [],
                "history": [],
                "last_updated": datetime.now().isoformat()
            }
        
        try:
            with open(self.queue_file, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load queue: {e}")
            return {
                "queue": [],
                "history": [],
                "last_updated": datetime.now().isoformat()
            }
    
    def _save_queue(self) -> None:
        """Save queue to file."""
        try:
            with open(self.queue_file, "w") as f:
                json.dump(self.queue_data, f, indent=2)
                
            # Set secure permissions
            os.chmod(self.queue_file, 0o600)
            
        except Exception as e:
            logger.error(f"Failed to save queue: {e}")
    
    def add_job(self, manga_id: str, manga_title: str, volumes: List[str],
               output_dir: Optional[str] = None, keep_raw: bool = False,
               quality: int = 85, kobo: bool = True, 
               priority: int = 0) -> Dict[str, Any]:
        """Add a job to the queue.
        
        Args:
            manga_id: MangaDex ID of the manga.
            manga_title: Title of the manga.
            volumes: List of volume numbers to download.
            output_dir: Output directory.
            keep_raw: Whether to keep raw downloaded files.
            quality: Image quality (1-100).
            kobo: Whether to create Kobo-compatible EPUB.
            priority: Job priority (higher = higher priority).
            
        Returns:
            Dict with job data.
        """
        # Create job
        job = {
            "id": f"{manga_id}_{int(time.time())}",
            "manga_id": manga_id,
            "manga_title": manga_title,
            "volumes": volumes,
            "output_dir": output_dir or self.config.get_output_dir(),
            "keep_raw": keep_raw,
            "quality": quality,
            "kobo": kobo,
            "priority": priority,
            "status": "pending",
            "added_at": datetime.now().isoformat(),
            "started_at": None,
            "completed_at": None,
            "result": None
        }
        
        # Add to queue
        self.queue_data["queue"].append(job)
        self.queue_data["last_updated"] = datetime.now().isoformat()
        
        # Sort queue by priority
        self.queue_data["queue"].sort(key=lambda x: x["priority"], reverse=True)
        
        # Save queue
        self._save_queue()
        
        return job
    
    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get a job from the queue.
        
        Args:
            job_id: Job ID.
            
        Returns:
            Dict with job data or None if not found.
        """
        # Check current job
        if self.current_job and self.current_job["id"] == job_id:
            return self.current_job
        
        # Check queue
        for job in self.queue_data["queue"]:
            if job["id"] == job_id:
                return job
        
        # Check history
        for job in self.queue_data["history"]:
            if job["id"] == job_id:
                return job
                
        return None
    
    def get_queue(self) -> List[Dict[str, Any]]:
        """Get the queue.
        
        Returns:
            List of jobs in the queue.
        """
        return self.queue_data["queue"].copy()
    
    def get_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get the job history.
        
        Args:
            limit: Maximum number of jobs to return.
            
        Returns:
            List of completed jobs.
        """
        return self.queue_data["history"][:limit]
    
    def remove_job(self, job_id: str) -> bool:
        """Remove a job from the queue.
        
        Args:
            job_id: Job ID.
            
        Returns:
            Whether the job was removed.
        """
        # Find job
        for i, job in enumerate(self.queue_data["queue"]):
            if job["id"] == job_id:
                # Remove job
                del self.queue_data["queue"][i]
                self.queue_data["last_updated"] = datetime.now().isoformat()
                self._save_queue()
                return True
                
        return False
    
    def clear_queue(self) -> int:
        """Clear the queue.
        
        Returns:
            Number of jobs cleared.
        """
        count = len(self.queue_data["queue"])
        self.queue_data["queue"] = []
        self.queue_data["last_updated"] = datetime.now().isoformat()
        self._save_queue()
        return count
    
    def clear_history(self) -> int:
        """Clear the job history.
        
        Returns:
            Number of jobs cleared.
        """
        count = len(self.queue_data["history"])
        self.queue_data["history"] = []
        self.queue_data["last_updated"] = datetime.now().isoformat()
        self._save_queue()
        return count
    
    async def process_next_job(self) -> Optional[Dict[str, Any]]:
        """Process the next job in the queue.
        
        Returns:
            Dict with job result or None if queue is empty.
        """
        if not self.queue_data["queue"]:
            return None
        
        # Get next job
        job = self.queue_data["queue"].pop(0)
        self.current_job = job
        
        # Update job status
        job["status"] = "running"
        job["started_at"] = datetime.now().isoformat()
        self._save_queue()
        
        try:
            # Process manga
            print_header(f"Processing: {job['manga_title']}", width=60)
            print_info(f"Job ID: {job['id']}")
            print_info(f"Volumes: {', '.join(job['volumes'])}")
            
            result = await process_manga(
                manga_id=job["manga_id"],
                manga_title=job["manga_title"],
                volumes=job["volumes"],
                output_dir=job["output_dir"],
                keep_raw=job["keep_raw"],
                quality=job["quality"],
                kobo=job["kobo"],
                validate=True
            )
            
            # Update job with result
            job["status"] = "completed" if result["successful"] > 0 else "failed"
            job["completed_at"] = datetime.now().isoformat()
            job["result"] = result
            
            # Record in history
            if result["successful"] > 0:
                manga_history.record_manga_download(
                    manga_id=job["manga_id"],
                    manga_title=job["manga_title"],
                    volumes=job["volumes"],
                    success=True,
                    metadata={
                        "job_id": job["id"],
                        "epub_files": result.get("epub_files", [])
                    }
                )
                
                print_success(f"Job completed: {result['successful']}/{len(job['volumes'])} volumes processed successfully")
            else:
                manga_history.record_manga_download(
                    manga_id=job["manga_id"],
                    manga_title=job["manga_title"],
                    volumes=job["volumes"],
                    success=False,
                    metadata={
                        "job_id": job["id"],
                        "error": result.get("error", "Unknown error")
                    }
                )
                
                print_error(f"Job failed: {result.get('error', 'Unknown error')}")
            
            # Add to history
            self.queue_data["history"].insert(0, job)
            if len(self.queue_data["history"]) > 100:  # Limit history
                self.queue_data["history"] = self.queue_data["history"][:100]
                
            self._save_queue()
            
            return job
            
        except Exception as e:
            logger.error(f"Failed to process job: {e}")
            
            # Update job with error
            job["status"] = "failed"
            job["completed_at"] = datetime.now().isoformat()
            job["result"] = {"error": str(e)}
            
            # Add to history
            self.queue_data["history"].insert(0, job)
            if len(self.queue_data["history"]) > 100:
                self.queue_data["history"] = self.queue_data["history"][:100]
                
            self._save_queue()
            
            return job
        
        finally:
            self.current_job = None
    
    async def process_all(self) -> List[Dict[str, Any]]:
        """Process all jobs in the queue.
        
        Returns:
            List of job results.
        """
        results = []
        
        while self.queue_data["queue"]:
            result = await self.process_next_job()
            if result:
                results.append(result)
        
        return results


# Global queue instance
download_queue = DownloadQueue()


async def batch_download(manga_ids: List[str], output_dir: Optional[str] = None,
                        volumes: Optional[Dict[str, List[str]]] = None,
                        keep_raw: bool = False, quality: int = 85,
                        kobo: bool = True) -> Dict[str, Any]:
    """Download multiple manga.
    
    Args:
        manga_ids: List of MangaDex IDs.
        output_dir: Output directory.
        volumes: Dict mapping manga IDs to volume lists. If None, download all volumes.
        keep_raw: Whether to keep raw downloaded files.
        quality: Image quality (1-100).
        kobo: Whether to create Kobo-compatible EPUB.
        
    Returns:
        Dict with download results.
    """
    # Get API
    api = await get_api()
    
    results = {
        "successful": 0,
        "failed": 0,
        "total": len(manga_ids),
        "manga": {}
    }
    
    print_header(f"Batch Download ({len(manga_ids)} manga)", width=60)
    
    for manga_id in manga_ids:
        try:
            # Get manga details
            manga = await api.get_manga(manga_id)
            if not manga:
                print_error(f"Failed to get manga {manga_id}")
                results["failed"] += 1
                results["manga"][manga_id] = {"success": False, "error": "Manga not found"}
                continue
            
            # Get manga title
            title = manga["attributes"].get("title", {}).get("en") or list(manga["attributes"].get("title", {}).values())[0]
            print_manga_title(title)
            
            # Get volumes to download
            manga_volumes = volumes.get(manga_id) if volumes else None
            
            if not manga_volumes:
                # Get all volumes
                all_volumes = await api.get_manga_volumes(manga_id)
                manga_volumes = list(all_volumes.keys())
            
            print_info(f"Downloading volumes: {', '.join(manga_volumes)}")
            
            # Add to download queue
            job = download_queue.add_job(
                manga_id=manga_id,
                manga_title=title,
                volumes=manga_volumes,
                output_dir=output_dir,
                keep_raw=keep_raw,
                quality=quality,
                kobo=kobo
            )
            
            results["manga"][manga_id] = {
                "success": True,
                "job_id": job["id"],
                "volumes": manga_volumes
            }
            
            results["successful"] += 1
            
        except Exception as e:
            logger.error(f"Failed to add manga {manga_id} to queue: {e}")
            results["failed"] += 1
            results["manga"][manga_id] = {"success": False, "error": str(e)}
    
    print_info(f"Added {results['successful']} manga to download queue")
    print_info(f"Use 'mangabook queue process' to start processing the queue")
    
    return results
