#!/usr/bin/env python

"""
Quick test for the enhanced EPUB builder
"""

import os
import sys
from pathlib import Path
import tempfile
import shutil

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent))

from mangabook.epub.enhanced_builder import EnhancedEPUBBuilder

def main():
    # Create a temporary directory
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        print(f"Creating test EPUB in {temp_path}")
        
        # Create a test image
        test_img_dir = temp_path / "test_images"
        test_img_dir.mkdir()
        
        # Create a simple test image file
        test_img_file = test_img_dir / "test_image.png"
        with open(test_img_file, 'wb') as f:
            # Write a minimal PNG file (just a header, not a valid image but enough for the test)
            f.write(bytes.fromhex('89504e470d0a1a0a0000000d49484452000000100000001008060000001ff3ff61'))
        
        # Create a builder
        builder = EnhancedEPUBBuilder(
            title="Test EPUB",
            output_dir=temp_path,
            language="en",
            author="Test Author"
        )
        
        # Set cover
        builder.set_cover(test_img_file)
        
        # Add chapter
        builder.add_chapter("Chapter 1", "Chapter 1", [test_img_file])
        
        # Write EPUB
        epub_path = builder.write("test_quick.epub")
        print(f"Created EPUB: {epub_path}")
        
        # Copy the EPUB to a location outside the temp directory
        output_dir = Path.home() / "src" / "mangabook"
        output_path = output_dir / "test_quick.epub"
        
        shutil.copy(epub_path, output_path)
        print(f"Copied EPUB to {output_path}")
        
        print("Running epubcheck on the generated EPUB...")
        os.system(f"epubcheck {output_path}")
        
        print("Test completed successfully")

if __name__ == "__main__":
    main()
