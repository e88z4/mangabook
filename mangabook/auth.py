"""Authentication handling for MangaDex API.

This module provides functions for securely storing and retrieving MangaDex
credentials, as well as handling login, logout, and token refresh operations.
"""

import os
import json
import logging
import time
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, Union

# Assuming we'll access the MangaDex API through the submodule
import sys
import importlib.util
from pathlib import Path

# Set up logging
logger = logging.getLogger(__name__)

# Constants
AUTH_DIR = Path.home() / ".mangabook"
CREDENTIALS_FILE = AUTH_DIR / "credentials.json"
TOKEN_EXPIRATION_BUFFER = 300  # Refresh token 5 minutes before expiration

# Default OAuth2 credentials - replace these with your actual values or use env vars
DEFAULT_CLIENT_ID = os.environ.get("MANGADEX_CLIENT_ID", "mangabook_client")
DEFAULT_CLIENT_SECRET = os.environ.get("MANGADEX_CLIENT_SECRET", "mangabook_secret")


def _import_mangadex_client():
    """Import the MangaDex API client from the submodule.
    
    Returns:
        The MangaDex API client class.
    
    Raises:
        ImportError: If the MangaDex API client cannot be imported.
    """
    try:
        # Use importlib to import from a package named 'async'
        import importlib
        module = importlib.import_module('mangadex.api.async.client')
        return getattr(module, 'MangaDexAsyncClient')
    except ImportError:
        # Try to import from the submodule directly
        try:
            repo_root = Path(__file__).parent.parent
            mangadex_api_path = repo_root / "mangadex-api"
            if (mangadex_api_path / "src").exists():
                sys.path.insert(0, str(mangadex_api_path))
                import importlib
                module = importlib.import_module('mangadex.api.async.client')
                return getattr(module, 'MangaDexAsyncClient')
            else:
                logger.error("MangaDex API submodule not found at expected path")
                raise ImportError("MangaDex API client not found")
        except ImportError as e:
            logger.error(f"Failed to import MangaDex API client: {e}")
            raise


def ensure_auth_dir() -> None:
    """Create the authentication directory if it doesn't exist.
    
    Sets appropriate permissions (700) for security.
    
    Raises:
        OSError: If directory creation fails or permissions can't be set.
    """
    try:
        AUTH_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        logger.debug(f"Authentication directory ensured at {AUTH_DIR}")
    except OSError as e:
        logger.error(f"Failed to create authentication directory: {e}")
        raise


def save_credentials(username: str, password: str, client_id: str = DEFAULT_CLIENT_ID, 
                     client_secret: str = DEFAULT_CLIENT_SECRET) -> bool:
    """Securely save user credentials.
    
    Args:
        username: MangaDex username.
        password: MangaDex password.
        client_id: MangaDex OAuth2 client ID.
        client_secret: MangaDex OAuth2 client secret.
        
    Returns:
        bool: True if saving was successful, False otherwise.
    """
    ensure_auth_dir()
    
    # Create credentials dictionary with encrypted password
    # Note: In a production application, you would use a more secure encryption method
    credentials = {
        "username": username,
        "password": password,  # In reality, would be encrypted
        "client_id": client_id,
        "client_secret": client_secret,
        "token": None,
        "refresh_token": None,
        "token_expiry": 0,
    }
    
    try:
        with open(CREDENTIALS_FILE, "w") as f:
            json.dump(credentials, f)
        os.chmod(CREDENTIALS_FILE, 0o600)  # Secure file permissions
        logger.debug("Credentials saved successfully")
        return True
    except OSError as e:
        logger.error(f"Error saving credentials file: {e}")
        return False


def load_credentials() -> Optional[Dict[str, Any]]:
    """Load stored credentials.
    
    Returns:
        Dict[str, Any]: The stored credentials, or None if no credentials exist.
    """
    if not CREDENTIALS_FILE.exists():
        logger.debug("No credentials file found")
        return None
    
    try:
        with open(CREDENTIALS_FILE, "r") as f:
            credentials = json.load(f)
        logger.debug(f"Credentials loaded: username={credentials.get('username')}, client_id={credentials.get('client_id')}, has_password={'password' in credentials and bool(credentials.get('password'))}")
        return credentials
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Error loading credentials file: {e}")
        return None


def delete_credentials() -> bool:
    """Delete stored credentials.
    
    Returns:
        bool: True if deletion was successful or file didn't exist, False otherwise.
    """
    if not CREDENTIALS_FILE.exists():
        logger.debug("No credentials file to delete")
        return True
    
    try:
        CREDENTIALS_FILE.unlink()
        logger.debug("Credentials deleted successfully")
        return True
    except OSError as e:
        logger.error(f"Error deleting credentials file: {e}")
        return False


def has_valid_token() -> bool:
    """Check if a valid auth token exists.
    
    Returns:
        bool: True if a valid token exists, False otherwise.
    """
    credentials = load_credentials()
    if not credentials:
        return False
    
    token = credentials.get("token")
    expiry = credentials.get("token_expiry", 0)
    
    if not token:
        return False
    
    # Check if token is still valid (with buffer time)
    return expiry > (time.time() + TOKEN_EXPIRATION_BUFFER)


def update_token(token: str, refresh_token: str, expiry: int) -> bool:
    """Update stored token information.
    
    Args:
        token: Authentication token.
        refresh_token: Refresh token.
        expiry: Expiry timestamp.
        
    Returns:
        bool: True if update was successful, False otherwise.
    """
    credentials = load_credentials()
    if not credentials:
        logger.error("Cannot update token: No credentials file")
        return False
    
    credentials["token"] = token
    credentials["refresh_token"] = refresh_token
    credentials["token_expiry"] = expiry
    
    try:
        with open(CREDENTIALS_FILE, "w") as f:
            json.dump(credentials, f)
        os.chmod(CREDENTIALS_FILE, 0o600)  # Ensure secure permissions
        logger.debug("Token updated successfully")
        return True
    except OSError as e:
        logger.error(f"Error updating token: {e}")
        return False


async def login(username: Optional[str] = None, password: Optional[str] = None,
                client_id: Optional[str] = None, client_secret: Optional[str] = None) -> Tuple[bool, str]:
    """Login to MangaDex API using OAuth2.
    
    If username and password are not provided, loads from stored credentials.
    
    Args:
        username: MangaDex username (optional).
        password: MangaDex password (optional).
        client_id: MangaDex OAuth2 client ID (optional).
        client_secret: MangaDex OAuth2 client secret (optional).
        
    Returns:
        Tuple[bool, str]: (Success flag, Error message if failed).
    """
    # If credentials provided, save them
    if username and password:
        save_creds_args = {"username": username, "password": password}
        if client_id:
            save_creds_args["client_id"] = client_id
        if client_secret:
            save_creds_args["client_secret"] = client_secret
        
        if not save_credentials(**save_creds_args):
            return False, "Failed to save credentials"
    
    credentials = load_credentials()
    if not credentials:
        logger.error("No credentials found for login.")
        return False, "No credentials found. Please provide username and password."
    
    logger.info(f"Attempting login with stored credentials: username={credentials.get('username')}, client_id={credentials.get('client_id')}, has_password={'password' in credentials and bool(credentials.get('password'))}")
    try:
        MangaDexAsyncClient = _import_mangadex_client()
        client = MangaDexAsyncClient()
        
        # Login using stored credentials with OAuth2
        username = credentials.get("username")
        password = credentials.get("password")
        client_id = credentials.get("client_id", DEFAULT_CLIENT_ID)
        client_secret = credentials.get("client_secret", DEFAULT_CLIENT_SECRET)
        
        if not username or not password:
            logger.error("Incomplete credentials for login.")
            return False, "Incomplete credentials"
        
        if not client_id or not client_secret:
            logger.error("Missing OAuth2 client credentials for login.")
            return False, "Missing OAuth2 client credentials"
        
        # Use OAuth2 password flow
        auth_result = await client.authenticate_with_password(
            username=username,
            password=password,
            client_id=client_id,
            client_secret=client_secret
        )
        
        if not auth_result.get("access_token"):
            error_msg = auth_result.get("error", "Unknown error")
            error_description = auth_result.get("error_description", "")
            logger.error(f"Authentication failed: {error_msg} {error_description} | API response: {auth_result}")
            return False, f"Authentication failed: {error_msg} {error_description} | API response: {auth_result}"
        
        # Extract token information
        token = auth_result.get("access_token")
        refresh_token = auth_result.get("refresh_token")
        token_expiry = time.time() + auth_result.get("expires_in", 0)
        
        # Store token information
        if not update_token(token, refresh_token, token_expiry):
            logger.error("Failed to store token after login.")
            return False, "Failed to store token"
        
        logger.info(f"Successfully logged in as {username}")
        return True, ""
        
    except Exception as e:
        logger.error(f"Login failed: {e}")
        return False, f"Login failed: {str(e)}"
    finally:
        # Close the client
        if 'client' in locals():
            await client.close()


async def refresh_token_if_needed() -> Tuple[bool, str]:
    """Refresh authentication token if it's close to expiring.
    
    Returns:
        Tuple[bool, str]: (Success flag, Error message if failed).
    """
    if has_valid_token():
        logger.debug("Token is valid, no refresh needed.")
        return True, ""
    
    credentials = load_credentials()
    if not credentials:
        logger.warning("No credentials found for refresh or login.")
        return False, "No credentials found"
    
    refresh_token = credentials.get("refresh_token")
    if not refresh_token:
        logger.info("No refresh token found, attempting login with stored credentials.")
        return await login()
    
    try:
        MangaDexAsyncClient = _import_mangadex_client()
        client = MangaDexAsyncClient()
        
        # Set the client credentials needed for token refresh
        client.client_id = credentials.get("client_id", DEFAULT_CLIENT_ID)
        client.client_secret = credentials.get("client_secret", DEFAULT_CLIENT_SECRET)
        client.refresh_token = refresh_token
        
        logger.info("Attempting token refresh with stored refresh token.")
        auth_result = await client.refresh_authentication()
        
        if not auth_result.get("access_token"):
            error_msg = auth_result.get("error", "Unknown error")
            error_description = auth_result.get("error_description", "")
            logger.warning(f"Token refresh failed: {error_msg} {error_description}. Attempting login with stored credentials.")
            # Always fallback to login if refresh fails
            return await login()
        
        # Extract token information
        token = auth_result.get("access_token")
        new_refresh_token = auth_result.get("refresh_token")
        token_expiry = time.time() + auth_result.get("expires_in", 0)
        
        # Store token information
        if not update_token(token, new_refresh_token, token_expiry):
            logger.error("Failed to store refreshed token.")
            return False, "Failed to store refreshed token"
        
        logger.info("Token refreshed successfully.")
        return True, ""
        
    except Exception as e:
        logger.error(f"Token refresh exception: {e}. Attempting login with stored credentials.")
        # Always fallback to login if refresh fails for any reason
        return await login()
    finally:
        # Close the client
        if 'client' in locals():
            await client.close()


async def logout() -> Tuple[bool, str]:
    """Logout from MangaDex API.
    
    Returns:
        Tuple[bool, str]: (Success flag, Error message if failed).
    """
    credentials = load_credentials()
    if not credentials or not credentials.get("token"):
        # If no token, just delete credentials
        delete_credentials()
        return True, ""
    
    try:
        MangaDexAsyncClient = _import_mangadex_client()
        client = MangaDexAsyncClient()
        
        # Set the stored token
        client.access_token = credentials.get("token")
        
        # Attempt to use the logout endpoint
        # Note: This may not be strictly necessary with OAuth2
        try:
            await client.logout()
            logger.info("Logged out from MangaDex API")
        except Exception as e:
            logger.warning(f"API logout failed, continuing with local logout: {e}")
        
        # Delete credentials
        if not delete_credentials():
            return False, "Failed to delete credentials"
        
        return True, ""
    except Exception as e:
        logger.error(f"Logout failed: {e}")
        
        # Still try to delete credentials locally
        if delete_credentials():
            return True, "Logged out locally (API logout failed)"
        
        return False, f"Logout failed: {str(e)}"
    finally:
        # Close the client
        if 'client' in locals():
            await client.close()


async def get_auth_status() -> dict:
    """Get the current authentication status.
    
    Returns:
        dict: Authentication status details.
    """
    credentials = load_credentials()
    if not credentials:
        return {
            "logged_in": False,
            "username": None,
            "token_valid": False
        }
    
    username = credentials.get("username")
    has_token = credentials.get("token") is not None
    token_valid = has_valid_token()
    
    return {
        "logged_in": has_token and token_valid,
        "username": username,
        "token_valid": token_valid
    }


class AuthManager:
    """Manager for handling MangaDex authentication."""
    
    def __init__(self):
        """Initialize the authentication manager."""
        self._client = None
    
    async def get_client(self) -> Any:
        """Get an authenticated MangaDex client.
        
        Returns:
            An authenticated MangaDex API client.
            
        Raises:
            AuthenticationError: If authentication fails.
        """
        # Ensure token is valid
        success, message = await refresh_token_if_needed()
        if not success:
            logger.error(f"Authentication error: {message}")
            raise AuthenticationError(message)
        
        if self._client is None:
            MangaDexAsyncClient = _import_mangadex_client()
            self._client = MangaDexAsyncClient()
            
            # Set the stored token and OAuth credentials
            credentials = load_credentials()
            if credentials and credentials.get("token"):
                self._client.access_token = credentials["token"]
                self._client.refresh_token = credentials["refresh_token"]
                self._client.token_expires_at = credentials["token_expiry"]
                
                # Set client ID and secret for potential token refresh
                self._client.client_id = credentials.get("client_id", DEFAULT_CLIENT_ID)
                self._client.client_secret = credentials.get("client_secret", DEFAULT_CLIENT_SECRET)
        
        return self._client
    
    async def login(self, username: str, password: str, 
                    client_id: Optional[str] = None, 
                    client_secret: Optional[str] = None) -> Tuple[bool, str]:
        """Log in with username and password using OAuth2.
        
        Args:
            username: MangaDex username.
            password: MangaDex password.
            client_id: MangaDex OAuth2 client ID (optional).
            client_secret: MangaDex OAuth2 client secret (optional).
            
        Returns:
            Tuple[bool, str]: (Success flag, Error message if failed).
        """
        # Close existing client if there is one
        await self.close()
        
        return await login(username, password, client_id, client_secret)
    
    async def logout(self) -> Tuple[bool, str]:
        """Log out from MangaDex.
        
        Returns:
            Tuple[bool, str]: (Success flag, Error message if failed).
        """
        result = await logout()
        
        # Close and reset client
        await self.close()
        
        return result
    
    async def close(self) -> None:
        """Close the MangaDex client."""
        if self._client:
            await self._client.close()
            self._client = None


class AuthenticationError(Exception):
    """Exception raised when authentication fails."""
    pass
