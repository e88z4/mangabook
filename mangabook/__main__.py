"""Main entry point for MangaBook CLI."""

import sys
import logging
import traceback
import asyncio
from pathlib import Path
import click

from .cli import cli
from .error import error_handler, ErrorCategory
from .api import close_global_api

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
    finally:
        # Ensure the global API instance is closed
        try:
            asyncio.run(close_global_api())
        except Exception as e:
            # Don't let API cleanup errors crash the app
            if error_handler.debug:
                click.echo(f"Error during API cleanup: {e}")

if __name__ == "__main__":
    # Entry point for MangaBook CLI
    main()
