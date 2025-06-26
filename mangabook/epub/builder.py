"""EPUB building functionality.

This module provides a class for generating EPUB files from manga images,
with proper metadata, navigation, and styling.
"""

import os
import logging
import uuid
import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Union, Set
import io
from collections import OrderedDict

import ebooklib
from ebooklib import epub

from ..utils import sanitize_filename, ensure_directory

# Set up logging
logger = logging.getLogger(__name__)

# Constants
DEFAULT_CSS = """
@namespace h "http://www.w3.org/1999/xhtml";
body {
    margin: 0;
    padding: 0;
    text-align: center;
}
div.image {
    margin: 0;
    padding: 0;
    text-align: center;
    page-break-after: always;
}
img {
    margin: 0;
    padding: 0;
    max-width: 100%;
    max-height: 100%;
}
"""

COVER_CSS = """
@namespace h "http://www.w3.org/1999/xhtml";
body {
    margin: 0;
    padding: 0;
    text-align: center;
}
div.cover {
    margin: 0;
    padding: 0;
    text-align: center;
}
img {
    margin: 0;
    padding: 0;
    max-width: 100%;
    max-height: 100%;
}
"""


class EPUBBuilder:
    """Builds EPUB files from manga images."""
    
    def __init__(self, title: str, output_dir: Union[str, Path], 
                language: str = 'en', author: str = 'Unknown',
                identifier: Optional[str] = None, publisher: str = 'MangaBook'):
        """Initialize the EPUB builder.
        
        Args:
            title: Title of the manga.
            output_dir: Directory to save the EPUB.
            language: Language code for the EPUB.
            author: Author of the manga.
            identifier: Unique identifier for the EPUB.
            publisher: Publisher name.
        """
        self.title = title
        self.output_dir = Path(output_dir)
        self.language = language
        self.author = author
        self.identifier = identifier or str(uuid.uuid4())
        self.publisher = publisher
        
        self.book = None
        self.images = []
        self.chapters = OrderedDict()
        self.toc = []
        self.cover_image = None
        self.spine = []
        self.reading_direction = 'rtl'  # Default for manga
        
        # Ensure output directory exists
        ensure_directory(self.output_dir)
    
    def _init_book(self) -> None:
        """Initialize the EPUB book."""
        self.book = epub.EpubBook()
        
        # Set metadata
        self.book.set_identifier(self.identifier)
        self.book.set_title(self.title)
        self.book.set_language(self.language)
        self.book.add_author(self.author)
        self.book.add_metadata('DC', 'publisher', self.publisher)
        self.book.add_metadata('DC', 'date', datetime.datetime.now().strftime('%Y-%m-%d'))
        self.book.add_metadata(None, 'meta', '', {
            'name': 'generator',
            'content': 'MangaBook'
        })
        
        # Set reading direction
        if self.reading_direction == 'rtl':
            self.book.set_direction('rtl')
            self.book.add_metadata(None, 'meta', '', {
                'name': 'primary-writing-mode', 
                'content': 'vertical-rl'
            })
        
        # Add default CSS
        css_file = epub.EpubItem(
            uid="style_default",
            file_name="style/default.css",
            media_type="text/css",
            content=DEFAULT_CSS
        )
        self.book.add_item(css_file)
        
        # Add cover CSS
        cover_css = epub.EpubItem(
            uid="style_cover",
            file_name="style/cover.css",
            media_type="text/css",
            content=COVER_CSS
        )
        self.book.add_item(cover_css)
    
    def set_cover(self, image_path: Union[str, Path]) -> None:
        """Set the cover image for the EPUB.
        
        Args:
            image_path: Path to the cover image.
        """
        image_path = Path(image_path)
        if not image_path.exists():
            logger.error(f"Cover image not found: {image_path}")
            return
        
        try:
            # Save the path for later
            self.cover_image = image_path
            
            # Initialize book if not already done
            if self.book is None:
                self._init_book()
            
            # Read the cover image
            with open(image_path, 'rb') as f:
                cover_data = f.read()
            
            # Determine media type
            media_type = f"image/{image_path.suffix.lower()[1:]}"
            if image_path.suffix.lower() == '.jpg' or image_path.suffix.lower() == '.jpeg':
                media_type = "image/jpeg"
            
            # Add the cover image to the book
            self.book.set_cover("cover.jpg", cover_data, media_type)
            
            # Create a cover page
            cover_page = self._create_image_page("cover", "cover.jpg", "Cover")
            self.book.add_item(cover_page)
            self.spine.append(cover_page)
            
            logger.debug(f"Cover set: {image_path}")
        except Exception as e:
            logger.error(f"Error setting cover: {e}")
    
    def add_image(self, image_path: Union[str, Path], chapter_id: str = "default") -> None:
        """Add an image to the EPUB.
        
        Args:
            image_path: Path to the image.
            chapter_id: ID of the chapter to add the image to.
        """
        image_path = Path(image_path)
        if not image_path.exists():
            logger.error(f"Image not found: {image_path}")
            return
        
        try:
            # Initialize book if not already done
            if self.book is None:
                self._init_book()
            
            # Initialize chapter if it doesn't exist
            if chapter_id not in self.chapters:
                self.chapters[chapter_id] = []
            
            # Add the image to the book
            image_filename = f"images/{chapter_id}/{image_path.name}"
            
            # Determine media type
            media_type = f"image/{image_path.suffix.lower()[1:]}"
            if image_path.suffix.lower() == '.jpg' or image_path.suffix.lower() == '.jpeg':
                media_type = "image/jpeg"
            
            # Create an image item
            image_item = epub.EpubImage(
                uid=f"image_{len(self.images)}",
                file_name=image_filename,
                media_type=media_type,
                content=open(image_path, 'rb').read()
            )
            self.book.add_item(image_item)
            self.images.append(image_item)
            
            # Create a page for the image
            image_page = self._create_image_page(
                f"{chapter_id}_{len(self.chapters[chapter_id])}",
                image_filename
            )
            self.book.add_item(image_page)
            self.chapters[chapter_id].append(image_page)
            self.spine.append(image_page)
            
            logger.debug(f"Image added: {image_path}")
        except Exception as e:
            logger.error(f"Error adding image: {e}")
    
    def add_chapter(self, chapter_id: str, title: str, images: List[Union[str, Path]]) -> None:
        """Add a chapter with multiple images to the EPUB.
        
        Args:
            chapter_id: ID of the chapter.
            title: Title of the chapter.
            images: List of paths to images.
        """
        # Initialize book if not already done
        if self.book is None:
            self._init_book()
        
        # Initialize chapter
        self.chapters[chapter_id] = []
        
        # Add the images to the chapter
        for image_path in images:
            self.add_image(image_path, chapter_id)
        
        # Create a chapter TOC entry
        if self.chapters[chapter_id]:
            first_page = self.chapters[chapter_id][0]
            chapter_toc = epub.Link(first_page.file_name, title, chapter_id)
            self.toc.append(chapter_toc)
            
            logger.debug(f"Chapter added: {title} with {len(images)} images")
    
    def _create_image_page(self, uid: str, image_path: str, title: Optional[str] = None) -> epub.EpubHtml:
        """Create an HTML page for an image.
        
        Args:
            uid: Unique identifier for the page.
            image_path: Path to the image.
            title: Optional title for the page.
            
        Returns:
            epub.EpubHtml: The created page.
        """
        page = epub.EpubHtml(
            title=title or f"Page {uid}",
            file_name=f"pages/{uid}.xhtml",
            lang=self.language
        )
        
        # Generate the HTML content
        page.content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
    <title>{title or f"Page {uid}"}</title>
    <link rel="stylesheet" type="text/css" href="../style/default.css" />
</head>
<body>
    <div class="image">
        <img src="../{image_path}" alt="{title or f"Page {uid}"}" />
    </div>
</body>
</html>"""
        
        # Set properties
        page.add_item("style_default")
        
        return page
    
    def finalize(self) -> None:
        """Finalize the EPUB book structure."""
        # Initialize book if not already done
        if self.book is None:
            self._init_book()
        
        # Set the spine
        self.book.spine = self.spine
        
        # Create the table of contents
        self.book.toc = self.toc
        
        # Add navigation files
        self.book.add_item(epub.EpubNcx())
        self.book.add_item(epub.EpubNav())
        
        logger.debug("EPUB structure finalized")
    
    def write(self, filename: Optional[str] = None) -> str:
        """Write the EPUB file.
        
        Args:
            filename: Optional filename for the EPUB.
            
        Returns:
            str: Path to the written EPUB file.
        """
        # Finalize if not already done
        if not self.book.spine:
            self.finalize()
        
        # Determine filename
        if filename is None:
            filename = sanitize_filename(self.title) + ".epub"
        
        # Ensure it has the .epub extension
        if not filename.lower().endswith('.epub'):
            filename += ".epub"
        
        # Generate the full path
        filepath = self.output_dir / filename
        
        # Write the EPUB
        try:
            epub.write_epub(str(filepath), self.book, {})
            logger.info(f"EPUB written to {filepath}")
            return str(filepath)
        except Exception as e:
            logger.error(f"Error writing EPUB: {e}")
            raise
    
    def set_reading_direction(self, direction: str) -> None:
        """Set the reading direction for the EPUB.
        
        Args:
            direction: Reading direction ('rtl' or 'ltr').
        """
        if direction not in ('rtl', 'ltr'):
            logger.warning(f"Invalid reading direction: {direction}, using 'rtl'")
            direction = 'rtl'
        
        self.reading_direction = direction
        
        # Update the book if it already exists
        if self.book is not None:
            if direction == 'rtl':
                self.book.set_direction('rtl')
                self.book.add_metadata(None, 'meta', '', {
                    'name': 'primary-writing-mode', 
                    'content': 'vertical-rl'
                })
            else:
                self.book.set_direction('ltr')
                # Remove any existing writing mode metadata
                for meta in self.book.metadata:
                    if meta[0] is None and meta[1] == 'meta' and meta[3].get('name') == 'primary-writing-mode':
                        self.book.metadata.remove(meta)
                        break
        
        logger.debug(f"Reading direction set to {direction}")
    
    def add_metadata(self, namespace: str, name: str, value: str, attributes: Optional[Dict] = None) -> None:
        """Add custom metadata to the EPUB.
        
        Args:
            namespace: Metadata namespace.
            name: Metadata name.
            value: Metadata value.
            attributes: Optional attributes.
        """
        # Initialize book if not already done
        if self.book is None:
            self._init_book()
        
        self.book.add_metadata(namespace, name, value, attributes or {})
        logger.debug(f"Added metadata: {namespace}:{name} = {value}")
    
    @staticmethod
    def create_from_images(title: str, output_dir: Union[str, Path], images: List[Union[str, Path]],
                          language: str = 'en', author: str = 'Unknown',
                          identifier: Optional[str] = None, publisher: str = 'MangaBook',
                          cover_image: Optional[Union[str, Path]] = None,
                          reading_direction: str = 'rtl') -> str:
        """Create an EPUB from a list of images.
        
        Args:
            title: Title of the manga.
            output_dir: Directory to save the EPUB.
            images: List of paths to images.
            language: Language code for the EPUB.
            author: Author of the manga.
            identifier: Unique identifier for the EPUB.
            publisher: Publisher name.
            cover_image: Optional path to cover image.
            reading_direction: Reading direction ('rtl' or 'ltr').
            
        Returns:
            str: Path to the written EPUB file.
        """
        builder = EPUBBuilder(title, output_dir, language, author, identifier, publisher)
        builder.set_reading_direction(reading_direction)
        
        # Set cover if provided
        if cover_image:
            builder.set_cover(cover_image)
        elif images:
            # Use the first image as cover if no specific cover provided
            builder.set_cover(images[0])
            # Skip the first image since it's used as cover
            images = images[1:]
        
        # Add images
        for image in images:
            builder.add_image(image)
        
        # Write EPUB
        return builder.write()
