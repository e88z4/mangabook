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
        self.default_css = epub.EpubItem(
            uid="style_default",
            file_name="style/default.css",
            media_type="text/css",
            content=DEFAULT_CSS
        )
        self.book.add_item(self.default_css)
        
        # Add cover CSS
        self.cover_css = epub.EpubItem(
            uid="style_cover",
            file_name="style/cover.css",
            media_type="text/css",
            content=COVER_CSS
        )
        self.book.add_item(self.cover_css)
    
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
            
            # Add the image to the book with a unique filename to avoid collisions
            # Use chapter_id and image count to ensure uniqueness
            image_count = len(self.chapters[chapter_id])
            image_filename = f"images/{chapter_id}/{image_count:03d}_{image_path.name}"
            
            # Check if this image already exists in the book
            if any(item.file_name == image_filename for item in self.images):
                logger.warning(f"Image with filename {image_filename} already exists, generating unique name")
                image_filename = f"images/{chapter_id}/{image_count:03d}_{uuid.uuid4().hex[:8]}_{image_path.name}"
            
            # Determine media type
            media_type = f"image/{image_path.suffix.lower()[1:]}"
            if image_path.suffix.lower() == '.jpg' or image_path.suffix.lower() == '.jpeg':
                media_type = "image/jpeg"
            elif image_path.suffix.lower() == '.png':
                media_type = "image/png"
            
            # Create a unique ID for this image
            image_uid = f"image_{chapter_id}_{image_count:03d}"
            
            # Create an image item with unique ID
            image_item = epub.EpubImage(
                uid=image_uid,
                file_name=image_filename,
                media_type=media_type,
                content=open(image_path, 'rb').read()
            )
            
            # Add the item to the book
            self.book.add_item(image_item)
            self.images.append(image_item)
            
            # Create a page for the image with unique ID
            page_uid = f"{chapter_id}_{image_count:03d}"
            image_page = self._create_image_page(
                page_uid,
                image_filename
            )
            self.book.add_item(image_page)
            self.chapters[chapter_id].append(image_page)
            self.spine.append(image_page)
            
            logger.debug(f"Image added: {image_path} as {image_filename}")
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
        
        # Create a proper chapter structure and TOC entry
        if self.chapters[chapter_id]:
            first_page = self.chapters[chapter_id][0]
            
            # Create a chapter title page if needed
            chapter_title_page = epub.EpubHtml(
                uid=f"chapter_{chapter_id}",
                title=title,
                file_name=f"chapters/{chapter_id}.xhtml",
                lang=self.language
            )
            
            # Set content for the chapter title page
            chapter_title_page.content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
    <title>{title}</title>
    <link rel="stylesheet" type="text/css" href="../style/default.css" />
</head>
<body>
    <h1>{title}</h1>
    <p>
        <a href="../{first_page.file_name}">Start Reading</a>
    </p>
</body>
</html>"""
            
            # Add CSS to the chapter title page
            if hasattr(self, 'default_css'):
                chapter_title_page.add_item(self.default_css)
            
            # Add the chapter title page to the book
            self.book.add_item(chapter_title_page)
            
            # Add to the spine - the chapter title page comes before the first image of the chapter
            # Find the position of the first image in the spine and insert the title page before it
            if first_page in self.spine:
                position = self.spine.index(first_page)
                self.spine.insert(position, chapter_title_page)
            else:
                # If not found, add it at the end (shouldn't happen)
                self.spine.append(chapter_title_page)
            
            # Add chapter to the TOC
            chapter_toc = epub.Link(chapter_title_page.file_name, title, chapter_id)
            
            # Create a nested TOC structure if there are many pages
            if len(self.chapters[chapter_id]) > 5:
                # Create sub-items for pages
                subchapter_links = []
                
                # Group by tens to avoid too many entries
                for i in range(0, len(self.chapters[chapter_id]), 10):
                    end_idx = min(i + 9, len(self.chapters[chapter_id]) - 1)
                    page_range = f"Pages {i+1}-{end_idx+1}"
                    page = self.chapters[chapter_id][i]
                    subchapter_links.append(
                        epub.Link(page.file_name, page_range, f"{chapter_id}_pages_{i}")
                    )
                
                # Create chapter entry with sub-pages
                self.toc.append((chapter_toc, subchapter_links))
            else:
                # Just add the chapter as a single TOC entry
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
            uid=f"page_{uid}",
            title=title or f"Page {uid}",
            file_name=f"pages/{uid}.xhtml",
            lang=self.language
        )
        
        # Generate the HTML content with proper XHTML structure
        content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
    <title>{title or f"Page {uid}"}</title>
    <link rel="stylesheet" type="text/css" href="../style/default.css" />
</head>
<body>
    <div class="image">
        <img src="../{image_path}" alt="{title or f'Page {uid}'}" />
    </div>
</body>
</html>"""
        
        page.content = content
        
        # Set CSS for the page
        if hasattr(self, 'default_css'):
            page.add_item(self.default_css)
        
        return page
    
    def finalize(self) -> None:
        """Finalize the EPUB book structure."""
        # Initialize book if not already done
        if self.book is None:
            self._init_book()
        
        # Ensure we have a TOC
        if not self.toc and self.chapters:
            logger.warning("No TOC entries but chapters exist, creating simple TOC")
            # Create TOC entries for each chapter
            for chapter_id, pages in self.chapters.items():
                if pages:
                    first_page = pages[0]
                    chapter_toc = epub.Link(first_page.file_name, chapter_id, chapter_id)
                    self.toc.append(chapter_toc)
        
        # Set the TOC in the book
        self.book.toc = self.toc
        
        # Create navigation files
        nav_css = epub.EpubItem(
            uid="style_nav",
            file_name="style/nav.css",
            media_type="text/css",
            content="""
            nav#toc ol { list-style-type: none; }
            nav#landmarks ol { list-style-type: none; }
            """
        )
        self.book.add_item(nav_css)
        
        # Create and add NCX and Nav files with explicit content
        ncx = epub.EpubNcx()
        self.book.add_item(ncx)
        
        # Create custom Nav document with explicit content
        nav = epub.EpubNav()
        nav.add_item(nav_css)
        
        # Build the navigation content manually to avoid empty document issues
        nav_content = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
    <title>Navigation</title>
    <link rel="stylesheet" type="text/css" href="style/nav.css" />
</head>
<body>
    <nav epub:type="toc" id="toc">
        <h1>Table of Contents</h1>
        <ol>
"""
        
        # Add TOC entries
        for item in self.toc:
            if isinstance(item, epub.Link):
                nav_content += f'            <li><a href="{item.href}">{item.title}</a></li>\n'
            elif isinstance(item, tuple) and len(item) == 2:
                parent, children = item
                nav_content += f'            <li><a href="{parent.href}">{parent.title}</a>\n'
                nav_content += '                <ol>\n'
                for child in children:
                    nav_content += f'                    <li><a href="{child.href}">{child.title}</a></li>\n'
                nav_content += '                </ol>\n'
                nav_content += '            </li>\n'
        
        nav_content += """        </ol>
    </nav>
    <nav epub:type="landmarks" id="landmarks">
        <h1>Landmarks</h1>
        <ol>
            <li><a epub:type="toc" href="#toc">Table of Contents</a></li>
"""
        
        # Add cover if available
        if self.cover_image:
            nav_content += '            <li><a epub:type="cover" href="pages/cover.xhtml">Cover</a></li>\n'
        
        nav_content += """        </ol>
    </nav>
</body>
</html>"""
        
        # Set the nav content
        nav.content = nav_content
        self.book.add_item(nav)
        
        # Set the spine - make sure nav is included
        if nav not in self.spine:
            # Add the navigation document to the end of the spine
            self.spine.append(nav)
        self.book.spine = self.spine
        
        # Fix item id references in the spine
        for i, item in enumerate(self.book.spine):
            if isinstance(item, str):
                # Find the corresponding item in items
                for book_item in self.book.items:
                    if book_item.id == item:
                        self.book.spine[i] = book_item
                        break
        
        # Ensure spine has valid items
        self.book.spine = [item for item in self.book.spine if not isinstance(item, str)]
        
        logger.debug(f"EPUB structure finalized with {len(self.book.spine)} spine items and {len(self.book.toc)} TOC entries")
    
    def write(self, filename: Optional[str] = None) -> str:
        """Write the EPUB file.
        
        Args:
            filename: Optional filename for the EPUB.
            
        Returns:
            str: Path to the written EPUB file.
        """
        # Special case for navigation-only EPUB (should be very rare)
        is_navigation_only = not self.images and hasattr(self, 'book') and self.book is not None
        
        # Validate that we have content to write
        if not self.images and not is_navigation_only:
            logger.error("No content to write to EPUB")
            raise ValueError("No content to write to EPUB")
        
        # Finalize if not already done
        if not hasattr(self, 'book') or self.book is None or not self.book.spine:
            self.finalize()
        
        # Validate that the spine has content
        if not self.book.spine:
            logger.error("No spine items in EPUB")
            raise ValueError("No spine items in EPUB")
        
        # Ensure we have navigation
        if not self.book.toc and self.chapters:
            logger.warning("No TOC entries but chapters exist, creating simple TOC")
            # Create TOC entries for each chapter if missing
            for chapter_id, pages in self.chapters.items():
                if pages:
                    first_page = pages[0]
                    chapter_toc = epub.Link(first_page.file_name, chapter_id, chapter_id)
                    self.toc.append(chapter_toc)
            
            self.book.toc = self.toc
        
        # Validate that all spine items are properly set up
        for item in self.book.spine:
            if hasattr(item, 'content') and not item.content:
                logger.warning(f"Empty content in spine item {item.id}, adding minimal content")
                item.content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
    <title>{item.title}</title>
</head>
<body>
    <div>{item.title or 'Content'}</div>
</body>
</html>"""
        
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
            # Log what we're about to write
            image_count = len(self.images) if hasattr(self, 'images') else 0
            chapter_count = len(self.chapters) if hasattr(self, 'chapters') else 0
            spine_count = len(self.book.spine) if hasattr(self.book, 'spine') else 0
            toc_count = len(self.book.toc) if hasattr(self.book, 'toc') else 0
            
            logger.info(f"Writing EPUB with {image_count} images, {chapter_count} chapters, " + 
                       f"{spine_count} spine items, {toc_count} TOC entries")
            
            epub.write_epub(str(filepath), self.book, {})
            logger.info(f"EPUB written to {filepath}")
            return str(filepath)
        except Exception as e:
            logger.error(f"Error writing EPUB: {e}")
            # Re-raise with more context
            raise ValueError(f"Error writing EPUB: {e}") from e
    
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
