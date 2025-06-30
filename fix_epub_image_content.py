#!/usr/bin/env python

"""
Debug script to fix EPUB image content issues
This script focuses on generating properly structured XHTML content for image pages
"""

import os
import sys
from pathlib import Path
import shutil
import tempfile
import logging
from PIL import Image
import random
import traceback

from mangabook.epub.builder import EPUBBuilder
from mangabook.epub.kobo import KepubBuilder
from mangabook.utils import ensure_directory

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def create_test_image(path: Path, size=(800, 600), color=None):
    """Create a test image file"""
    if color is None:
        # Generate random color
        color = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
    
    # Create a new image with random color
    img = Image.new('RGB', size, color)
    img.save(path)
    return path

def main():
    print("Testing EPUB image content fix...")
    
    # Create a test output directory
    output_dir = Path("./test_output")
    ensure_directory(output_dir)
    
    # Create a temporary directory for test images
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Create test images
        images = []
        for i in range(3):
            img_path = temp_path / f"test_image_{i}.png"
            create_test_image(img_path)
            images.append(img_path)
        
        # Create a cover image
        cover_path = temp_path / "cover.jpg"
        create_test_image(cover_path, color=(255, 0, 0))  # Red cover
        
        print(f"Created {len(images)} test images and a cover")
        
        try:
            # Create a basic EPUB builder
            builder = EPUBBuilder(
                title="Test EPUB Image Fix",
                output_dir=output_dir,
                language="en",
                author="Test Author"
            )
            
            # Set the cover
            builder.set_cover(cover_path)
            print("Set cover image")
            
            # Add images as a chapter
            builder.add_chapter("chapter1", "Chapter 1", images)
            print("Added chapter with images")
            
            # Debug spine and structure before writing
            print("\nDEBUG - Book structure before writing:")
            print(f"Spine items: {len(builder.spine)}")
            print(f"TOC items: {len(builder.toc)}")
            print(f"Images: {len(builder.images)}")
            print(f"Chapter items: {sum(len(pages) for pages in builder.chapters.values())}")
            
            # Finalize and debug again
            builder.finalize()
            print("\nDEBUG - Book structure after finalize:")
            print(f"Spine items: {len(builder.spine)}")
            print(f"Book spine items: {len(builder.book.spine)}")
            print(f"Book TOC items: {len(builder.book.toc)}")
            
            # Print spine details
            print("\nDEBUG - Spine contents:")
            for i, item in enumerate(builder.book.spine):
                if hasattr(item, 'file_name'):
                    print(f"  {i}: {item.file_name}")
                else:
                    print(f"  {i}: {item}")
            
            # Print image page details
            print("\nDEBUG - Sample image page content:")
            if builder.chapters and 'chapter1' in builder.chapters and builder.chapters['chapter1']:
                sample_page = builder.chapters['chapter1'][0]
                print(f"Sample page ID: {sample_page.id}")
                print(f"Sample page file name: {sample_page.file_name}")
                print(f"Sample page content:\n{sample_page.content[:500]}...")
            
            # Write EPUB
            epub_path = builder.write("test_image_fix.epub")
            print(f"Wrote EPUB to: {epub_path}")
            
            # Create a Kobo EPUB using the same approach
            kobo_builder = KepubBuilder(
                title="Test Kepub Image Fix",
                output_dir=output_dir,
                language="en",
                author="Test Author"
            )
            
            # Set the cover
            kobo_builder.set_cover(cover_path)
            
            # Add images as a chapter
            kobo_builder.add_chapter("chapter1", "Chapter 1", images)
            
            # Finalize and write the KEPUB
            kepub_path = kobo_builder.write("test_image_fix.kepub.epub")
            print(f"Wrote KEPUB to: {kepub_path}")
            
        except Exception as e:
            print(f"Error: {e}")
            traceback.print_exc()
    
    print("\nTest completed.")

if __name__ == "__main__":
    main()
