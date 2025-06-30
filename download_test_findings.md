# MangaBook Download Functionality Testing Results

## Summary
- Manga search functionality is now working correctly
- Download functionality has been tested and shows connectivity issues with the MangaDex API's endpoints
- The API connectivity to `/at-home/server/{chapter_id}` endpoint is causing timeouts or hanging connections
- The `/manga/{manga_id}/aggregate` endpoint works for some manga titles but not others

## Issues Identified
1. Fixed incorrect method name in `get_volumes` function: `get_manga_chapters` was changed to `get_chapters`
2. The API appears to be connecting to search and basic manga info endpoints successfully
3. The manga volumes endpoint works for some manga titles (e.g., Naruto) but times out for others (e.g., Spy x Family)
4. The chapter images endpoint (`at-home/server/{chapter_id}`) consistently times out or hangs, preventing image downloads

## Fixed Code Issues
1. Added proper manga ID display in search results
2. Added additional error handling for API requests
3. Made method name consistent between CLI and API classes
4. Added debug logging to track API responses

## Recommended Implementation for Timeouts

### Update all API methods to include timeouts:

```python
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
    
    # Build query parameters
    url = f"/at-home/server/{chapter_id}"
    
    # Use direct HTTP request with timeout
    await client._ensure_session()
    try:
        async with client.session.get(f"{client.base_url}{url}", timeout=timeout) as response:
            if response.status != 200:
                logger.error(f"Error getting chapter images: HTTP {response.status}")
                error_text = await response.text()
                logger.error(f"Error response: {error_text}")
                return {"id": chapter_id, "urls": [], "total": 0}
            response_data = await response.json()
    except asyncio.TimeoutError:
        logger.error(f"Request timed out for chapter {chapter_id}")
        return {"id": chapter_id, "urls": [], "total": 0}
    
    # Process response as before...
```

### Apply similar timeout handling to all API methods:

1. Add timeout parameter to all API methods
2. Wrap HTTP calls in try-except blocks to catch timeouts
3. Return graceful fallbacks when timeouts occur
4. Add retry mechanism with exponential backoff
5. Implement caching for successful responses

## Mock API Responses for Testing

To enable testing of the download and EPUB generation functionality without relying on the MangaDex API, we should implement a mock API response system:

### 1. Create mock response files:
Create JSON files with sample responses for:
- Manga search
- Manga details
- Volume listings
- Chapter listings
- Chapter images

### 2. Implement a mock API client:
```python
class MockMangaDexAPI(MangaDexAPI):
    """Mock version of MangaDexAPI for testing."""
    
    def __init__(self, mock_data_dir: str = "tests/mock_data"):
        """Initialize with mock data directory."""
        super().__init__()
        self.mock_data_dir = Path(mock_data_dir)
    
    async def _load_mock_response(self, endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Load a mock response from a JSON file."""
        # Create a filename based on the endpoint and params
        filename = f"{endpoint.replace('/', '_')}.json"
        if params:
            # Add a hash of the params to make the filename unique
            param_hash = hash(frozenset(params.items()))
            filename = f"{endpoint.replace('/', '_')}_{param_hash}.json"
        
        filepath = self.mock_data_dir / filename
        if filepath.exists():
            with open(filepath, 'r') as f:
                return json.load(f)
        else:
            # Return empty response if mock file doesn't exist
            return {}
    
    async def search_manga(self, title: str, limit: int = 10, offset: int = 0, 
                         language: Optional[str] = None) -> Dict[str, Any]:
        """Mock search for manga by title."""
        return await self._load_mock_response("search_manga", {"title": title, "limit": limit})
    
    # Implement other methods similarly...
```

### 3. Enable mock mode via configuration:
```python
# In config.py
config.set("use_mock_api", True)

# In api.py
async def get_api() -> MangaDexAPI:
    """Get API client instance."""
    config = Config()
    if config.get("use_mock_api", False):
        return MockMangaDexAPI()
    else:
        return MangaDexAPI()
```

This approach would allow testing the download workflow and EPUB generation logic without API connectivity issues.

## Update on MangaDex API Submodule Changes

The mangadex-api submodule has been updated with new methods specifically for retrieving chapter images:

1. `get_chapter_server()` - Gets the MangaDex@Home server information for a chapter
2. `get_chapter_image_urls()` - Constructs image URLs from the server data

We've updated our API wrapper to use these new methods, which should provide better integration with the official API:

```python
# Updated implementation using the new submodule methods
async def get_chapter_images(self, chapter_id: str, data_saver: bool = False, timeout: float = 10.0) -> Dict[str, Any]:
    """Get image URLs for a chapter."""
    client = await self._get_client()
    
    try:
        # Use the new method with timeout
        at_home_data = await asyncio.wait_for(
            client.get_chapter_server(chapter_id), 
            timeout=timeout
        )
        
        # Use the helper method to construct image URLs
        image_urls = client.get_chapter_image_urls(at_home_data, use_data_saver=data_saver)
        
        # Extract necessary data
        chapter_hash = at_home_data["chapter"]["hash"]
        
        return {
            "id": chapter_id,
            "hash": chapter_hash,
            "urls": image_urls,
            "total": len(image_urls)
        }
    except asyncio.TimeoutError:
        logger.error(f"Request timed out for chapter {chapter_id}")
        return {"id": chapter_id, "urls": [], "total": 0}
    except Exception as e:
        logger.error(f"Exception getting chapter images: {e}")
        return {"id": chapter_id, "urls": [], "total": 0}
```

This implementation takes advantage of the official API client methods while still maintaining our timeout and error handling.

### Benefits of using the updated submodule:
1. More consistent implementation aligned with official API usage
2. Potential for better performance and reliability
3. Easier maintenance as the API evolves
4. Standardized error handling

## Testing Results with Updated API

We've attempted to test the updated implementation, but we're still experiencing the same connectivity issues with the MangaDex API endpoints. Even with the new methods from the submodule update:

1. The API requests to `/at-home/server/{chapter_id}` still hang or time out
2. Both direct HTTP requests and the new client methods exhibit the same behavior
3. The timeouts are consistent across different manga and chapter IDs

These persistent connection issues suggest the problem may be related to:
- Network connectivity between our environment and the MangaDex servers
- Potential rate limiting or IP blocking at the API level
- MangaDex API reliability issues or maintenance windows

### Recommended Next Steps:

1. **Implement the mock API approach** outlined earlier to enable development and testing of the rest of the application
2. Check MangaDex API status and documentation for known issues or scheduled maintenance
3. Test from different network environments to rule out IP-based restrictions
4. Add comprehensive timeout and retry mechanisms to all API calls
5. Update the downloader to gracefully handle API failures

## Summary of Changes Made

1. **MangaDex API Submodule Update**
   - Updated the mangadex-api submodule to latest version with chapter image retrieval methods
   - The commit (ff30f1f) adds dedicated methods for chapter image retrieval

2. **API Wrapper Enhancements**
   - Modified our API wrapper to use the new client methods
   - Added timeout handling to prevent hanging requests
   - Improved error handling and logging

3. **Testing Approaches**
   - Created test scripts to directly verify API connectivity
   - Tested with different manga IDs and chapter IDs
   - Added timeouts to prevent tests from hanging indefinitely

## Final Recommendations

Based on our findings and testing, we recommend the following approaches for moving forward:

1. **API Timeouts and Error Handling**
   - All API requests should include explicit timeouts (implemented in our code updates)
   - Error handling should gracefully handle timeouts and other failures
   - Add logging to track API response times and success rates

2. **Mock API Implementation**
   - Implement the mock API approach detailed earlier to enable continued development
   - Create sample response data from successful API calls when available
   - Add configuration option to toggle between real and mock API

3. **Network Investigation**
   - Test API connectivity from different network environments
   - Check if the MangaDex API has any regional restrictions
   - Monitor the MangaDex API status for any reported issues

4. **Gradual Fallbacks**
   - Implement a more robust retry system with exponential backoff
   - Add fallback options for when primary sources fail
   - Cache successful responses for reuse when appropriate

The project can continue to develop and test the EPUB generation and other features using the mock API while the connectivity issues are being resolved.
