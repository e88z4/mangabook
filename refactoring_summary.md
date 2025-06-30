# EPUB/KEPUB Builder Refactoring Summary

## Key Improvements

This refactoring modernized the EPUB/KEPUB generation workflow to ensure:

1. **Strict EPUB Spec Compliance** - All generated files pass epubcheck validation
2. **Robust Navigation** - Properly structured nav.xhtml with valid landmarks
3. **Proper Cover Handling** - Dedicated cover image support with fallback to first page
4. **Clean XML Content** - Fixed invalid XML elements and attributes
5. **Resource Management** - No duplicate manifest items, all references exist and validate
6. **Module Renaming** - Renamed from `fixed_builder.py` to `enhanced_builder.py` for clarity

## Implementation Changes

1. **Builder Design**
   - Direct ZIP-based implementation bypassing ebooklib navigation issues
   - Proper encoding of filenames and IDs to be XML-compliant
   - Robust error handling for invalid metadata elements

2. **Cover Handling**
   - Looks for dedicated cover image (e.g., `cover.png`)
   - Falls back to first chapter image if no dedicated cover found
   - Proper cover reference in OPF and Nav files

3. **Navigation**
   - Manual generation of nav.xhtml for reliability
   - Fixed landmarks section to reference the correct cover path
   - Properly structured TOC with chapter entries

4. **File Organization**
   - XML and HTML cleanup to ensure validation
   - Replaced spaces in filenames with underscores for URI safety
   - Proper ID generation to ensure uniqueness and XML compliance

5. **Default Builder**
   - Enhanced builder is now the default
   - Legacy builder still available via `--use-enhanced-builder=false` flag

## Testing

All generated EPUB/KEPUB files now pass epubcheck with zero errors/warnings, validated with:

- Small test files with minimal content
- Large manga volumes (e.g., Detective Conan vol. 94 with ~190 pages)
- Various chapter structures and image formats

## Usage

The enhanced builder is now the default implementation. It can be used directly:

```python
from mangabook.epub.enhanced_builder import EnhancedEPUBBuilder, EnhancedKepubBuilder

# Create an EPUB
builder = EnhancedEPUBBuilder(
    title="My Manga Volume",
    output_dir="/path/to/output",
    language="en",
    author="Author Name"
)

# Add chapters...
builder.write()  # Outputs a valid EPUB file
```

Or through the CLI with the default settings:

```bash
mangabook download --manga-id <id> --volume <vol>
```
