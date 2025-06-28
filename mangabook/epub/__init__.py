"""EPUB generation package for MangaBook.

This package provides functionality for building EPUB and KEPUB files from manga images.
It includes standard and enhanced builder implementations with the latter being more robust
for large manga volumes with strict EPUB spec compliance.
"""

from .builder import EPUBBuilder
from .kobo import KepubBuilder
from .enhanced_builder import EnhancedEPUBBuilder, EnhancedKepubBuilder

__all__ = ['EPUBBuilder', 'KepubBuilder', 'EnhancedEPUBBuilder', 'EnhancedKepubBuilder']
