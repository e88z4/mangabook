"""MangaDex API Wrapper.

This module provides a high-level wrapper around the MangaDex API,
handling authentication, pagination, error handling, and retries.
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional, Union, Tuple, Generator, AsyncGenerator

from .auth import AuthManager, AuthenticationError
from .utils import retry, exception_handler

# Set up logging
logger = logging.getLogger(__name__)


class MangaDexAPI:
    """High-level wrapper for the MangaDex API."""
    
    def __init__(self):
        """Initialize the MangaDex API wrapper."""
        self.auth_manager = AuthManager()
        self._client = None
    
    async def _get_client(self):
        """Get an authenticated MangaDex client.
        
        Returns:
            The MangaDex API client.
            
        Raises:
            AuthenticationError: If authentication fails.
        """
        return await self.auth_manager.get_client()
    
    @exception_handler
    @retry(max_attempts=3, delay=1.0, backoff=2.0)
    async def search_manga(self, title: str, limit: int = 10, offset: int = 0, 
                           language: Optional[str] = None) -> Dict[str, Any]:
        """Search for manga by title.
        
        Args:
            title: The title to search for.
            limit: Maximum number of results to return.
            offset: Number of results to skip.
            language: Filter by original language (e.g., 'ja' for Japanese)
                     or translated language for available translations.
            
        Returns:
            Dict with search results.
            
        Raises:
            AuthenticationError: If authentication fails.
            Exception: If the API request fails.
        """
        client = await self._get_client()
        
        # Use only the supported parameters
        search_params = {
            "title": title,
            "limit": limit,
            "offset": offset
        }
        
        # We'll handle language filtering in the CLI since the API wrapper 
        # doesn't support these parameters directly
        
        # Make the API call with proper parameters
        response = await client.search_manga(**search_params)
        return response
    
    @exception_handler
    @retry(max_attempts=3, delay=1.0, backoff=2.0)
    async def get_manga(self, manga_id: str) -> Dict[str, Any]:
        """Get manga details by ID.
        
        Args:
            manga_id: The MangaDex ID of the manga.
            
        Returns:
            Dict with manga details.
            
        Raises:
            AuthenticationError: If authentication fails.
            Exception: If the API request fails.
        """
        client = await self._get_client()
        # Use the get_manga method directly on the client if available
        # Otherwise, fallback to a basic fetch
        try:
            response = await client.get_manga(manga_id)
            return response
        except AttributeError:
            # Fallback if client structure changed
            logger.warning("Using fallback method for get_manga")
            response = await client.manga.get(manga_id, includes=["cover_art", "author", "artist"])
            return response
    
    @exception_handler
    @retry(max_attempts=3, delay=1.0, backoff=2.0)
    async def get_chapters(self, manga_id: str, language: Optional[str] = None, 
                          limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """Get chapters for a manga.
        
        Args:
            manga_id: The MangaDex ID of the manga.
            language: Filter by translation language (e.g., 'en').
            limit: Maximum number of results to return.
            offset: Number of results to skip.
            
        Returns:
            Dict with chapter results.
            
        Raises:
            AuthenticationError: If authentication fails.
            Exception: If the API request fails.
        """
        client = await self._get_client()
        
        try:
            # Try using the API directly if available
            params = {
                "manga": manga_id,
                "limit": limit,
                "offset": offset
            }
            
            if language:
                params["translatedLanguage"] = [language]
            
            # Try using the get_chapter_list method
            response = await client.get_chapter_list(**params)
            return response
        except (AttributeError, TypeError):
            logger.warning("Using fallback method for get_chapters")
            # Fallback to older structure
            params = {
                "manga": manga_id,
                "limit": limit,
                "offset": offset,
                "includes": ["scanlation_group"]
            }
            
            if language:
                params["translatedLanguage[]"] = [language]
            
            response = await client.chapter.list(**params)
            return response
    
    async def get_all_chapters(self, manga_id: str, language: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all chapters for a manga, handling pagination.
        
        Args:
            manga_id: The MangaDex ID of the manga.
            language: Filter by translation language (e.g., 'en').
            
        Returns:
            List of all chapter data.
            
        Raises:
            AuthenticationError: If authentication fails.
            Exception: If the API request fails.
        """
        all_chapters = []
        offset = 0
        limit = 100
        
        while True:
            response = await self.get_chapters(manga_id, language, limit, offset)
            chapters = response.get("data", [])
            
            if not chapters:
                break
                
            all_chapters.extend(chapters)
            
            offset += limit
            if offset >= response.get("total", 0):
                break
        
        return all_chapters
    
    @exception_handler
    @retry(max_attempts=3, delay=1.0, backoff=2.0)
    async def get_chapter_images(self, chapter_id: str, data_saver: bool = False) -> Dict[str, Any]:
        """Get image URLs for a chapter.
        
        Args:
            chapter_id: The MangaDex ID of the chapter.
            data_saver: Use data-saver (compressed) images.
            
        Returns:
            Dict with image URLs and other chapter data.
            
        Raises:
            AuthenticationError: If authentication fails.
            Exception: If the API request fails.
        """
        client = await self._get_client()
        response = await client.at_home.server(chapter_id)
        
        chapter_hash = response["chapter"]["hash"]
        base_url = response["baseUrl"]
        
        # Choose between normal quality or data-saver
        image_quality = "dataSaver" if data_saver else "data"
        image_filenames = response["chapter"][image_quality]
        
        # Construct full URLs for each image
        image_urls = []
        for filename in image_filenames:
            quality_path = "data-saver" if data_saver else "data"
            url = f"{base_url}/{quality_path}/{chapter_hash}/{filename}"
            image_urls.append(url)
        
        return {
            "id": chapter_id,
            "hash": chapter_hash,
            "urls": image_urls,
            "total": len(image_urls)
        }
    
    @exception_handler
    @retry(max_attempts=3, delay=1.0, backoff=2.0)
    async def get_cover_art(self, manga_id: str) -> str:
        """Get cover art URL for a manga.
        
        Args:
            manga_id: The MangaDex ID of the manga.
            
        Returns:
            URL for the cover art.
            
        Raises:
            AuthenticationError: If authentication fails.
            Exception: If the API request fails.
        """
        manga_data = await self.get_manga(manga_id)
        
        cover_art = None
        for relationship in manga_data.get("relationships", []):
            if relationship["type"] == "cover_art":
                cover_art = relationship
                break
        
        if not cover_art or "attributes" not in cover_art:
            return ""
        
        filename = cover_art["attributes"].get("fileName", "")
        if not filename:
            return ""
        
        return f"https://uploads.mangadex.org/covers/{manga_id}/{filename}"
    
    @exception_handler
    @retry(max_attempts=3, delay=1.0, backoff=2.0)
    async def get_scanlation_group(self, group_id: str) -> Dict[str, Any]:
        """Get information about a scanlation group.
        
        Args:
            group_id: The MangaDex ID of the scanlation group.
            
        Returns:
            Dict with group details.
            
        Raises:
            AuthenticationError: If authentication fails.
            Exception: If the API request fails.
        """
        client = await self._get_client()
        response = await client.scanlation_group.get(group_id)
        return response
    
    async def get_manga_volumes(self, manga_id: str, language: Optional[str] = None) -> Dict[str, Any]:
        """Get volume information for a manga.
        
        Args:
            manga_id: The MangaDex ID of the manga.
            language: Filter by translation language (e.g., 'en').
            
        Returns:
            Dict with volume information.
            
        Raises:
            AuthenticationError: If authentication fails.
            Exception: If the API request fails.
        """
        client = await self._get_client()
        
        params = {"manga": manga_id}
        if language:
            params["translatedLanguage[]"] = [language]
            
        response = await client.manga.aggregate(**params)
        return response.get("volumes", {})
    
    async def login(self, username: str, password: str,
                client_id: Optional[str] = None,
                client_secret: Optional[str] = None) -> Tuple[bool, str]:
        """Log in to MangaDex using OAuth2.
        
        Args:
            username: MangaDex username.
            password: MangaDex password.
            client_id: MangaDex OAuth2 client ID (optional).
            client_secret: MangaDex OAuth2 client secret (optional).
            
        Returns:
            Tuple[bool, str]: (Success flag, Error message if failed).
        """
        return await self.auth_manager.login(username, password, client_id, client_secret)
    
    async def logout(self) -> Tuple[bool, str]:
        """Log out from MangaDex.
        
        Returns:
            Tuple[bool, str]: (Success flag, Error message if failed).
        """
        return await self.auth_manager.logout()
    
    async def close(self) -> None:
        """Close the API client."""
        await self.auth_manager.close()
    
    async def get_manga_chapters(self, manga_id: str, language: Optional[str] = None) -> Dict[str, Any]:
        """Alias for get_chapters to maintain compatibility.
        
        Args:
            manga_id: The MangaDex ID of the manga.
            language: Filter by translation language (e.g., 'en').
            
        Returns:
            Dict with chapter results.
            
        Raises:
            AuthenticationError: If authentication fails.
            Exception: If the API request fails.
        """
        return await self.get_all_chapters(manga_id, language)


# Singleton instance for global use
_api_instance = None


async def get_api() -> MangaDexAPI:
    """Get the global MangaDexAPI instance.
    
    Returns:
        MangaDexAPI: The global API instance.
    """
    global _api_instance
    if _api_instance is None:
        _api_instance = MangaDexAPI()
    return _api_instance
