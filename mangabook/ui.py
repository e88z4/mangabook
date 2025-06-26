"""User interface utilities for MangaBook.

This module provides utilities for enhancing the user interface, including
colored output, progress indicators, and ETA calculations.
"""

import sys
import time
from typing import Dict, Any, List, Optional, Union, Tuple, Callable
import click
from tqdm import tqdm
from datetime import datetime, timedelta

# Define color constants for CLI output
class Colors:
    """ANSI color codes for terminal output."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"
    
    # Foreground colors
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    
    # Background colors
    BG_BLACK = "\033[40m"
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"
    BG_MAGENTA = "\033[45m"
    BG_CYAN = "\033[46m"
    BG_WHITE = "\033[47m"
    
    # Bright foreground colors
    BRIGHT_BLACK = "\033[90m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"


class ColorfulFormatter:
    """Formats text with colors for terminal output."""
    
    @staticmethod
    def info(text: str) -> str:
        """Format info text.
        
        Args:
            text: Text to format.
            
        Returns:
            Formatted text.
        """
        return f"{Colors.CYAN}{text}{Colors.RESET}"
    
    @staticmethod
    def success(text: str) -> str:
        """Format success text.
        
        Args:
            text: Text to format.
            
        Returns:
            Formatted text.
        """
        return f"{Colors.GREEN}{text}{Colors.RESET}"
    
    @staticmethod
    def warning(text: str) -> str:
        """Format warning text.
        
        Args:
            text: Text to format.
            
        Returns:
            Formatted text.
        """
        return f"{Colors.YELLOW}{text}{Colors.RESET}"
    
    @staticmethod
    def error(text: str) -> str:
        """Format error text.
        
        Args:
            text: Text to format.
            
        Returns:
            Formatted text.
        """
        return f"{Colors.RED}{text}{Colors.RESET}"
    
    @staticmethod
    def highlight(text: str) -> str:
        """Format highlighted text.
        
        Args:
            text: Text to format.
            
        Returns:
            Formatted text.
        """
        return f"{Colors.BOLD}{Colors.BRIGHT_WHITE}{text}{Colors.RESET}"
    
    @staticmethod
    def manga_title(text: str) -> str:
        """Format manga title.
        
        Args:
            text: Text to format.
            
        Returns:
            Formatted text.
        """
        return f"{Colors.BOLD}{Colors.BRIGHT_CYAN}{text}{Colors.RESET}"
    
    @staticmethod
    def volume(text: str) -> str:
        """Format volume text.
        
        Args:
            text: Text to format.
            
        Returns:
            Formatted text.
        """
        return f"{Colors.MAGENTA}{text}{Colors.RESET}"
    
    @staticmethod
    def chapter(text: str) -> str:
        """Format chapter text.
        
        Args:
            text: Text to format.
            
        Returns:
            Formatted text.
        """
        return f"{Colors.BRIGHT_BLUE}{text}{Colors.RESET}"
    
    @staticmethod
    def dim(text: str) -> str:
        """Format dimmed text.
        
        Args:
            text: Text to format.
            
        Returns:
            Formatted text.
        """
        return f"{Colors.DIM}{text}{Colors.RESET}"
    
    @staticmethod
    def progress(current: int, total: int, label: str = "") -> str:
        """Format progress text.
        
        Args:
            current: Current progress.
            total: Total progress.
            label: Label for progress.
            
        Returns:
            Formatted text.
        """
        percent = (current / total) * 100 if total > 0 else 0
        progress_text = f"{current}/{total} ({percent:.1f}%)"
        
        if label:
            return f"{label}: {Colors.BRIGHT_GREEN}{progress_text}{Colors.RESET}"
        else:
            return f"{Colors.BRIGHT_GREEN}{progress_text}{Colors.RESET}"
    
    @staticmethod
    def table_header(text: str) -> str:
        """Format table header.
        
        Args:
            text: Text to format.
            
        Returns:
            Formatted text.
        """
        return f"{Colors.BOLD}{Colors.BRIGHT_WHITE}{text}{Colors.RESET}"
    
    @staticmethod
    def table_row(texts: List[str], alternate: bool = False) -> List[str]:
        """Format table row.
        
        Args:
            texts: List of texts to format.
            alternate: Whether this is an alternate row.
            
        Returns:
            List of formatted texts.
        """
        if alternate:
            return [f"{Colors.DIM}{text}{Colors.RESET}" for text in texts]
        else:
            return [text for text in texts]


class EnhancedProgress:
    """Enhanced progress bar with ETA calculation."""
    
    def __init__(self, total: int, desc: str = "", unit: str = "it", 
               color: bool = True, show_eta: bool = True):
        """Initialize enhanced progress bar.
        
        Args:
            total: Total number of items.
            desc: Description.
            unit: Unit of items.
            color: Whether to use colors.
            show_eta: Whether to show ETA.
        """
        self.total = total
        self.desc = desc
        self.unit = unit
        self.color = color
        self.show_eta = show_eta
        self.start_time = time.time()
        self.last_update = self.start_time
        self.n = 0
        self.completed = False
        
        # Initialize progress bar
        bar_format = None
        if show_eta:
            bar_format = "{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}{postfix}]"
            
        self.pbar = tqdm(total=total, desc=desc, unit=unit, bar_format=bar_format)
    
    def update(self, n: int = 1) -> None:
        """Update progress.
        
        Args:
            n: Number of items to increment by.
        """
        self.n += n
        self.last_update = time.time()
        self.pbar.update(n)
        
        if self.show_eta:
            self._update_eta()
    
    def _update_eta(self) -> None:
        """Update ETA calculation."""
        elapsed = time.time() - self.start_time
        rate = self.n / elapsed if elapsed > 0 else 0
        
        if rate > 0:
            remaining = (self.total - self.n) / rate
            eta = datetime.now() + timedelta(seconds=remaining)
            eta_str = eta.strftime('%H:%M:%S')
            
            self.pbar.set_postfix(eta=eta_str)
    
    def close(self) -> None:
        """Close progress bar."""
        self.completed = True
        self.pbar.close()


def print_info(message: str) -> None:
    """Print info message.
    
    Args:
        message: Message to print.
    """
    click.echo(ColorfulFormatter.info(message))


def print_success(message: str) -> None:
    """Print success message.
    
    Args:
        message: Message to print.
    """
    click.echo(ColorfulFormatter.success(message))


def print_warning(message: str) -> None:
    """Print warning message.
    
    Args:
        message: Message to print.
    """
    click.echo(ColorfulFormatter.warning(message))


def print_error(message: str) -> None:
    """Print error message.
    
    Args:
        message: Message to print.
    """
    click.echo(ColorfulFormatter.error(message))


def print_manga_title(title: str) -> None:
    """Print manga title.
    
    Args:
        title: Title to print.
    """
    click.echo(ColorfulFormatter.manga_title(title))


def print_header(text: str, width: int = 80, 
               char: str = "=", color: str = Colors.BRIGHT_CYAN) -> None:
    """Print header with separator lines.
    
    Args:
        text: Header text.
        width: Width of separator.
        char: Character for separator.
        color: Color for header.
    """
    separator = char * width
    click.echo(f"{color}{separator}{Colors.RESET}")
    click.echo(f"{color}{text.center(width)}{Colors.RESET}")
    click.echo(f"{color}{separator}{Colors.RESET}")
