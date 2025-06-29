"""MangaDex API Wrapper.

This module provides a high-level wrapper around the MangaDex API,
handling authentication, pagination, error handling, and retries.
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional, Union, Tuple, Generator, AsyncGenerator
from pathlib import Path

from .auth import AuthManager, AuthenticationError
from .utils import retry, exception_handler, ensure_directory

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
            language: Filter by original language (e.g., 'ja' for Japanese).
            
        Returns:
            Dict with search results.
            
        Raises:
            AuthenticationError: If authentication fails.
            Exception: If the API request fails.
        """
        client = await self._get_client()
        
        # Build query parameters
        url = "/manga"
        params = {
            "title": title,
            "limit": limit,
            "offset": offset,
            "includes[]": ["cover_art"]
        }
        
        # Only add language filter if explicitly specified
        if language:
            params["originalLanguage[]"] = [language]
        
        # Log the request for debugging
        logger.debug(f"Search request: URL={client.base_url}{url}, params={params}")
        
        # Use direct HTTP request instead of client.manga.search
        await client._ensure_session()
        async with client.session.get(f"{client.base_url}{url}", params=params) as response:
            response_data = await response.json()
            logger.debug(f"Search response status: {response.status}")
            logger.debug(f"Search response: {response_data}")
            return response_data
    
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
        
        # Build query parameters
        url = f"/manga/{manga_id}"
        params = {
            "includes[]": ["cover_art", "author", "artist"]
        }
        
        # Use direct HTTP request instead of client.manga.get
        await client._ensure_session()
        async with client.session.get(f"{client.base_url}{url}", params=params) as response:
            return await response.json()
    
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
        
        # Build query parameters
        url = "/chapter"
        params = {
            "manga": manga_id,
            "limit": limit,
            "offset": offset,
            "includes[]": ["scanlation_group"]
        }
        
        if language:
            params["translatedLanguage[]"] = [language]
        
        # Use direct HTTP request instead of client.chapter.list
        await client._ensure_session()
        async with client.session.get(f"{client.base_url}{url}", params=params) as response:
            return await response.json()
    
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
    async def get_chapter_images(self, chapter_id: str, data_saver: bool = False, timeout: float = 10.0) -> Dict[str, Any]:
        """Get image URLs for a chapter.
        
        Args:
            chapter_id: The MangaDex ID of the chapter.
            data_saver: Use data-saver (compressed) images.
            timeout: Timeout in seconds for the HTTP request.
            
        Returns:
            Dict with image URLs and other chapter data.
            
        Raises:
            AuthenticationError: If authentication fails.
            TimeoutError: If the request times out.
            Exception: If the API request fails.
        """
        client = await self._get_client()
        
        logger.debug(f"Getting chapter images for chapter: {chapter_id}")
        try:
            # Use the new method added to the client
            # Wrap with timeout for safety
            at_home_data = None
            try:
                # Set timeout using asyncio.wait_for
                at_home_data = await asyncio.wait_for(
                    client.get_chapter_server(chapter_id), 
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                logger.error(f"Request timed out for chapter {chapter_id}")
                return {"id": chapter_id, "urls": [], "total": 0}
                
            if not at_home_data:
                logger.error(f"No data received for chapter {chapter_id}")
                return {"id": chapter_id, "urls": [], "total": 0}
                
            logger.debug(f"Response keys: {at_home_data.keys()}")
            
            # Use the new helper method to construct image URLs
            image_urls = client.get_chapter_image_urls(at_home_data, use_data_saver=data_saver)
            
            # Extract hash for consistency with the previous implementation
            chapter_hash = at_home_data["chapter"]["hash"]
        except Exception as e:
            logger.error(f"Exception getting chapter images: {e}")
            return {"id": chapter_id, "urls": [], "total": 0}
        
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
        
        # Build query parameters
        url = f"/group/{group_id}"
        
        # Use direct HTTP request instead of client.scanlation_group.get
        await client._ensure_session()
        async with client.session.get(f"{client.base_url}{url}") as response:
            return await response.json()
    
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
        
        # Build query parameters
        url = f"/manga/{manga_id}/aggregate"
        params = {}
        if language:
            params["translatedLanguage[]"] = [language]
        
        # Use direct HTTP request instead of client.manga.aggregate
        await client._ensure_session()
        async with client.session.get(f"{client.base_url}{url}", params=params) as response:
            response_data = await response.json()
            return response_data.get("volumes", {})
    
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
    
    @exception_handler
    @retry(max_attempts=3, delay=1.0, backoff=2.0)
    async def get_group_statistics(self, group_id: str) -> Dict[str, Any]:
        """Get statistics (including follower count) for a scanlation group.
        
        Args:
            group_id: The MangaDex group ID.
            
        Returns:
            Dict with statistics (including 'follows').
        """
        client = await self._get_client()
        url = f"/statistics/group/{group_id}"
        await client._ensure_session()
        async with client.session.get(f"{client.base_url}{url}") as response:
            return await response.json()
    
    @exception_handler
    @retry(max_attempts=3, delay=1.0, backoff=2.0)
    async def get_volume_cover_art(self, manga_id: str, volume_number: str) -> Optional[str]:
        """Get volume-specific cover art URL for a manga.
        
        Args:
            manga_id: The MangaDex ID of the manga.
            volume_number: The volume number as a string (e.g., '1', '01', etc.)
            
        Returns:
            Optional[str]: URL for the volume cover art, or None if not found.
            
        Raises:
            AuthenticationError: If authentication fails.
            Exception: If the API request fails.
        """
        client = await self._get_client()
        
        # Build query parameters
        url = "/cover"
        params = {
            "manga[]": manga_id,
            "limit": 100,  # Get a large number of covers to search through
            "offset": 0,
            "order[volume]": "asc"  # Order by volume number
        }
        
        # Use direct HTTP request
        await client._ensure_session()
        async with client.session.get(f"{client.base_url}{url}", params=params) as response:
            response_data = await response.json()
            
            # Check for errors
            if response_data.get("result") != "ok":
                logger.error(f"Error fetching covers: {response_data.get('errors', [])}")
                return None
            
            # Extract covers data
            covers = response_data.get("data", [])
            if not covers:
                logger.warning(f"No covers found for manga {manga_id}")
                return None
            
            # Find the cover for the specified volume
            target_cover = None
            for cover in covers:
                if "attributes" in cover and cover["attributes"].get("volume") == volume_number:
                    target_cover = cover
                    break
            
            # If volume number didn't match exactly, try to match without leading zeros
            if not target_cover and volume_number.startswith("0"):
                stripped_volume = volume_number.lstrip("0")
                if stripped_volume:  # Ensure it's not empty (e.g., volume "0")
                    for cover in covers:
                        if "attributes" in cover and cover["attributes"].get("volume") == stripped_volume:
                            target_cover = cover
                            break
            
            # If still no match and volume has no leading zeros, try with leading zeros
            if not target_cover and not volume_number.startswith("0"):
                padded_volume = volume_number.zfill(2)  # Add leading zero
                for cover in covers:
                    if "attributes" in cover and cover["attributes"].get("volume") == padded_volume:
                        target_cover = cover
                        break
            
            # If we found a cover, construct the URL
            if target_cover and "attributes" in target_cover:
                filename = target_cover["attributes"].get("fileName")
                if filename:
                    return f"https://uploads.mangadex.org/covers/{manga_id}/{filename}"
            
            # If no specific volume cover found, fall back to the general cover
            logger.warning(f"No specific cover found for volume {volume_number}, falling back to general cover")
            return await self.get_cover_art(manga_id)
    
    @exception_handler
    @retry(max_attempts=3, delay=1.0, backoff=2.0)
    async def download_cover_image(self, cover_url: str, output_path: Union[str, Path]) -> Optional[str]:
        """Download a cover image from a URL.
        
        Args:
            cover_url: URL of the cover image.
            output_path: Path where the cover image should be saved.
            
        Returns:
            Optional[str]: Path to the downloaded cover image, or None if download failed.
            
        Raises:
            AuthenticationError: If authentication fails.
            Exception: If the API request fails.
        """
        if not cover_url:
            logger.error("No cover URL provided")
            return None
        
        output_path = Path(output_path)
        ensure_directory(output_path.parent)
        
        client = await self._get_client()
        await client._ensure_session()
        
        try:
            async with client.session.get(cover_url) as response:
                if response.status != 200:
                    logger.error(f"Failed to download cover image: {response.status}")
                    return None
                
                # Read the image data
                image_data = await response.read()
                
                # Save the image
                with open(output_path, 'wb') as f:
                    f.write(image_data)
                
                logger.info(f"Downloaded cover image to {output_path}")
                return str(output_path)
        
        except Exception as e:
            logger.error(f"Error downloading cover image: {e}")
            return None


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


async def close_global_api() -> None:
    """Close the global API instance if it exists."""
    global _api_instance
    if _api_instance is not None:
        await _api_instance.close()
        _api_instance = None
