"""Kobo-specific EPUB modifications.

This module provides Kobo-specific enhancements for EPUB files to optimize
the reading experience on Kobo e-readers. It includes modifications for
handling the .kepub.epub format, specialized CSS, and Kobo markup.

See: https://github.com/pgaskin/kepubify/blob/master/kepub/transform.go
"""

import os
import logging
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Union, Set
import io
import shutil
import zipfile
import tempfile
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup

import ebooklib
from ebooklib import epub

from .builder import EPUBBuilder
from ..utils import sanitize_filename, ensure_directory

# Set up logging
logger = logging.getLogger(__name__)

# Constants
KOBO_CSS = """
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
    display: block;
}
/* Kobo-specific CSS */
div.koboSpan {
    display: inline-block;
}
"""

# Kobo uses an additional namespace for its specific features
KOBO_NAMESPACE = {
    "xmlns:kobo": "http://ns.kobo.com/1.0"
}


class KepubBuilder(EPUBBuilder):
    """Builds Kobo-compatible EPUB files (KEPUBs) from manga images."""
    
    def __init__(self, title: str, output_dir: Union[str, Path], 
                language: str = 'en', author: str = 'Unknown',
                identifier: Optional[str] = None, publisher: str = 'MangaBook'):
        """Initialize the Kobo EPUB builder.
        
        Args:
            title: Title of the manga.
            output_dir: Directory to save the KEPUB.
            language: Language code for the KEPUB.
            author: Author of the manga.
            identifier: Unique identifier for the KEPUB.
            publisher: Publisher name.
        """
        super().__init__(title, output_dir, language, author, identifier, publisher)
    
    def _init_book(self) -> None:
        """Initialize the EPUB book with Kobo-specific settings."""
        super()._init_book()
        
        # Add Kobo-specific metadata
        self.book.add_metadata(None, 'meta', '', {
            'name': 'cover',
            'content': 'cover-image'
        })
        
        # Add Kobo CSS instead of default CSS
        for item in self.book.get_items_of_type(ebooklib.ITEM_STYLE):
            if item.id == "style_default":
                item.content = KOBO_CSS
                break
    
    def _create_image_page(self, uid: str, image_path: str, title: Optional[str] = None) -> epub.EpubHtml:
        """Create an HTML page for an image with Kobo-specific markup.
        
        Args:
            uid: Unique identifier for the page.
            image_path: Path to the image.
            title: Optional title for the page.
            
        Returns:
            epub.EpubHtml: The created page with Kobo enhancements.
        """
        page = super()._create_image_page(uid, image_path, title)
        
        # Parse the HTML content
        soup = BeautifulSoup(page.content, 'html.parser')
        
        # Add Kobo namespace to HTML tag
        html_tag = soup.find('html')
        for ns_name, ns_value in KOBO_NAMESPACE.items():
            html_tag[ns_name] = ns_value
        
        # Add Kobo spans to the image div
        img_div = soup.find('div', class_='image')
        if img_div:
            # Add a kobo span around the content
            span_id = f"kobo.{uid}.1"
            kobo_span = soup.new_tag('span', id=span_id, **{'class': 'koboSpan'})
            
            # Wrap the image in the span
            img = img_div.find('img')
            img.wrap(kobo_span)
        
        # Update the page content
        page.content = str(soup)
        
        return page
    
    def write(self, filename: Optional[str] = None) -> str:
        """Write the KEPUB file.
        
        Args:
            filename: Optional filename for the KEPUB.
            
        Returns:
            str: Path to the written KEPUB file.
        """
        # Finalize if not already done
        if not self.book.spine:
            self.finalize()
        
        # Determine filename
        if filename is None:
            filename = sanitize_filename(self.title) + ".kepub.epub"
        
        # Ensure it has the .kepub.epub extension
        if not filename.lower().endswith('.kepub.epub'):
            if filename.lower().endswith('.epub'):
                filename = filename[:-5] + ".kepub.epub"
            else:
                filename += ".kepub.epub"
        
        # Generate the full path
        filepath = self.output_dir / filename
        
        # Write the EPUB
        try:
            epub.write_epub(str(filepath), self.book, {})
            logger.info(f"KEPUB written to {filepath}")
            
            # Apply additional Kobo-specific modifications to the file
            self._apply_kobo_modifications(filepath)
            
            return str(filepath)
        except Exception as e:
            logger.error(f"Error writing KEPUB: {e}")
            raise
    
    def _apply_kobo_modifications(self, filepath: Union[str, Path]) -> None:
        """Apply additional Kobo-specific modifications to the EPUB file.
        
        Args:
            filepath: Path to the EPUB file.
        """
        # This function modifies the EPUB file after it's been written by ebooklib
        # to add additional Kobo-specific features that aren't easily added through the API
        
        try:
            # Create a temporary directory
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_dir = Path(temp_dir)
                
                # Extract the EPUB file
                with zipfile.ZipFile(filepath, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)
                
                # Process XHTML files to add Kobo paragraph splitting
                xhtml_files = temp_dir.glob('OEBPS/pages/*.xhtml')
                for xhtml_file in xhtml_files:
                    self._process_xhtml_for_kobo(xhtml_file)
                
                # Update the content.opf file
                content_opf = temp_dir / 'OEBPS' / 'content.opf'
                if content_opf.exists():
                    self._update_content_opf(content_opf)
                
                # Recreate the EPUB file
                os.remove(filepath)
                with zipfile.ZipFile(filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    # Add mimetype first and uncompressed
                    mimetype_file = temp_dir / 'mimetype'
                    if mimetype_file.exists():
                        zipf.write(mimetype_file, 'mimetype', compress_type=zipfile.ZIP_STORED)
                    
                    # Add all other files
                    for root, _, files in os.walk(temp_dir):
                        root_path = Path(root)
                        for file in files:
                            if file == 'mimetype':
                                continue
                            
                            file_path = root_path / file
                            arcname = file_path.relative_to(temp_dir)
                            zipf.write(file_path, arcname)
        
        except Exception as e:
            logger.error(f"Error applying Kobo modifications: {e}")
    
    def _process_xhtml_for_kobo(self, xhtml_path: Union[str, Path]) -> None:
        """Process an XHTML file for Kobo paragraph splitting.
        
        Args:
            xhtml_path: Path to the XHTML file.
        """
        try:
            with open(xhtml_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Parse with BeautifulSoup
            soup = BeautifulSoup(content, 'html.parser')
            
            # Find all paragraphs and add Kobo spans
            paragraphs = soup.find_all('p')
            for i, p in enumerate(paragraphs):
                # Add an id to the paragraph if it doesn't have one
                if not p.get('id'):
                    p['id'] = f"kobo_p_{i}"
                
                # Split the text into sentences
                p_id = p['id']
                text = p.get_text()
                
                # If the paragraph has no text or only has an image, skip it
                if not text.strip() or (p.find('img') and len(text.strip()) == 0):
                    continue
                
                # Clear the paragraph content
                p.clear()
                
                # Add each sentence as a separate span
                sentences = re.split(r'([.!?]+)', text)
                current_sentence = ""
                span_count = 1
                
                for j, part in enumerate(sentences):
                    current_sentence += part
                    
                    # If this part ends with a sentence delimiter and isn't empty, create a span
                    if j % 2 == 1 and current_sentence.strip():
                        span_id = f"{p_id}-{span_count}"
                        kobo_span = soup.new_tag('span', id=span_id, **{'class': 'koboSpan'})
                        kobo_span.string = current_sentence
                        p.append(kobo_span)
                        
                        current_sentence = ""
                        span_count += 1
                
                # Add any remaining text
                if current_sentence.strip():
                    span_id = f"{p_id}-{span_count}"
                    kobo_span = soup.new_tag('span', id=span_id, **{'class': 'koboSpan'})
                    kobo_span.string = current_sentence
                    p.append(kobo_span)
            
            # Write the modified content back
            with open(xhtml_path, 'w', encoding='utf-8') as f:
                f.write(str(soup))
        
        except Exception as e:
            logger.error(f"Error processing {xhtml_path} for Kobo: {e}")
    
    def _update_content_opf(self, opf_path: Union[str, Path]) -> None:
        """Update the content.opf file with Kobo-specific metadata.
        
        Args:
            opf_path: Path to the content.opf file.
        """
        try:
            # Parse the OPF file
            tree = ET.parse(opf_path)
            root = tree.getroot()
            
            # Add Kobo reading direction property if not present
            if self.reading_direction == 'rtl':
                # Check for existing spine properties
                spine = root.find('.//{http://www.idpf.org/2007/opf}spine')
                if spine is not None and not spine.get('page-progression-direction'):
                    spine.set('page-progression-direction', 'rtl')
            
            # Write the updated OPF file
            tree.write(opf_path, encoding='utf-8', xml_declaration=True)
        
        except Exception as e:
            logger.error(f"Error updating {opf_path} for Kobo: {e}")
    
    @staticmethod
    def convert_epub_to_kepub(epub_path: Union[str, Path], output_dir: Optional[Union[str, Path]] = None) -> str:
        """Convert an existing EPUB file to a Kobo KEPUB.
        
        Args:
            epub_path: Path to the EPUB file.
            output_dir: Optional output directory for the converted file.
            
        Returns:
            str: Path to the converted KEPUB file.
        """
        epub_path = Path(epub_path)
        
        if not epub_path.exists():
            raise FileNotFoundError(f"EPUB file not found: {epub_path}")
        
        if output_dir is None:
            output_dir = epub_path.parent
        else:
            output_dir = Path(output_dir)
            ensure_directory(output_dir)
        
        # Generate the output filename
        output_name = epub_path.stem
        if output_name.lower().endswith('.epub'):
            output_name = output_name[:-5]
        
        kepub_path = output_dir / f"{output_name}.kepub.epub"
        
        try:
            # First, make a copy of the EPUB
            shutil.copy2(epub_path, kepub_path)
            
            # Create a KepubBuilder instance
            builder = KepubBuilder("temp", output_dir)
            
            # Apply Kobo modifications
            builder._apply_kobo_modifications(kepub_path)
            
            logger.info(f"Converted EPUB to KEPUB: {kepub_path}")
            return str(kepub_path)
        
        except Exception as e:
            logger.error(f"Error converting EPUB to KEPUB: {e}")
            # Remove the output file if it was created
            if kepub_path.exists():
                kepub_path.unlink()
            raise
