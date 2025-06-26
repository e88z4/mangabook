"""Error handling for MangaBook.

This module provides error handling and logging functionality for MangaBook,
including error categorization, recovery mechanisms, and improved user feedback.
"""

import logging
import sys
import traceback
from enum import Enum
from typing import Dict, Any, Optional, Callable, List, TypeVar, Union
from dataclasses import dataclass
import click
from pathlib import Path

# Type variable for generic functions
T = TypeVar('T')

# Set up logging
logger = logging.getLogger(__name__)


class ErrorCategory(Enum):
    """Categories of errors that can occur in MangaBook."""
    
    NETWORK = "network"  # Network-related errors (API calls, downloads)
    AUTHENTICATION = "auth"  # Authentication errors
    FILE_SYSTEM = "fs"  # File system errors (read/write)
    VALIDATION = "validation"  # Data validation errors
    CONVERSION = "conversion"  # Image/EPUB conversion errors
    PERMISSION = "permission"  # Permission errors
    RESOURCE = "resource"  # Resource errors (e.g., memory, disk space)
    EXTERNAL = "external"  # External tool/dependency errors
    UNEXPECTED = "unexpected"  # Unexpected errors
    USER_INPUT = "input"  # User input errors


@dataclass
class MangaBookError(Exception):
    """Custom exception class for MangaBook errors."""
    
    message: str
    category: ErrorCategory
    original_error: Optional[Exception] = None
    details: Optional[Dict[str, Any]] = None
    recoverable: bool = True
    
    def __post_init__(self):
        super().__init__(self.message)
    
    def __str__(self) -> str:
        return f"{self.message} [{self.category.value}]"


class ErrorHandler:
    """Error handler for MangaBook operations."""
    
    def __init__(self, debug: bool = False):
        """Initialize error handler.
        
        Args:
            debug: Whether to enable debug mode.
        """
        self.debug = debug
        self.error_log: List[MangaBookError] = []
        self.log_file: Optional[Path] = None
    
    def set_log_file(self, log_file: Union[str, Path]) -> None:
        """Set log file path.
        
        Args:
            log_file: Path to log file.
        """
        self.log_file = Path(log_file)
        
        # Set up file handler
        file_handler = logging.FileHandler(self.log_file)
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        ))
        
        # Add handler to root logger
        root_logger = logging.getLogger()
        root_logger.addHandler(file_handler)
    
    def handle(self, error: Exception, category: ErrorCategory = ErrorCategory.UNEXPECTED,
               details: Optional[Dict[str, Any]] = None, recoverable: bool = True) -> MangaBookError:
        """Handle an exception and convert it to MangaBookError.
        
        Args:
            error: The original exception.
            category: The error category.
            details: Additional details about the error.
            recoverable: Whether the error is recoverable.
            
        Returns:
            MangaBookError: The handled error.
        """
        # Create MangaBookError
        mb_error = MangaBookError(
            message=str(error),
            category=category,
            original_error=error,
            details=details or {},
            recoverable=recoverable
        )
        
        # Add to error log
        self.error_log.append(mb_error)
        
        # Log error
        logger.error(f"{mb_error} - {'Recoverable' if recoverable else 'Fatal'}")
        
        if self.debug:
            logger.debug(f"Details: {details}")
            logger.debug(f"Traceback: {traceback.format_exc()}")
        
        return mb_error
    
    def display_error(self, error: MangaBookError) -> None:
        """Display error to user with appropriate formatting.
        
        Args:
            error: The error to display.
        """
        # Format error message based on category
        category_display = {
            ErrorCategory.NETWORK: "⚠️ Network Error",
            ErrorCategory.AUTHENTICATION: "🔒 Authentication Error",
            ErrorCategory.FILE_SYSTEM: "📁 File System Error",
            ErrorCategory.VALIDATION: "❌ Validation Error",
            ErrorCategory.CONVERSION: "🔄 Conversion Error",
            ErrorCategory.PERMISSION: "🚫 Permission Error",
            ErrorCategory.RESOURCE: "📉 Resource Error",
            ErrorCategory.EXTERNAL: "🔌 External Tool Error",
            ErrorCategory.USER_INPUT: "⌨️ Input Error",
            ErrorCategory.UNEXPECTED: "❓ Unexpected Error"
        }
        
        # Display error using click
        click.secho(category_display.get(error.category, "Error"), fg="yellow", bold=True)
        click.secho(f"{error.message}", fg="red")
        
        # Show details in debug mode
        if self.debug and error.details:
            click.echo("Details:")
            for key, value in error.details.items():
                click.echo(f"  - {key}: {value}")
        
        # Show recovery message
        if error.recoverable:
            click.echo("The operation can continue despite this error.")
        else:
            click.secho("This error prevents the operation from continuing.", fg="red")
    
    def safe_execute(self, func: Callable[..., T], *args, 
                    error_category: ErrorCategory = ErrorCategory.UNEXPECTED,
                    display: bool = True, **kwargs) -> Optional[T]:
        """Safely execute a function and handle any exceptions.
        
        Args:
            func: Function to execute.
            *args: Arguments to pass to the function.
            error_category: Category of error if one occurs.
            display: Whether to display errors to the user.
            **kwargs: Keyword arguments to pass to the function.
            
        Returns:
            The result of the function, or None if an exception occurred.
        """
        try:
            return func(*args, **kwargs)
        except Exception as e:
            error = self.handle(e, category=error_category)
            if display:
                self.display_error(error)
            return None
    
    async def safe_execute_async(self, func: Callable[..., T], *args, 
                               error_category: ErrorCategory = ErrorCategory.UNEXPECTED,
                               display: bool = True, **kwargs) -> Optional[T]:
        """Safely execute an async function and handle any exceptions.
        
        Args:
            func: Async function to execute.
            *args: Arguments to pass to the function.
            error_category: Category of error if one occurs.
            display: Whether to display errors to the user.
            **kwargs: Keyword arguments to pass to the function.
            
        Returns:
            The result of the function, or None if an exception occurred.
        """
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            error = self.handle(e, category=error_category)
            if display:
                self.display_error(error)
            return None
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary of errors.
        
        Returns:
            Dict with error summary information.
        """
        # Group errors by category
        errors_by_category = {}
        for error in self.error_log:
            if error.category.value not in errors_by_category:
                errors_by_category[error.category.value] = []
            errors_by_category[error.category.value].append(error.message)
        
        return {
            "total_errors": len(self.error_log),
            "fatal_errors": sum(1 for e in self.error_log if not e.recoverable),
            "categories": errors_by_category,
            "log_file": str(self.log_file) if self.log_file else None
        }
    
    def display_summary(self) -> None:
        """Display error summary to user."""
        summary = self.get_summary()
        
        if not summary["total_errors"]:
            click.echo("✅ No errors occurred during the operation.")
            return
        
        click.echo("\n📊 Error Summary:")
        click.secho(f"Total errors: {summary['total_errors']}", fg="yellow")
        click.secho(f"Fatal errors: {summary['fatal_errors']}", 
                   fg="red" if summary["fatal_errors"] else "green")
        
        click.echo("\nErrors by category:")
        for category, messages in summary.get("categories", {}).items():
            click.secho(f"{category}: {len(messages)}", fg="yellow")
            if self.debug:
                for i, msg in enumerate(messages):
                    click.echo(f"  {i+1}. {msg}")
        
        if summary.get("log_file"):
            click.echo(f"\nFull error log saved to: {summary['log_file']}")


# Create global error handler
error_handler = ErrorHandler()


def initialize_error_handler(debug: bool = False, log_dir: Optional[str] = None) -> ErrorHandler:
    """Initialize global error handler.
    
    Args:
        debug: Whether to enable debug mode.
        log_dir: Directory for log files.
    
    Returns:
        The initialized error handler.
    """
    global error_handler
    
    error_handler.debug = debug
    
    if log_dir:
        # Create log directory if it doesn't exist
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        
        # Create log file with timestamp
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = log_path / f"mangabook_{timestamp}.log"
        
        error_handler.set_log_file(log_file)
    
    return error_handler
