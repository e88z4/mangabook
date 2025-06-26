"""Main entry point for MangaBook CLI."""

import sys
import logging
import traceback
from pathlib import Path
import click

from .cli import cli
from .error import error_handler, ErrorCategory

def main():
    """Main entry point with error handling."""
    try:
        # Run the CLI
        cli(obj={})
    except Exception as e:
        # Handle any uncaught exceptions
        error = error_handler.handle(
            e, 
            category=ErrorCategory.UNEXPECTED,
            recoverable=False
        )
        error_handler.display_error(error)
        
        # Print traceback in debug mode
        if error_handler.debug:
            click.echo("\nTraceback:")
            traceback.print_exc()
        
        # Exit with error code
        sys.exit(1)

if __name__ == "__main__":
    # Entry point for MangaBook CLI
    main()
