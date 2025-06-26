"""Parallel processing utilities for MangaBook.

This module provides utilities for parallel processing of downloads and image processing.
"""

import asyncio
import logging
from typing import List, Dict, Any, Callable, TypeVar, Coroutine, Optional, Set, Union
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import functools
import time
import io
import sys
from pathlib import Path
import traceback
from tqdm.asyncio import tqdm as async_tqdm

from .error import error_handler, ErrorCategory

# Type variables for generic functions
T = TypeVar('T')
R = TypeVar('R')

# Set up logging
logger = logging.getLogger(__name__)


async def gather_with_concurrency(n: int, *coros, show_progress: bool = False,
                                desc: str = "Processing", unit: str = "item",
                                total: Optional[int] = None) -> List[Any]:
    """Run coroutines with a concurrency limit.
    
    Args:
        n: Maximum number of concurrent tasks.
        *coros: Coroutines to run.
        show_progress: Whether to show a progress bar.
        desc: Description for the progress bar.
        unit: Unit for the progress bar.
        total: Total number of items for the progress bar.
        
    Returns:
        List of results from the coroutines.
    """
    semaphore = asyncio.Semaphore(n)
    
    async def sem_coro(coro):
        async with semaphore:
            return await coro
    
    if not coros:
        return []
    
    if show_progress:
        if total is None:
            total = len(coros)
        return await async_tqdm.gather(
            *(sem_coro(c) for c in coros),
            desc=desc,
            unit=unit,
            total=total
        )
    else:
        return await asyncio.gather(*(sem_coro(c) for c in coros))


async def run_in_process_pool(func: Callable[..., R], *args, **kwargs) -> R:
    """Run a CPU-bound function in a process pool.
    
    Args:
        func: Function to run.
        *args: Arguments to pass to the function.
        **kwargs: Keyword arguments to pass to the function.
        
    Returns:
        Result of the function.
    """
    loop = asyncio.get_event_loop()
    with ProcessPoolExecutor() as pool:
        return await loop.run_in_executor(
            pool, functools.partial(func, *args, **kwargs)
        )


async def run_in_thread_pool(func: Callable[..., R], *args, **kwargs) -> R:
    """Run an IO-bound function in a thread pool.
    
    Args:
        func: Function to run.
        *args: Arguments to pass to the function.
        **kwargs: Keyword arguments to pass to the function.
        
    Returns:
        Result of the function.
    """
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as pool:
        return await loop.run_in_executor(
            pool, functools.partial(func, *args, **kwargs)
        )


class DownloadManager:
    """Manager for parallel downloading of manga chapters."""
    
    def __init__(self, max_concurrent: int = 5, timeout: int = 30):
        """Initialize download manager.
        
        Args:
            max_concurrent: Maximum number of concurrent downloads.
            timeout: Timeout for downloads in seconds.
        """
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self.results = {}
        self.in_progress = set()
        self.completed = set()
        self.failed = set()
    
    async def download_chapters(self, chapter_jobs: List[Dict[str, Any]],
                             downloader_func: Callable[[Dict[str, Any]], Coroutine[Any, Any, Dict[str, Any]]],
                             desc: str = "Downloading chapters") -> Dict[str, Any]:
        """Download multiple chapters in parallel.
        
        Args:
            chapter_jobs: List of chapter download jobs.
            downloader_func: Function to download a single chapter.
            desc: Description for the progress bar.
            
        Returns:
            Dict with download results.
        """
        if not chapter_jobs:
            return {
                "success": True,
                "chapters": {},
                "completed": 0,
                "failed": 0,
                "total": 0
            }
        
        # Create tasks for each chapter
        tasks = []
        for job in chapter_jobs:
            task = self._download_chapter(job, downloader_func)
            tasks.append(task)
        
        # Run tasks with concurrency limit
        results = await gather_with_concurrency(
            self.max_concurrent,
            *tasks,
            show_progress=True,
            desc=desc,
            unit="ch",
            total=len(tasks)
        )
        
        # Process results
        chapters_results = {}
        completed = 0
        failed = 0
        
        for job, result in zip(chapter_jobs, results):
            chapter_id = job.get("id", "unknown")
            chapters_results[chapter_id] = result
            
            if result.get("success", False):
                completed += 1
                self.completed.add(chapter_id)
            else:
                failed += 1
                self.failed.add(chapter_id)
        
        return {
            "success": failed == 0,
            "chapters": chapters_results,
            "completed": completed,
            "failed": failed,
            "total": len(chapter_jobs)
        }
    
    async def _download_chapter(self, job: Dict[str, Any],
                             downloader_func: Callable[[Dict[str, Any]], Coroutine[Any, Any, Dict[str, Any]]]) -> Dict[str, Any]:
        """Download a single chapter with timeout and error handling.
        
        Args:
            job: Chapter download job.
            downloader_func: Function to download the chapter.
            
        Returns:
            Dict with download result.
        """
        chapter_id = job.get("id", "unknown")
        self.in_progress.add(chapter_id)
        
        try:
            # Run download with timeout
            result = await asyncio.wait_for(
                downloader_func(job),
                timeout=self.timeout
            )
            
            self.results[chapter_id] = result
            return result
            
        except asyncio.TimeoutError:
            logger.error(f"Download timeout for chapter {chapter_id}")
            
            error = {
                "success": False,
                "error": "timeout",
                "message": f"Download timed out after {self.timeout} seconds"
            }
            
            self.results[chapter_id] = error
            return error
            
        except Exception as e:
            logger.error(f"Error downloading chapter {chapter_id}: {e}")
            
            error = {
                "success": False,
                "error": "exception",
                "message": str(e)
            }
            
            self.results[chapter_id] = error
            return error
            
        finally:
            self.in_progress.remove(chapter_id)
    
    def get_stats(self) -> Dict[str, int]:
        """Get download statistics.
        
        Returns:
            Dict with download statistics.
        """
        return {
            "completed": len(self.completed),
            "failed": len(self.failed),
            "in_progress": len(self.in_progress),
            "total": len(self.completed) + len(self.failed) + len(self.in_progress)
        }


class ProcessingTask:
    """Task for image processing."""
    
    def __init__(self, task_id: str, task_type: str, priority: int = 0, 
               data: Optional[Dict[str, Any]] = None):
        """Initialize processing task.
        
        Args:
            task_id: Task ID.
            task_type: Type of task.
            priority: Priority of task (higher values = higher priority).
            data: Task data.
        """
        self.id = task_id
        self.type = task_type
        self.priority = priority
        self.data = data or {}
        self.result = None
        self.error = None
        self.started_at = None
        self.completed_at = None
        self.status = "pending"  # pending, running, completed, failed
    
    def __lt__(self, other):
        """Compare tasks by priority."""
        if not isinstance(other, ProcessingTask):
            return NotImplemented
        return self.priority > other.priority  # Higher priority first
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert task to dict.
        
        Returns:
            Dict representation of the task.
        """
        return {
            "id": self.id,
            "type": self.type,
            "priority": self.priority,
            "data": self.data,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "status": self.status
        }


class ProcessingQueue:
    """Queue for processing tasks."""
    
    def __init__(self, max_workers: int = 4):
        """Initialize processing queue.
        
        Args:
            max_workers: Maximum number of concurrent workers.
        """
        self.queue = asyncio.PriorityQueue()
        self.max_workers = max_workers
        self.tasks = {}  # task_id -> task
        self.workers = []
        self.running = False
        self.semaphore = asyncio.Semaphore(max_workers)
    
    def add_task(self, task: ProcessingTask) -> None:
        """Add a task to the queue.
        
        Args:
            task: Task to add.
        """
        self.tasks[task.id] = task
        self.queue.put_nowait((task.priority, task))
    
    async def process(self, processor_func: Callable[[Dict[str, Any]], Coroutine[Any, Any, Dict[str, Any]]]) -> None:
        """Process tasks in the queue.
        
        Args:
            processor_func: Function to process tasks.
        """
        self.running = True
        
        try:
            while self.running and not self.queue.empty():
                # Get task from queue
                _, task = await self.queue.get()
                
                # Process task
                worker = self._process_task(task, processor_func)
                self.workers.append(worker)
                
                # Release worker when done
                worker.add_done_callback(self._worker_done)
            
            # Wait for all workers to complete
            if self.workers:
                await asyncio.gather(*self.workers)
                
        except Exception as e:
            logger.error(f"Error in processing queue: {e}")
            error_handler.handle(e, category=ErrorCategory.UNEXPECTED)
            
        finally:
            self.running = False
    
    def _worker_done(self, future):
        """Callback when a worker is done."""
        if future in self.workers:
            self.workers.remove(future)
    
    async def _process_task(self, task: ProcessingTask, 
                         processor_func: Callable[[Dict[str, Any]], Coroutine[Any, Any, Dict[str, Any]]]) -> None:
        """Process a task.
        
        Args:
            task: Task to process.
            processor_func: Function to process the task.
        """
        async with self.semaphore:
            # Update task status
            task.status = "running"
            task.started_at = time.time()
            
            try:
                # Process task
                result = await processor_func(task.data)
                
                # Update task with result
                task.result = result
                task.status = "completed"
                
            except Exception as e:
                # Handle error
                logger.error(f"Error processing task {task.id}: {e}")
                
                task.error = str(e)
                task.status = "failed"
                
                # Add task to error handler
                error_handler.handle(e, category=ErrorCategory.CONVERSION)
                
            finally:
                # Update task completion time
                task.completed_at = time.time()
                
                # Mark task as done in queue
                self.queue.task_done()
    
    def get_task(self, task_id: str) -> Optional[ProcessingTask]:
        """Get a task by ID.
        
        Args:
            task_id: Task ID.
            
        Returns:
            Task or None if not found.
        """
        return self.tasks.get(task_id)
    
    def get_tasks_by_status(self, status: str) -> List[ProcessingTask]:
        """Get tasks by status.
        
        Args:
            status: Task status.
            
        Returns:
            List of tasks with the given status.
        """
        return [task for task in self.tasks.values() if task.status == status]
    
    def get_stats(self) -> Dict[str, int]:
        """Get queue statistics.
        
        Returns:
            Dict with queue statistics.
        """
        stats = {
            "total": len(self.tasks),
            "pending": 0,
            "running": 0,
            "completed": 0,
            "failed": 0
        }
        
        for task in self.tasks.values():
            stats[task.status] = stats.get(task.status, 0) + 1
        
        return stats
    
    def stop(self) -> None:
        """Stop processing queue."""
        self.running = False


# Cache for API responses
class ApiCache:
    """Cache for API responses."""
    
    def __init__(self, cache_dir: Optional[Union[str, Path]] = None, max_age: int = 3600):
        """Initialize API cache.
        
        Args:
            cache_dir: Directory for cache files. If None, a directory will be created
                      in the user's cache directory.
            max_age: Maximum age of cache entries in seconds (default: 1 hour).
        """
        if cache_dir is None:
            # Use platform-specific cache directory
            from pathlib import Path
            import os
            
            if sys.platform == "win32":
                cache_base = Path(os.environ.get("LOCALAPPDATA", "~"))
            elif sys.platform == "darwin":
                cache_base = Path("~/Library/Caches")
            else:  # Linux and others
                cache_base = Path(os.environ.get("XDG_CACHE_HOME", "~/.cache"))
                
            cache_dir = cache_base / "mangabook" / "api_cache"
        else:
            cache_dir = Path(cache_dir)
        
        # Ensure cache directory exists
        cache_dir.expanduser().mkdir(parents=True, exist_ok=True)
        
        self.cache_dir = cache_dir.expanduser()
        self.max_age = max_age
        self.memory_cache = {}
    
    def _get_cache_path(self, key: str) -> Path:
        """Get cache file path for a key.
        
        Args:
            key: Cache key.
            
        Returns:
            Path to cache file.
        """
        import hashlib
        # Create hash of key
        hash_key = hashlib.md5(key.encode()).hexdigest()
        return self.cache_dir / f"{hash_key}.json"
    
    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Get a value from the cache.
        
        Args:
            key: Cache key.
            
        Returns:
            Cached value or None if not found or expired.
        """
        # Check memory cache first
        if key in self.memory_cache:
            entry = self.memory_cache[key]
            if entry["timestamp"] + self.max_age > time.time():
                return entry["data"]
            else:
                # Expired, remove from memory cache
                del self.memory_cache[key]
        
        # Check file cache
        cache_path = self._get_cache_path(key)
        if cache_path.exists():
            try:
                # Read cache file
                import json
                with open(cache_path, "r") as f:
                    cache_data = json.load(f)
                
                # Check if expired
                if cache_data["timestamp"] + self.max_age > time.time():
                    # Add to memory cache
                    self.memory_cache[key] = cache_data
                    return cache_data["data"]
                else:
                    # Expired, remove file
                    cache_path.unlink(missing_ok=True)
            except Exception as e:
                logger.error(f"Error reading cache file {cache_path}: {e}")
                # Remove invalid cache file
                cache_path.unlink(missing_ok=True)
        
        return None
    
    def set(self, key: str, value: Dict[str, Any]) -> None:
        """Set a value in the cache.
        
        Args:
            key: Cache key.
            value: Value to cache.
        """
        # Create cache entry
        cache_data = {
            "timestamp": time.time(),
            "data": value
        }
        
        # Add to memory cache
        self.memory_cache[key] = cache_data
        
        # Write to file cache
        cache_path = self._get_cache_path(key)
        try:
            import json
            with open(cache_path, "w") as f:
                json.dump(cache_data, f)
        except Exception as e:
            logger.error(f"Error writing cache file {cache_path}: {e}")
    
    def clear(self, key: Optional[str] = None) -> None:
        """Clear cache entries.
        
        Args:
            key: Optional key to clear. If None, clear all entries.
        """
        if key is None:
            # Clear all
            self.memory_cache.clear()
            for cache_file in self.cache_dir.glob("*.json"):
                cache_file.unlink(missing_ok=True)
        else:
            # Clear specific key
            if key in self.memory_cache:
                del self.memory_cache[key]
            
            cache_path = self._get_cache_path(key)
            cache_path.unlink(missing_ok=True)
    
    def clear_expired(self) -> int:
        """Clear expired cache entries.
        
        Returns:
            Number of cleared entries.
        """
        cleared = 0
        
        # Clear expired from memory cache
        current_time = time.time()
        expired_keys = [
            key for key, entry in self.memory_cache.items()
            if entry["timestamp"] + self.max_age < current_time
        ]
        
        for key in expired_keys:
            del self.memory_cache[key]
            cleared += 1
        
        # Clear expired from file cache
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                import json
                with open(cache_file, "r") as f:
                    cache_data = json.load(f)
                
                if cache_data["timestamp"] + self.max_age < current_time:
                    cache_file.unlink()
                    cleared += 1
            except Exception:
                # Invalid cache file, remove it
                cache_file.unlink(missing_ok=True)
                cleared += 1
        
        return cleared


# Create a global API cache instance
api_cache = ApiCache()
