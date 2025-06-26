"""Manga reading history tracking.

This module provides functionality to track manga reading history, including downloaded volumes,
reading progress, and checking for updates.
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Set, Union
from datetime import datetime, timedelta
import time

from .config import Config

# Set up logging
logger = logging.getLogger(__name__)


class MangaHistory:
    """Manages manga reading history."""
    
    def __init__(self, history_dir: Optional[Union[str, Path]] = None):
        """Initialize manga history manager.
        
        Args:
            history_dir: Directory for history files. If None, use config default.
        """
        self.config = Config()
        
        if history_dir is None:
            # Use config directory
            history_dir = Path(self.config.get_config_dir()) / "history"
        else:
            history_dir = Path(history_dir)
        
        # Ensure history directory exists
        history_dir.mkdir(parents=True, exist_ok=True)
        
        self.history_dir = history_dir
        self.history_file = history_dir / "manga_history.json"
        self.history_data = self._load_history()
    
    def _load_history(self) -> Dict[str, Any]:
        """Load history from file.
        
        Returns:
            Dict with history data.
        """
        if not self.history_file.exists():
            return {
                "manga": {},
                "last_updated": datetime.now().isoformat()
            }
        
        try:
            with open(self.history_file, "r") as f:
                data = json.load(f)
            
            # Ensure structure is valid
            if "manga" not in data:
                data["manga"] = {}
            
            if "last_updated" not in data:
                data["last_updated"] = datetime.now().isoformat()
            
            return data
            
        except Exception as e:
            logger.error(f"Failed to load history: {e}")
            return {
                "manga": {},
                "last_updated": datetime.now().isoformat()
            }
    
    def _save_history(self) -> None:
        """Save history to file."""
        try:
            with open(self.history_file, "w") as f:
                json.dump(self.history_data, f, indent=2)
                
            # Set secure permissions
            os.chmod(self.history_file, 0o600)
            
        except Exception as e:
            logger.error(f"Failed to save history: {e}")
    
    def record_manga_download(self, manga_id: str, manga_title: str, 
                             volumes: List[str], success: bool = True,
                             metadata: Optional[Dict[str, Any]] = None) -> None:
        """Record manga download in history.
        
        Args:
            manga_id: MangaDex ID for the manga.
            manga_title: Title of the manga.
            volumes: List of volume numbers downloaded.
            success: Whether the download was successful.
            metadata: Additional metadata.
        """
        now = datetime.now().isoformat()
        
        # Get or create manga entry
        manga_entry = self.history_data["manga"].get(manga_id, {
            "id": manga_id,
            "title": manga_title,
            "downloads": [],
            "volumes": set(),
            "first_seen": now,
            "last_updated": now
        })
        
        # Convert volumes set to list for JSON serialization if it exists
        if isinstance(manga_entry.get("volumes"), set):
            manga_entry["volumes"] = list(manga_entry["volumes"])
        
        # Record download
        download_entry = {
            "timestamp": now,
            "volumes": volumes,
            "success": success,
            "metadata": metadata or {}
        }
        manga_entry["downloads"].append(download_entry)
        
        # Update volumes
        if isinstance(manga_entry["volumes"], list):
            volume_set = set(manga_entry["volumes"])
        else:
            volume_set = set()
            
        volume_set.update(volumes)
        manga_entry["volumes"] = list(volume_set)
        
        # Update timestamps
        manga_entry["last_updated"] = now
        self.history_data["last_updated"] = now
        
        # Update manga entry
        self.history_data["manga"][manga_id] = manga_entry
        
        # Save history
        self._save_history()
    
    def record_manga_read(self, manga_id: str, volume: str) -> None:
        """Record manga volume as read.
        
        Args:
            manga_id: MangaDex ID for the manga.
            volume: Volume number read.
        """
        now = datetime.now().isoformat()
        
        # Get manga entry
        manga_entry = self.history_data["manga"].get(manga_id)
        
        if not manga_entry:
            logger.warning(f"Manga {manga_id} not found in history")
            return
        
        # Record read
        if "reads" not in manga_entry:
            manga_entry["reads"] = {}
        
        manga_entry["reads"][volume] = {
            "last_read": now,
            "read_count": manga_entry["reads"].get(volume, {}).get("read_count", 0) + 1
        }
        
        # Update timestamps
        manga_entry["last_updated"] = now
        self.history_data["last_updated"] = now
        
        # Save history
        self._save_history()
    
    def get_manga_history(self, manga_id: Optional[str] = None) -> Dict[str, Any]:
        """Get manga history.
        
        Args:
            manga_id: Optional MangaDex ID for specific manga history.
            
        Returns:
            Dict with history data.
        """
        if manga_id:
            return self.history_data["manga"].get(manga_id, {})
        else:
            return self.history_data
    
    def get_manga_list(self) -> List[Dict[str, Any]]:
        """Get list of all manga in history.
        
        Returns:
            List of manga entries.
        """
        manga_list = []
        
        for manga_id, manga_data in self.history_data["manga"].items():
            # Create summary entry
            summary = {
                "id": manga_id,
                "title": manga_data["title"],
                "volumes": manga_data.get("volumes", []),
                "first_seen": manga_data["first_seen"],
                "last_updated": manga_data["last_updated"],
                "download_count": len(manga_data.get("downloads", [])),
                "last_read": None
            }
            
            # Find last read timestamp
            reads = manga_data.get("reads", {})
            if reads:
                last_read_timestamps = [read["last_read"] for read in reads.values()]
                if last_read_timestamps:
                    summary["last_read"] = max(last_read_timestamps)
            
            manga_list.append(summary)
        
        # Sort by last updated
        manga_list.sort(key=lambda x: x["last_updated"], reverse=True)
        
        return manga_list
    
    def get_recently_updated(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get list of recently updated manga.
        
        Args:
            days: Number of days to consider as recent.
            
        Returns:
            List of recently updated manga.
        """
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        
        return [
            manga for manga in self.get_manga_list()
            if manga["last_updated"] > cutoff
        ]
    
    def get_recently_read(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get list of recently read manga.
        
        Args:
            days: Number of days to consider as recent.
            
        Returns:
            List of recently read manga.
        """
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        
        return [
            manga for manga in self.get_manga_list()
            if manga.get("last_read") and manga["last_read"] > cutoff
        ]
    
    def delete_manga_history(self, manga_id: str) -> bool:
        """Delete manga from history.
        
        Args:
            manga_id: MangaDex ID for the manga.
            
        Returns:
            Whether the manga was deleted.
        """
        if manga_id in self.history_data["manga"]:
            del self.history_data["manga"][manga_id]
            self.history_data["last_updated"] = datetime.now().isoformat()
            self._save_history()
            return True
        return False


# Global instance
manga_history = MangaHistory()
