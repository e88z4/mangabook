"""Enhanced EPUB/KEPUB builders with strict EPUB specification compliance.

This module provides enhanced EPUB and KEPUB builders that use direct ZIP manipulation 
to ensure strict EPUB spec compliance. These builders work around issues in ebooklib's
navigation handling to create valid EPUB files, particularly for large manga volumes.
"""

import os
import sys
import datetime
from pathlib import Path
import shutil
import zipfile
import tempfile
import logging
import traceback
import xml.etree.ElementTree as ET
from typing import Optional, List, Dict, Union

import ebooklib
from ebooklib import epub

from ..utils import ensure_directory, sanitize_filename
from .builder import EPUBBuilder
from .kobo import KepubBuilder

# Set up logging
logger = logging.getLogger(__name__)

class EnhancedEPUBBuilder(EPUBBuilder):
    """EPUB Builder with strict EPUB spec compliance"""
    
    def write(self, filename: Optional[str] = None, force_overwrite: bool = False) -> str:
        """Write the EPUB file directly using ZIP manipulation.
        
        Args:
            filename: Optional filename for the EPUB.
            force_overwrite: Whether to overwrite existing files.
            
        Returns:
            str: Path to the written EPUB file.
        """
        # Do all the preparation as in the parent class
        is_navigation_only = not self.images and hasattr(self, 'book') and self.book is not None
        
        if not self.images and not is_navigation_only:
            logger.error("No content to write to EPUB")
            raise ValueError("No content to write to EPUB")
        
        if not hasattr(self, 'book') or self.book is None or not self.book.spine:
            self.finalize()
        
        if not self.book.spine:
            logger.error("No spine items in EPUB")
            raise ValueError("No spine items in EPUB")
        
        # Determine filename
        if filename is None:
            filename = sanitize_filename(self.title) + ".epub"
        
        # Ensure it has the .epub extension
        if not filename.lower().endswith('.epub'):
            filename += ".epub"
        
        # Get the self.output_dir as a Path object for construction
        output_path = Path(self.output_dir)
        
        # Determine the full path for the EPUB file
        if filename:
            # If filename contains a path separator, extract just the filename part
            if os.path.sep in filename:
                filename = os.path.basename(filename)
                
            epub_path = output_path / filename
        else:
            # Generate a filename from the title
            safe_title = sanitize_filename(self.title)
            epub_path = output_path / f"{safe_title}.epub"
        
        # Check if file already exists and not force_overwrite
        if epub_path.exists() and not force_overwrite:
            logger.warning(f"File already exists: {epub_path}. Use force_overwrite=True to overwrite.")
            return str(epub_path)  # Return the path even though we didn't write to it
        
        # Create a temporary directory for the EPUB contents
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Create the required directory structure
            meta_inf_dir = temp_path / "META-INF"
            meta_inf_dir.mkdir(exist_ok=True)
            
            oebps_dir = temp_path / "OEBPS"
            oebps_dir.mkdir(exist_ok=True)
            
            # Create the mimetype file
            with open(temp_path / "mimetype", 'w', encoding='utf-8') as f:
                f.write("application/epub+zip")
            
            # Create the container.xml file
            self._create_container_file(meta_inf_dir / "container.xml")
            
            # Extract all the book items to the OEBPS directory
            self._extract_items_to_directory(oebps_dir)
            
            # Create the OPF file
            self._create_opf_file(oebps_dir / "content.opf")
            
            # Create the NCX file
            self._create_ncx_file(oebps_dir / "toc.ncx")
            
            # Create the Nav file
            self._create_nav_file(oebps_dir / "nav.xhtml")
            
            # Create the ZIP file with the correct mimetype handling
            # Make sure the parent directory exists
            epub_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Create the ZIP file
            with zipfile.ZipFile(epub_path, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                # Add the mimetype file first, uncompressed
                zip_file.write(
                    temp_path / "mimetype", 
                    arcname="mimetype", 
                    compress_type=zipfile.ZIP_STORED
                )
                
                # Add the rest of the files
                for root, dirs, files in os.walk(temp_path):
                    rel_path = os.path.relpath(root, temp_path)
                    
                    for file in files:
                        # Skip mimetype, we've already added it
                        if file == "mimetype" and rel_path == '.':
                            continue
                            
                        file_path = os.path.join(root, file)
                        
                        if rel_path == '.':
                            # Files in the root directory
                            arc_name = file
                        else:
                            # Files in subdirectories
                            arc_name = os.path.join(rel_path, file)
                            
                        # Use forward slashes for ZIP entries
                        arc_name = arc_name.replace(os.path.sep, '/')
                        
                        # Add the file to the ZIP
                        zip_file.write(file_path, arcname=arc_name)
        
        logger.info(f"EPUB written to {epub_path}")
        return str(epub_path)
    
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
            
            # Determine media type based on file extension
            extension = image_path.suffix.lower()
            if extension in ['.jpg', '.jpeg']:
                media_type = "image/jpeg"
            elif extension == '.png':
                media_type = "image/png"
            else:
                media_type = f"image/{extension[1:]}"
            
            # Handle the cover image properly
            cover_filename = f"images/cover{extension}"
            
            # Remove existing cover items to avoid duplicates
            items_to_remove = []
            for item in self.book.get_items():
                if hasattr(item, 'id') and (item.id == 'cover' or item.id == 'cover-img' or 
                                           item.file_name == 'cover.xhtml'):
                    items_to_remove.append(item)
            
            for item in items_to_remove:
                try:
                    self.book.items.remove(item)
                except ValueError:
                    pass
                    
            # Add cover image as a separate item with cover-image property
            cover_img = epub.EpubImage()
            cover_img.id = 'cover-img'
            cover_img.file_name = cover_filename
            cover_img.media_type = media_type
            cover_img.content = cover_data
            cover_img.properties = ['cover-image']
            self.book.add_item(cover_img)
            
            # Create a properly formatted cover page
            cover_page = epub.EpubHtml(
                title='Cover',
                file_name='cover.xhtml',
                lang=self.language,
                uid='cover'
            )
            cover_page.content = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{self.language}">
<head>
    <title>Cover</title>
    <meta charset="utf-8"/>
    <style>
        body {{ margin: 0; padding: 0; text-align: center; }}
        .cover {{ width: 100%; height: 100vh; display: flex; justify-content: center; align-items: center; }}
        .cover img {{ max-width: 100%; max-height: 100%; }}
    </style>
</head>
<body>
    <div class="cover">
        <img src="{cover_filename}" alt="Cover"/>
    </div>
</body>
</html>'''
            
            # Set cover property (EPUB3 uses 'cover-image' property only for the image, not the page)
            # No need to set a special property for the cover page in EPUB3
            
            # Add the cover page to the book and spine
            self.book.add_item(cover_page)
            # Make sure cover is first in the spine
            if cover_page not in self.spine:
                self.spine.insert(0, cover_page)
            
            logger.debug(f"Cover set: {image_path}")
        except Exception as e:
            logger.error(f"Error setting cover: {e}")
            traceback.print_exc()
    
    def _extract_items_to_directory(self, oebps_dir: Path) -> None:
        """Extract all items from the book to the OEBPS directory.
        
        Args:
            oebps_dir: Path to the OEBPS directory.
        """
        # Ensure all necessary subdirectories exist
        (oebps_dir / 'images').mkdir(exist_ok=True)
        (oebps_dir / 'pages').mkdir(exist_ok=True)
        (oebps_dir / 'style').mkdir(exist_ok=True)
        (oebps_dir / 'chapters').mkdir(exist_ok=True)
        
        # Extract all items from the book
        for item in self.book.get_items():
            if not hasattr(item, 'file_name'):
                continue
            
            # Replace spaces with underscores in file names
            item.file_name = item.file_name.replace(' ', '_')
            
            file_path = oebps_dir / item.file_name
            file_dir = file_path.parent
            file_dir.mkdir(exist_ok=True, parents=True)
            
            # Write the item content
            with open(file_path, 'wb') as f:
                if item.content is None:
                    # Skip writing empty cover images
                    if item.id == 'cover-img' or (hasattr(item, 'properties') and 
                                                'cover-image' in getattr(item, 'properties', [])):
                        logger.warning(f"Skipping empty cover image: {item.id}")
                        continue
                    else:
                        logger.warning(f"Item {item.id} has None content, writing empty file")
                        f.write(b'')
                elif isinstance(item.content, str):
                    f.write(item.content.encode('utf-8'))
                else:
                    f.write(item.content)
            
            logger.debug(f"Extracted item {item.id} to {file_path}")
            
            # Fix image references in XHTML files
            if item.file_name.endswith('.xhtml') and item.content:
                self._fix_xhtml_references(file_path)
                
    def _fix_xhtml_references(self, file_path: Path) -> None:
        """Fix references in XHTML files, replacing spaces with underscores.
        Also fixes invalid ID attributes and other EPUB validation issues.
        
        Args:
            file_path: Path to the XHTML file.
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Replace spaces with underscores in href attributes
            import re
            content = re.sub(r'href="([^"]*)"', lambda m: f'href="{m.group(1).replace(" ", "_")}"', content)
            content = re.sub(r'src="([^"]*)"', lambda m: f'src="{m.group(1).replace(" ", "_")}"', content)
            
            # Fix invalid ID attributes (must not contain spaces)
            content = re.sub(r'id="([^"]*)"', 
                            lambda m: f'id="{re.sub(r"\s+", "_", m.group(1))}"', 
                            content)
            
            # Additional fixes for EPUB validation
            # Fix namespaces in HTML
            if "<!DOCTYPE html>" in content and "xmlns" not in content:
                content = content.replace("<html>", '<html xmlns="http://www.w3.org/1999/xhtml">')
                
            # Fix self-closing tags (XHTML requires proper closing)
            content = re.sub(r'<(img|br|hr)([^>]*[^/])>', r'<\1\2 />', content)
                
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception as e:
            logger.error(f"Error fixing references in {file_path}: {e}")
    
    def _create_container_file(self, container_path: Path) -> None:
        """Create the container.xml file that points to the OPF file.
        
        Args:
            container_path: Path to write the container.xml file.
        """
        container_content = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
    <rootfiles>
        <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
    </rootfiles>
</container>
"""
        try:
            with open(container_path, 'w', encoding='utf-8') as f:
                f.write(container_content)
            logger.debug(f"Created container.xml at {container_path}")
        except Exception as e:
            logger.error(f"Error creating container.xml: {e}")
            raise
    
    def _create_opf_file(self, opf_path: Path) -> None:
        """Create the content.opf file manually.
        
        Args:
            opf_path: Path to write the content.opf file.
        """
        # Create the timestamp
        now = datetime.datetime.now()
        timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        
        # Collect metadata
        metadata_xml = f"""    <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
        <dc:identifier id="book-id">{self.identifier}</dc:identifier>
        <dc:title>{self.title}</dc:title>
        <dc:language>{self.language}</dc:language>
        <dc:creator id="creator">{self.author}</dc:creator>
        <dc:publisher>{self.publisher}</dc:publisher>
        <meta property="dcterms:modified">{timestamp}</meta>
"""
        
        # Add additional metadata
        for m in self.book.metadata:
            if m is None:
                continue
                
            # Handle different metadata formats
            try:
                # Skip invalid elements (like t and ns0:t)
                if len(m) > 1 and m[1] and (m[1] == 't' or m[1] == 'ns0:t'):
                    logger.warning(f"Skipping invalid metadata element: {m[1]}")
                    continue
                    
                if len(m) == 4 and m[3]:
                    # Format with attributes
                    attrs = ' '.join([f'{k}="{v}"' for k, v in m[3].items()])
                    metadata_xml += f'        <{m[1]} {attrs}>{m[2]}</{m[1]}>\n'
                elif len(m) > 2:
                    # Simple format
                    metadata_xml += f'        <{m[1]}>{m[2]}</{m[1]}>\n'
            except (TypeError, IndexError):
                logger.warning(f"Skipping invalid metadata entry: {m}")
                continue
        
        metadata_xml += "    </metadata>\n"
        
        # Collect manifest items
        manifest_xml = "    <manifest>\n"
        
        # Make sure we have a nav item with the nav property
        nav_item_found = False
        
        # Track items to avoid duplicates
        added_items = set()
        
        for item in self.book.get_items():
            if not hasattr(item, 'file_name'):
                continue
                
            # Replace spaces with underscores
            item.file_name = item.file_name.replace(' ', '_')
            
            # Make sure IDs don't contain colons
            if hasattr(item, 'id'):
                item.id = item.id.replace(':', '_')
                
            # Ensure item ID is XML-compliant (only alphanumeric, -, _, .)
            import re
            if not re.match(r'^[a-zA-Z0-9\-_\.]+$', item.id):
                logger.warning(f"Fixing invalid item ID: {item.id}")
                item.id = re.sub(r'[^a-zA-Z0-9\-_\.]', '_', item.id)
            
            # Skip duplicate items
            item_key = f"{item.file_name}"
            if item_key in added_items:
                logger.warning(f"Skipping duplicate item: {item.file_name}")
                continue
                
            added_items.add(item_key)
            
            props = ""
            if hasattr(item, 'properties') and item.properties:
                props = f' properties="{" ".join(item.properties)}"'
                if 'nav' in item.properties:
                    nav_item_found = True
            
            manifest_xml += f'        <item id="{item.id}" href="{item.file_name}" media-type="{item.media_type}"{props} />\n'
        
        # Add nav property to nav.xhtml if not found
        if not nav_item_found:
            # Find the nav item and add the property
            for item in self.book.get_items():
                if hasattr(item, 'file_name') and item.file_name == 'nav.xhtml':
                    manifest_xml = manifest_xml.replace(
                        f'<item id="{item.id}" href="nav.xhtml" media-type="{item.media_type}"',
                        f'<item id="{item.id}" href="nav.xhtml" media-type="{item.media_type}" properties="nav"'
                    )
                    break
        
        manifest_xml += "    </manifest>\n"
        
        # Collect spine items
        spine_xml = '    <spine toc="ncx">\n'
        
        # Track valid manifest items to ensure we only include items that exist
        valid_ids = set()
        for item in self.book.get_items():
            if hasattr(item, 'id'):
                # Ensure IDs are properly sanitized
                clean_id = item.id.replace(':', '_')
                import re
                clean_id = re.sub(r'[^a-zA-Z0-9\-_\.]', '_', clean_id)
                valid_ids.add(clean_id)
                item.id = clean_id
        
        for item in self.book.spine:
            if isinstance(item, str):
                # Replace colons and invalid characters in IDs
                import re
                item_id = item.replace(':', '_')
                item_id = re.sub(r'[^a-zA-Z0-9\-_\.]', '_', item_id)
                
                # Only add if it's a valid ID
                if item_id in valid_ids:
                    spine_xml += f'        <itemref idref="{item_id}" />\n'
                else:
                    logger.warning(f"Skipping invalid spine item: {item_id}")
                    
            elif hasattr(item, 'id'):
                # Replace colons and invalid characters in IDs
                import re
                item_id = item.id.replace(':', '_')
                item_id = re.sub(r'[^a-zA-Z0-9\-_\.]', '_', item_id)
                
                # Only add if it's a valid ID
                if item_id in valid_ids:
                    spine_xml += f'        <itemref idref="{item_id}" />\n'
                else:
                    logger.warning(f"Skipping invalid spine item: {item_id}")
        
        spine_xml += "    </spine>\n"
        
        # Create the full OPF content
        opf_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id">
{metadata_xml}
{manifest_xml}
{spine_xml}
</package>"""
        
        # Write the OPF file
        with open(opf_path, 'w', encoding='utf-8') as f:
            f.write(opf_content)
            
        logger.debug(f"Created content.opf at {opf_path}")
    
    def _create_ncx_file(self, ncx_path: Path) -> None:
        """Create the toc.ncx file manually.
        
        Args:
            ncx_path: Path to write the toc.ncx file.
        """
        # Create the navMap content
        navpoints = ""
        playorder = 1
        
        # Convert TOC to navpoints
        for item in self.book.toc:
            if isinstance(item, tuple) and len(item) == 2:
                # Item with children
                parent, children = item
                
                # Replace spaces with underscores in href
                if hasattr(parent, 'href'):
                    parent.href = parent.href.replace(' ', '_')
                    
                navpoints += f"""        <navPoint id="navpoint-{playorder}" playOrder="{playorder}">
            <navLabel>
                <text>{parent.title}</text>
            </navLabel>
            <content src="{parent.href}" />
"""
                playorder += 1
                
                # Add children
                for child in children:
                    # Replace spaces with underscores in href
                    if hasattr(child, 'href'):
                        child.href = child.href.replace(' ', '_')
                        
                    navpoints += f"""            <navPoint id="navpoint-{playorder}" playOrder="{playorder}">
                <navLabel>
                    <text>{child.title}</text>
                </navLabel>
                <content src="{child.href}" />
            </navPoint>
"""
                    playorder += 1
                    
                navpoints += "        </navPoint>\n"
            else:
                # Simple item
                if hasattr(item, 'href') and hasattr(item, 'title'):
                    # Replace spaces with underscores in href
                    item.href = item.href.replace(' ', '_')
                    
                    navpoints += f"""        <navPoint id="navpoint-{playorder}" playOrder="{playorder}">
            <navLabel>
                <text>{item.title}</text>
            </navLabel>
            <content src="{item.href}" />
        </navPoint>
"""
                    playorder += 1
        
        # Create the full NCX content
        ncx_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
    <head>
        <meta name="dtb:uid" content="{self.identifier}" />
        <meta name="dtb:depth" content="2" />
        <meta name="dtb:totalPageCount" content="0" />
        <meta name="dtb:maxPageNumber" content="0" />
    </head>
    <docTitle>
        <text>{self.title}</text>
    </docTitle>
    <navMap>
{navpoints}
    </navMap>
</ncx>"""
        
        # Write the NCX file
        with open(ncx_path, 'w', encoding='utf-8') as f:
            f.write(ncx_content)
            
        logger.debug(f"Created toc.ncx at {ncx_path}")
    
    def _create_nav_file(self, nav_path: Path) -> None:
        """Create the nav.xhtml file manually.
        
        Args:
            nav_path: Path to write the nav.xhtml file.
        """
        # Create the TOC list items
        toc_items = ""
        
        # Get cover file path
        cover_path = "cover.xhtml"
        cover_exists = False
        for item in self.book.get_items():
            if item.file_name == 'cover.xhtml':
                cover_exists = True
                break
        
        # Convert TOC to list items
        for item in self.book.toc:
            if isinstance(item, tuple) and len(item) == 2:
                # Item with children
                parent, children = item
                
                # Replace spaces with underscores and ensure href has the correct prefix
                if hasattr(parent, 'href'):
                    parent.href = parent.href.replace(' ', '_')
                    # Strip 'OEBPS/' prefix if present as we're already in the OEBPS directory
                    if parent.href.startswith('OEBPS/'):
                        parent.href = parent.href[6:]
                    
                toc_items += f"""            <li>
                <a href="{parent.href}">{parent.title}</a>
                <ol>
"""
                # Add children
                for child in children:
                    # Replace spaces with underscores and ensure href has the correct prefix
                    if hasattr(child, 'href'):
                        child.href = child.href.replace(' ', '_')
                        # Strip 'OEBPS/' prefix if present as we're already in the OEBPS directory
                        if child.href.startswith('OEBPS/'):
                            child.href = child.href[6:]
                        
                    toc_items += f"""                    <li><a href="{child.href}">{child.title}</a></li>
"""
                    
                toc_items += """                </ol>
            </li>
"""
            else:
                # Simple item
                if hasattr(item, 'href') and hasattr(item, 'title'):
                    # Replace spaces with underscores and ensure href has the correct prefix
                    item.href = item.href.replace(' ', '_')
                    # Strip 'OEBPS/' prefix if present as we're already in the OEBPS directory
                    if item.href.startswith('OEBPS/'):
                        item.href = item.href[6:]
                    
                    toc_items += f"""            <li><a href="{item.href}">{item.title}</a></li>
"""
        
        # If empty TOC, add a default link to the cover
        if not toc_items:
            # Verify if cover.xhtml exists in the items
            if cover_exists:
                toc_items = """            <li><a href="cover.xhtml">Cover</a></li>
"""
            else:
                # Find the first content page as fallback
                first_page = None
                for item in self.book.get_items():
                    if item.file_name.endswith('.xhtml') and item.file_name != 'nav.xhtml':
                        first_page = item.file_name
                        break
                        
                if first_page:
                    toc_items = f"""            <li><a href="{first_page}">Start</a></li>
"""
        
        # Create landmarks section
        landmarks = ""
        if cover_exists:
            # In EPUB3, landmarks must use the correct path - cover.xhtml is in the OEBPS root
            landmarks = f"""    <nav epub:type="landmarks" id="landmarks">
        <h1>Landmarks</h1>
        <ol>
            <li><a epub:type="toc" href="#toc">Table of Contents</a></li>
            <li><a epub:type="cover" href="cover.xhtml">Cover</a></li>
        </ol>
    </nav>"""
            
        # Create the full Nav content
        nav_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
    <title>Navigation</title>
    <meta charset="utf-8"/>
</head>
<body>
    <nav epub:type="toc" id="toc">
        <h1>Table of Contents</h1>
        <ol>
{toc_items}
        </ol>
    </nav>
{landmarks}
</body>
</html>"""
        
        # Write the Nav file
        with open(nav_path, 'w', encoding='utf-8') as f:
            f.write(nav_content)
            
        logger.debug(f"Created nav.xhtml at {nav_path}")


class EnhancedKepubBuilder(EnhancedEPUBBuilder, KepubBuilder):
    """Kobo EPUB Builder with strict EPUB spec compliance"""
    
    def write(self, filename: Optional[str] = None, force_overwrite: bool = False) -> str:
        """Write the KEPUB file.
        
        Args:
            filename: Optional filename for the KEPUB.
            force_overwrite: Whether to overwrite existing files.
            
        Returns:
            str: Path to the written KEPUB file.
        """
        # Determine filename
        if filename is None:
            filename = sanitize_filename(self.title) + ".kepub.epub"
        
        # Ensure it has the .kepub.epub extension
        if not filename.lower().endswith('.kepub.epub'):
            if filename.lower().endswith('.epub'):
                filename = filename[:-5] + ".kepub.epub"
            else:
                filename += ".kepub.epub"
        
        # Write the EPUB using the enhanced method
        epub_path = super().write(filename, force_overwrite)
        
        # Apply Kobo-specific modifications using the parent class method
        self._apply_kobo_modifications(epub_path)
        
        return epub_path
    
    def _update_toc_ncx(self, ncx_path: Union[str, Path]) -> None:
        """Update the toc.ncx file with Kobo-specific metadata.
        
        Args:
            ncx_path: Path to the toc.ncx file.
        """
        try:
            # Parse the NCX file
            tree = ET.parse(ncx_path)
            root = tree.getroot()
            
            # Define namespaces for XPath queries
            ns = {'ncx': 'http://www.daisy.org/z3986/2005/ncx/'}
            
            # Update navPoints with Kobo-specific ids if needed
            nav_points = root.findall('.//ncx:navPoint', ns)
            for i, nav_point in enumerate(nav_points, 1):
                # Add Kobo-specific id if not present
                nav_id = nav_point.get('id')
                if 'kobo' not in nav_id:
                    nav_point.set('id', f"kobo_nav_{i}")
            
            # Write the updated NCX file
            tree.write(ncx_path, encoding='utf-8', xml_declaration=True)
            
            logger.debug(f"Updated toc.ncx for Kobo: {ncx_path}")
            
        except Exception as e:
            logger.error(f"Error updating {ncx_path} for Kobo: {e}")
