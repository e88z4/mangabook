# Changelog

## Version 0.2.0 (2025-06-27)

### Added
- Robust local file structure with consistent zero-padding:
  - Volume directories use 3-digit padding (e.g., `volume_001`)
  - Chapter directories use 4-digit padding (e.g., `chapter_0001_title`)
  - Page files use 3-digit padding (e.g., `001.jpg`)
- POSIX-compliant filename sanitization:
  - Added option for strict POSIX compliance or cross-platform usage
  - Improved handling of special characters and non-ASCII text
  - Enhanced edge case handling (leading dots, all-dot filenames, etc.)
- JSON manifest file system for tracking downloaded content:
  - Tracks download timestamps, file status, and updates
  - Marks chapters and pages as complete/incomplete or valid/invalid
  - Supports update detection and local file validation
- Local-first download strategy:
  - Skips downloading if valid file exists locally
  - Validates existing files before using them
  - Maintains manifest of downloaded files with status information
- Update detection and handling:
  - Compares local manifest with remote API data
  - Re-downloads entire chapters when updates are detected
  - Updates manifest with new information
- Enhanced CLI options:
  - Added `--check-local` flag to enable local file checking
  - Added `--force-download` flag to bypass local file checking
- Improved download reporting:
  - Added statistics for downloaded, skipped, and failed files
  - Includes retry counts and success rates in summary
- Comprehensive unit tests for new functionality

### Changed
- Updated path generation functions to use consistent padding
- Modified downloader to support local file checking
- Enhanced workflow.py with improved file handling and statistics
- Updated command handling to support new options
- Improved error messages and download reporting

### Fixed
- Improved handling of exceptional cases in file operations
- Enhanced retry logic for failed downloads with proper delays
- Fixed issues with inconsistent file naming conventions

## Version 0.1.0 (Initial Release)

- Initial implementation of MangaBook
- Basic manga downloading and EPUB creation functionality
- CLI interface for search, download, and conversion
- Support for MangaDex API integration
