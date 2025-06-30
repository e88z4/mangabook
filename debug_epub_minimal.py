#!/usr/bin/env python

"""
Debug script for EPUBBuilder
"""

import os
import sys
from pathlib import Path
import ebooklib
from ebooklib import epub
import logging

logging.basicConfig(level=logging.DEBUG)

def main():
    print("Creating a minimal EPUB...")
    
    # Create a book
    book = epub.EpubBook()
    
    # Set metadata
    book.set_identifier('id123456')
    book.set_title('Test Title')
    book.set_language('en')
    book.add_author('Test Author')
    
    # Create CSS
    css = epub.EpubItem(
        uid='style_default',
        file_name='style/default.css',
        media_type='text/css',
        content='body { font-family: Arial, sans-serif; }'
    )
    book.add_item(css)
    
    # Create a chapter
    c1 = epub.EpubHtml(title='Chapter 1', file_name='chap_01.xhtml', lang='en')
    c1.content = '<html><body><h1>Chapter 1</h1><p>This is a test chapter.</p></body></html>'
    c1.add_item(css)
    book.add_item(c1)
    
    # Add navigation files
    book.add_item(epub.EpubNcx())
    nav = epub.EpubNav()
    nav.add_item(css)
    book.add_item(nav)
    
    # Set spine and TOC
    book.spine = ['nav', c1]
    book.toc = [epub.Link('chap_01.xhtml', 'Chapter 1', 'chapter1')]
    
    # Create output directory
    os.makedirs('test_output', exist_ok=True)
    
    # Write EPUB file
    epub_path = 'test_output/debug_test.epub'
    try:
        print("Writing EPUB...")
        epub.write_epub(epub_path, book, {})
        print(f"EPUB written to {epub_path}")
    except Exception as e:
        print(f"Error writing EPUB: {e}")
        import traceback
        traceback.print_exc()
    
if __name__ == '__main__':
    main()
