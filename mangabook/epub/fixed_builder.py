"""
DEPRECATED MODULE: This file is no longer used in the mangabook codebase.

This module previously provided workaround EPUB/KEPUB builders to address ebooklib navigation and EPUB spec compliance issues. All functionality has been superseded by `enhanced_builder.py`, which should be used for all new workflows.

- All references to this module have been removed from the codebase.
- This file remains for historical reference only and will be removed in a future release.
- Please use `enhanced_builder.py` for strict EPUB/KEPUB generation and compliance.
"""

# DEPRECATED: No longer used. See enhanced_builder.py for the current implementation.

import os
import sys
from pathlib import Path
import shutil
import zipfile
import tempfile
import logging
import traceback
import xml.etree.ElementTree as ET
from typing import Optional, List, Dict, Union

from ..utils import ensure_directory
from .builder import EPUBBuilder
from .kobo import KepubBuilder

# Set up logging
logger = logging.getLogger(__name__)

class FixedEPUBBuilder(EPUBBuilder):
    """EPUB Builder with workaround for the 'Document is empty' issue"""
    
    def write(self, filename: Optional[str] = None) -> str:
        """Write the EPUB file directly using ZIP manipulation.
        
        Args:
            filename: Optional filename for the EPUB.
            
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
            filename = self.title.replace(' ', '_') + ".epub"
        
        # Ensure it has the .epub extension
        if not filename.lower().endswith('.epub'):
            filename += ".epub"
        
        # Generate the full path
        filepath = self.output_dir / filename
        
        try:
            # Create a temporary directory for manual EPUB creation
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                
                # Create directories for EPUB structure
                meta_inf_dir = temp_path / 'META-INF'
                oebps_dir = temp_path / 'OEBPS'
                meta_inf_dir.mkdir()
                oebps_dir.mkdir()
                
                # Create mimetype file
                with open(temp_path / 'mimetype', 'w') as f:
                    f.write('application/epub+zip')
                
                # Create container.xml
                container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
   <rootfiles>
      <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
   </rootfiles>
</container>"""
                
                with open(meta_inf_dir / 'container.xml', 'w') as f:
                    f.write(container_xml)
                
                # Extract all items from the book
                self._extract_items_to_directory(oebps_dir)
                
                # Create content.opf manually
                self._create_opf_file(oebps_dir / 'content.opf')
                
                # Create toc.ncx manually
                self._create_ncx_file(oebps_dir / 'toc.ncx')
                
                # Create nav.xhtml manually if it doesn't exist
                nav_path = oebps_dir / 'nav.xhtml'
                if not nav_path.exists():
                    self._create_nav_file(nav_path)
                
                # Create the EPUB file (ZIP)
                with zipfile.ZipFile(filepath, 'w') as zip_file:
                    # Add mimetype (must be first and uncompressed)
                    zip_file.write(temp_path / 'mimetype', 'mimetype', compress_type=zipfile.ZIP_STORED)
                    
                    # Add other files
                    for root, _, files in os.walk(temp_path):
                        for file in files:
                            if file == 'mimetype':
                                continue  # Already added
                            
                            file_path = os.path.join(root, file)
                            arcname = os.path.relpath(file_path, temp_path)
                            zip_file.write(file_path, arcname)
                
                logger.info(f"EPUB written to {filepath}")
                return str(filepath)
                
        except Exception as e:
            logger.error(f"Error writing EPUB: {e}")
            traceback.print_exc()
            raise ValueError(f"Error writing EPUB: {e}") from e
    
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
            
            file_path = oebps_dir / item.file_name
            file_dir = file_path.parent
            file_dir.mkdir(exist_ok=True, parents=True)
            
            # Write the item content
            with open(file_path, 'wb') as f:
                if item.content is None:
                    logger.warning(f"Item {item.id} has None content, writing empty file")
                    f.write(b'')
                elif isinstance(item.content, str):
                    f.write(item.content.encode('utf-8'))
                else:
                    f.write(item.content)
            
            logger.debug(f"Extracted item {item.id} to {file_path}")
    
    def _create_opf_file(self, opf_path: Path) -> None:
        """Create the content.opf file manually.
        
        Args:
            opf_path: Path to write the content.opf file.
        """
        # Collect metadata
        metadata_xml = f"""    <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
        <dc:identifier id="book-id">{self.identifier}</dc:identifier>
        <dc:title>{self.title}</dc:title>
        <dc:language>{self.language}</dc:language>
        <dc:creator>{self.author}</dc:creator>
        <dc:publisher>{self.publisher}</dc:publisher>
"""
        
        # Add additional metadata
        for m in self.book.metadata:
            if m is None:
                continue
                
            # Handle different metadata formats
            try:
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
        for item in self.book.get_items():
            if not hasattr(item, 'file_name'):
                continue
                
            props = ""
            if hasattr(item, 'properties') and item.properties:
                props = f' properties="{" ".join(item.properties)}"'
            
            manifest_xml += f'        <item id="{item.id}" href="{item.file_name}" media-type="{item.media_type}"{props} />\n'
        
        manifest_xml += "    </manifest>\n"
        
        # Collect spine items
        spine_xml = '    <spine toc="ncx">\n'
        for item in self.book.spine:
            if isinstance(item, str):
                spine_xml += f'        <itemref idref="{item}" />\n'
            elif hasattr(item, 'id'):
                spine_xml += f'        <itemref idref="{item.id}" />\n'
        
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
                navpoints += f"""        <navPoint id="navpoint-{playorder}" playOrder="{playorder}">
            <navLabel>
                <text>{parent.title}</text>
            </navLabel>
            <content src="{parent.href}" />
"""
                playorder += 1
                
                # Add children
                for child in children:
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
        
        # Convert TOC to list items
        for item in self.book.toc:
            if isinstance(item, tuple) and len(item) == 2:
                # Item with children
                parent, children = item
                toc_items += f"""            <li>
                <a href="{parent.href}">{parent.title}</a>
                <ol>
"""
                # Add children
                for child in children:
                    toc_items += f"""                    <li><a href="{child.href}">{child.title}</a></li>
"""
                    
                toc_items += """                </ol>
            </li>
"""
            else:
                # Simple item
                if hasattr(item, 'href') and hasattr(item, 'title'):
                    toc_items += f"""            <li><a href="{item.href}">{item.title}</a></li>
"""
        
        # Create the full Nav content
        nav_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
    <title>Navigation</title>
    <meta charset="utf-8"/>
    <link rel="stylesheet" type="text/css" href="style/nav.css" />
</head>
<body>
    <nav epub:type="toc" id="toc">
        <h1>Table of Contents</h1>
        <ol>
{toc_items}
        </ol>
    </nav>
</body>
</html>"""
        
        # Write the Nav file
        with open(nav_path, 'w', encoding='utf-8') as f:
            f.write(nav_content)
            
        logger.debug(f"Created nav.xhtml at {nav_path}")


class FixedKepubBuilder(FixedEPUBBuilder, KepubBuilder):
    """Kobo EPUB Builder with workaround for the 'Document is empty' issue"""
    
    def write(self, filename: Optional[str] = None) -> str:
        """Write the KEPUB file.
        
        Args:
            filename: Optional filename for the KEPUB.
            
        Returns:
            str: Path to the written KEPUB file.
        """
        # Determine filename
        if filename is None:
            filename = self.title.replace(' ', '_') + ".kepub.epub"
        
        # Ensure it has the .kepub.epub extension
        if not filename.lower().endswith('.kepub.epub'):
            if filename.lower().endswith('.epub'):
                filename = filename[:-5] + ".kepub.epub"
            else:
                filename += ".kepub.epub"
        
        # Write the EPUB using the fixed method
        epub_path = super().write(filename)
        
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
