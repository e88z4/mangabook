"""Testing module for MangaBook.

This module provides functionality to test various components of MangaBook.
It can be used to verify that the application is working correctly.
"""

import os
import sys
import asyncio
import logging
import time
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
import click

from .api import get_api
from .config import Config
from .error import error_handler, ErrorCategory
from .workflow import process_manga, check_environment, validate_epub
from .cli import search_manga, get_manga_details, get_volumes
from .downloader import ChapterDownloader

# Set up logging
logger = logging.getLogger(__name__)


class TestCase:
    """Base class for test cases."""
    
    def __init__(self, name: str, description: str):
        """Initialize test case.
        
        Args:
            name: Name of the test case.
            description: Description of the test case.
        """
        self.name = name
        self.description = description
        self.results = {
            "name": name,
            "description": description,
            "passed": False,
            "duration": 0.0,
            "output": "",
            "error": None
        }
    
    async def run(self) -> Dict[str, Any]:
        """Run the test case.
        
        Returns:
            Dict with test results.
        """
        start_time = time.time()
        
        try:
            # Run test case
            await self.execute()
            
            # Test passed
            self.results["passed"] = True
        except Exception as e:
            # Test failed
            error = error_handler.handle(e, category=ErrorCategory.UNEXPECTED)
            self.results["error"] = str(e)
            self.results["passed"] = False
        
        # Calculate duration
        end_time = time.time()
        self.results["duration"] = round(end_time - start_time, 2)
        
        return self.results
    
    async def execute(self) -> None:
        """Execute the test case. To be implemented by subclasses."""
        raise NotImplementedError("Subclass must implement execute method.")
    
    def log(self, message: str) -> None:
        """Log a message in the test output.
        
        Args:
            message: The message to log.
        """
        self.results["output"] += message + "\n"


class ApiConnectionTest(TestCase):
    """Test API connection."""
    
    def __init__(self):
        """Initialize test case."""
        super().__init__(
            name="API Connection Test",
            description="Tests connection to MangaDex API"
        )
    
    async def execute(self) -> None:
        """Execute the test case."""
        self.log("Testing API connection...")
        
        # Get API instance
        api = await get_api()
        
        # Test ping
        result = await api.ping()
        self.log(f"API ping result: {result}")
        
        if not result:
            raise Exception("API ping failed")
        
        self.log("API connection test passed")


class SearchTest(TestCase):
    """Test manga search."""
    
    def __init__(self):
        """Initialize test case."""
        super().__init__(
            name="Search Test",
            description="Tests manga search functionality"
        )
    
    async def execute(self) -> None:
        """Execute the test case."""
        self.log("Testing manga search...")
        
        # Test search with a common manga title
        results = await search_manga("one piece", limit=5)
        
        if not results:
            raise Exception("Search returned no results")
        
        self.log(f"Search returned {len(results)} results")
        
        # Check result structure
        test_result = results[0]
        required_fields = ["id", "title", "status", "description"]
        
        for field in required_fields:
            if field not in test_result:
                raise Exception(f"Search result missing required field: {field}")
        
        self.log(f"First result: {test_result['title']} (ID: {test_result['id']})")
        self.log("Search test passed")


class MangaDetailsTest(TestCase):
    """Test manga details retrieval."""
    
    def __init__(self, manga_id: Optional[str] = None):
        """Initialize test case.
        
        Args:
            manga_id: Optional manga ID to use for testing. If None, a default ID will be used.
        """
        super().__init__(
            name="Manga Details Test",
            description="Tests manga details retrieval"
        )
        # One Piece manga ID as default
        self.manga_id = manga_id or "32d76d19-8a05-4db0-9fc2-e0b0648fe9d0"
    
    async def execute(self) -> None:
        """Execute the test case."""
        self.log(f"Testing manga details retrieval for ID: {self.manga_id}")
        
        # Get manga details
        details = await get_manga_details(self.manga_id)
        
        if not details:
            raise Exception("Failed to retrieve manga details")
        
        # Check result structure
        required_fields = ["id", "title", "status", "description"]
        for field in required_fields:
            if field not in details:
                raise Exception(f"Manga details missing required field: {field}")
        
        self.log(f"Retrieved manga: {details['title']}")
        
        # Get volumes
        volumes = await get_volumes(self.manga_id)
        
        if not volumes:
            self.log("No volumes found (this might be expected for some manga)")
        else:
            self.log(f"Found {len(volumes)} volumes")
        
        self.log("Manga details test passed")


class DownloadTest(TestCase):
    """Test manga download."""
    
    def __init__(self, manga_id: Optional[str] = None, temp_dir: Optional[str] = None):
        """Initialize test case.
        
        Args:
            manga_id: Optional manga ID to use for testing. If None, a default ID will be used.
            temp_dir: Optional temporary directory for downloads. If None, a default directory will be used.
        """
        super().__init__(
            name="Download Test",
            description="Tests manga download functionality"
        )
        # One Piece manga ID as default
        self.manga_id = manga_id or "32d76d19-8a05-4db0-9fc2-e0b0648fe9d0"
        
        # Use temporary directory
        self.temp_dir = temp_dir or Path.home() / ".mangabook" / "test"
    
    async def execute(self) -> None:
        """Execute the test case."""
        self.log(f"Testing manga download for ID: {self.manga_id}")
        self.log(f"Using temporary directory: {self.temp_dir}")
        
        # Ensure test directory exists
        os.makedirs(self.temp_dir, exist_ok=True)
        
        # Initialize downloader
        downloader = ChapterDownloader(output_dir=str(self.temp_dir), keep_raw=False)
        await downloader.initialize()
        
        # Get manga details for title
        details = await get_manga_details(self.manga_id)
        manga_title = details["title"]
        self.log(f"Downloading manga: {manga_title}")
        
        # Get first volume of the manga
        volumes = await get_volumes(self.manga_id)
        
        # Find first valid volume
        volume_number = None
        for vol, info in volumes.items():
            if vol != "null" and vol != "None" and vol != "Unknown":
                volume_number = vol
                break
        
        if not volume_number:
            self.log("No valid volumes found, using chapter 1 instead")
            volume_number = "1"
        
        self.log(f"Downloading volume: {volume_number}")
        
        # Download only the first chapter of the volume to speed up test
        download_result = await downloader.download_volume(
            manga_id=self.manga_id,
            manga_title=manga_title,
            volume_number=volume_number,
            language="en",
            max_chapters=1  # Only download one chapter for testing
        )
        
        await downloader.close()
        
        if not download_result["success"]:
            raise Exception(f"Failed to download volume: {download_result.get('message', 'Unknown error')}")
        
        self.log(f"Successfully downloaded chapter from volume {volume_number}")
        self.log(f"Downloaded files in: {download_result['volume_path']}")
        
        self.log("Download test passed")


class EpubTest(TestCase):
    """Test EPUB generation."""
    
    def __init__(self, manga_id: Optional[str] = None, temp_dir: Optional[str] = None):
        """Initialize test case.
        
        Args:
            manga_id: Optional manga ID to use for testing. If None, a default ID will be used.
            temp_dir: Optional temporary directory for downloads. If None, a default directory will be used.
        """
        super().__init__(
            name="EPUB Test",
            description="Tests EPUB generation functionality"
        )
        # One Piece manga ID as default (use a series with shorter chapters for testing)
        self.manga_id = manga_id or "32d76d19-8a05-4db0-9fc2-e0b0648fe9d0"
        
        # Use temporary directory
        self.temp_dir = temp_dir or Path.home() / ".mangabook" / "test"
    
    async def execute(self) -> None:
        """Execute the test case."""
        self.log(f"Testing EPUB generation for manga ID: {self.manga_id}")
        
        # Ensure test directory exists
        os.makedirs(self.temp_dir, exist_ok=True)
        
        # Get manga details
        details = await get_manga_details(self.manga_id)
        manga_title = details["title"]
        
        # Get volumes
        volumes = await get_volumes(self.manga_id)
        
        # Find first valid volume
        volume_number = None
        for vol, info in volumes.items():
            if vol != "null" and vol != "None" and vol != "Unknown":
                volume_number = vol
                break
        
        if not volume_number:
            self.log("No valid volumes found, using chapter 1 instead")
            volume_number = "1"
        
        # Process manga with limited chapters
        self.log(f"Processing volume {volume_number} of {manga_title}")
        
        result = await process_manga(
            manga_id=self.manga_id,
            manga_title=manga_title,
            volumes=[volume_number],
            output_dir=str(self.temp_dir),
            keep_raw=False,
            quality=85,
            kobo=True,
            language="en",
            validate=True
        )
        
        if result.get("failed", 0) > 0 and result.get("successful", 0) == 0:
            raise Exception("EPUB generation failed")
        
        self.log(f"Generated {len(result.get('epub_files', []))} EPUB files")
        
        for epub_file in result.get("epub_files", []):
            self.log(f"Generated EPUB: {epub_file}")
            
            # Validate EPUB
            validation_result = await validate_epub(epub_file)
            
            if validation_result.get("valid") is True:
                self.log(f"EPUB validation: Passed")
            elif validation_result.get("valid") is False:
                self.log(f"EPUB validation: Failed - {validation_result.get('error', 'Unknown error')}")
            else:
                self.log("EPUB validation: Skipped (epubcheck not available)")
        
        self.log("EPUB test passed")


class EnvironmentTest(TestCase):
    """Test environment configuration."""
    
    def __init__(self):
        """Initialize test case."""
        super().__init__(
            name="Environment Test",
            description="Tests environment configuration"
        )
    
    async def execute(self) -> None:
        """Execute the test case."""
        self.log("Testing environment configuration...")
        
        # Check environment
        env = await check_environment()
        
        # Check API connection
        if not env.get("api", {}).get("accessible", False):
            raise Exception("MangaDex API is not accessible")
        
        self.log("MangaDex API is accessible")
        
        # Check dependencies
        for package, status in env.get("dependencies", {}).items():
            if status.get("installed", False):
                self.log(f"Dependency {package}: Installed")
            else:
                self.log(f"Dependency {package}: Not installed")
        
        # Check tools
        for tool, status in env.get("tools", {}).items():
            if status.get("available", False):
                self.log(f"Tool {tool}: Available")
            else:
                self.log(f"Tool {tool}: Not available")
        
        self.log("Environment test passed")


class ConfigTest(TestCase):
    """Test configuration functionality."""
    
    def __init__(self):
        """Initialize test case."""
        super().__init__(
            name="Config Test",
            description="Tests configuration functionality"
        )
    
    async def execute(self) -> None:
        """Execute the test case."""
        self.log("Testing configuration functionality...")
        
        # Test config initialization
        config = Config()
        self.log(f"Config directory: {config.config_dir}")
        
        # Test config save and load
        test_key = "test_key"
        test_value = f"test_value_{int(time.time())}"
        
        config.set(test_key, test_value)
        self.log(f"Set config: {test_key}={test_value}")
        
        config.save()
        self.log("Saved config")
        
        # Create new config instance and load
        config2 = Config()
        loaded_value = config2.get(test_key)
        
        if loaded_value != test_value:
            raise Exception(f"Config value mismatch: expected '{test_value}', got '{loaded_value}'")
        
        self.log(f"Loaded config value: {test_key}={loaded_value}")
        
        # Clean up test value
        config2.remove(test_key)
        config2.save()
        self.log(f"Removed test value: {test_key}")
        
        self.log("Config test passed")


async def run_tests(test_cases: List[TestCase], fail_fast: bool = False) -> Dict[str, Any]:
    """Run all test cases.
    
    Args:
        test_cases: List of test cases to run.
        fail_fast: Whether to stop on first failure.
        
    Returns:
        Dict with test results.
    """
    results = {
        "total": len(test_cases),
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "tests": []
    }
    
    for i, test in enumerate(test_cases):
        click.echo(f"\nRunning test {i+1}/{len(test_cases)}: {test.name}")
        click.echo(f"Description: {test.description}")
        
        try:
            test_result = await test.run()
            results["tests"].append(test_result)
            
            if test_result["passed"]:
                results["passed"] += 1
                click.secho(f"✅ Test passed in {test_result['duration']}s", fg="green")
            else:
                results["failed"] += 1
                click.secho(f"❌ Test failed in {test_result['duration']}s: {test_result['error']}", fg="red")
                
                if fail_fast:
                    click.secho("Stopping tests due to failure (fail-fast enabled)", fg="yellow")
                    break
        except Exception as e:
            results["failed"] += 1
            click.secho(f"❌ Test crashed: {str(e)}", fg="red")
            
            if fail_fast:
                click.secho("Stopping tests due to failure (fail-fast enabled)", fg="yellow")
                break
    
    # Update skipped count
    results["skipped"] = results["total"] - results["passed"] - results["failed"]
    
    return results


def display_test_results(results: Dict[str, Any]) -> None:
    """Display test results.
    
    Args:
        results: Test results.
    """
    click.echo("\n" + "="*60)
    click.secho("📊 Test Results", fg="bright_blue", bold=True)
    click.echo("="*60)
    
    click.echo(f"Total tests: {results['total']}")
    click.secho(f"Passed: {results['passed']}", fg="green")
    click.secho(f"Failed: {results['failed']}", fg="red" if results["failed"] > 0 else "white")
    click.secho(f"Skipped: {results['skipped']}", fg="yellow" if results["skipped"] > 0 else "white")
    
    click.echo("\nTest Details:")
    click.echo("-"*60)
    
    for test in results["tests"]:
        status = "✅ PASS" if test["passed"] else "❌ FAIL"
        status_color = "green" if test["passed"] else "red"
        
        click.secho(f"{status} - {test['name']} ({test['duration']}s)", fg=status_color)
        
        # Show error if test failed
        if not test["passed"] and test.get("error"):
            click.secho(f"  Error: {test['error']}", fg="red")
        
        # Show test output in verbose mode
        if test.get("output") and error_handler.debug:
            click.echo("  Output:")
            for line in test["output"].split("\n"):
                if line:
                    click.echo(f"    {line}")
    
    click.echo("="*60)


def save_test_results(results: Dict[str, Any], output_file: str) -> None:
    """Save test results to a file.
    
    Args:
        results: Test results.
        output_file: Output file path.
    """
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)


async def run_all_tests(temp_dir: Optional[str] = None, fail_fast: bool = False,
                       output_file: Optional[str] = None) -> Dict[str, Any]:
    """Run all tests.
    
    Args:
        temp_dir: Optional temporary directory for test files.
        fail_fast: Whether to stop on first failure.
        output_file: Optional file to save test results to.
        
    Returns:
        Dict with test results.
    """
    # Create tests
    tests = [
        EnvironmentTest(),
        ConfigTest(),
        ApiConnectionTest(),
        SearchTest(),
        MangaDetailsTest(),
        DownloadTest(temp_dir=temp_dir),
        EpubTest(temp_dir=temp_dir)
    ]
    
    # Run tests
    results = await run_tests(tests, fail_fast=fail_fast)
    
    # Display results
    display_test_results(results)
    
    # Save results if requested
    if output_file:
        save_test_results(results, output_file)
        click.echo(f"\nTest results saved to: {output_file}")
    
    return results


async def run_test_command(temp_dir: Optional[str] = None, fail_fast: bool = False,
                         output_file: Optional[str] = None) -> None:
    """Run test command implementation.
    
    Args:
        temp_dir: Optional temporary directory for test files.
        fail_fast: Whether to stop on first failure.
        output_file: Optional file to save test results to.
    """
    # Default to temp directory in .mangabook folder
    if not temp_dir:
        temp_dir = str(Path.home() / ".mangabook" / "test")
    
    # Ensure test directory exists
    os.makedirs(temp_dir, exist_ok=True)
    
    click.echo(f"Running MangaBook tests (temp dir: {temp_dir})")
    
    # Run all tests
    results = await run_all_tests(
        temp_dir=temp_dir,
        fail_fast=fail_fast,
        output_file=output_file
    )
    
    # Exit with error code if any tests failed
    if results["failed"] > 0:
        sys.exit(1)
