# MangaBook

A Python console application to download manga from MangaDex and create Kobo-compatible EPUB files.

## Features

- Search and download manga from MangaDex API
- Convert manga chapters to high-quality Kobo EPUB (kepub.epub) files
- Organize downloads by manga title and volume
- Support for manga with wide pages (double-page spreads)
- Selection of the best scanlation group automatically
- Volume range selection for batch downloading
- Interactive mode with colorful UI for easy manga selection
- Parallel downloading for improved performance
- API response caching for faster repeat operations
- Reading history tracking and update checking
- Batch processing and download queue management
- EPUB validation with epubcheck (if available)
- Comprehensive error handling and recovery
- Detailed download and conversion summaries with ETA
- POSIX-compliant filename handling for cross-platform compatibility
- Robust local file structure with consistent zero-padding
- Local-first download strategy (skip downloading if valid files exist)
- JSON manifest tracking for downloaded content with timestamps
- Update detection for changed or new content
- Enhanced CLI options for controlling download behavior
- **NEW:** Enhanced EPUB/KEPUB builder with direct ZIP manipulation for strict EPUB compliance
- **NEW:** Support for large manga volumes through robust navigation handling
- **NEW:** Options to use either standard or enhanced builders
- **NEW:** Proper cover handling and epubcheck validation
- **NEW:** Fixed EPUB/KEPUB generation for both regular volumes and ungrouped chapters
- **NEW:** Improved ungrouped chapter handling and text-based cover generation
- **NEW:** Official MangaDex volume cover integration - uses the correct cover art for each volume
- **NEW:** Canonical Kobo collection folders for easy device upload - organizes all .kepub.epub files in one place
- **NEW:** Improved search functionality across all languages
- **NEW:** Support for downloading ungrouped chapters (chapters not assigned to volumes)
- **NEW:** Language selection from available translations for each manga
- **NEW:** Automatic updates for ongoing manga with the --updates flag (overwrite existing files with new chapters)
- **NEW:** File history lifecycle management (keeps download history for the last 30 days only)

## Requirements

- Python 3.8 or higher
- Required Python packages (installed automatically):
  - ebooklib>=0.17.1
  - Pillow>=10.0.0
  - requests>=2.31.0
  - click>=8.1.3
  - tqdm>=4.66.1
  - beautifulsoup4>=4.9.0
  - aiohttp>=3.8.0
  - colorama>=0.4.6
- Optional tools:
  - epubcheck (for EPUB validation)

## Advanced Features

### Enhanced EPUB/KEPUB Builder

The application now includes an enhanced EPUB/KEPUB builder that addresses issues with large manga volumes and ensures strict EPUB specification compliance. This builder:

- Uses direct ZIP manipulation to create valid EPUB/KEPUB files
- Properly handles navigation and TOC for large manga volumes
- Ensures correct file and folder structure for all e-readers
- Properly manages image manifests and spine entries
- Includes Kobo-specific enhancements for optimal reading on Kobo devices
- Creates valid EPUBs that pass epubcheck validation
- Uses proper cover handling with correct metadata

The enhanced builder is enabled by default but can be disabled with the `--use-enhanced-builder=False` option if needed.

### Official MangaDex Cover Integration

MangaBook now fetches and uses the official volume covers from MangaDex:

- Automatically queries the MangaDex API for volume-specific cover art
- Downloads high-quality official covers from MangaDex servers
- Uses the official cover in the EPUB/KEPUB metadata
- Falls back to using the first chapter image if no official cover is found
- Can be controlled with the `--use-official-covers` flag (default: True)

### Canonical Kobo Collection

For Kobo users, MangaBook can now organize all your .kepub.epub files into a canonical directory structure:

- Creates a dedicated `{manga-title}_kobo` folder for each manga series
- Collects all .kepub.epub files for the manga in this folder
- Makes it easy to sync all volumes to your Kobo device at once
- Perfect for simple `rsync` or drag-and-drop transfers to your device
- Includes a README file with upload instructions
- Can be controlled with the `--create-kobo-collection` flag (default: True)

### Enhanced Search and Download Functionality

MangaBook now offers improved search and download capabilities:

- **Cross-Language Search**: Search for manga titles across all languages supported by MangaDex
- **Language Selection**: Choose from all available translations for your selected manga
- **Ungrouped Chapter Support**: Download chapters that aren't assigned to a specific volume
  - Chapters are collected in a dedicated "ungrouped_chapters" folder
  - EPUBs for ungrouped chapters use clear naming: `{manga-title} - Chapters {range}`
- **Wide Page Detection and Splitting**: Automatically detects and properly splits wide manga pages for optimal reading
  - Double-page spreads are split into left and right pages
  - Maintains proper reading order in the final EPUB

The interactive mode has been updated with all these features, providing a guided interface for finding and downloading exactly what you want.

### Local File Management

MangaBook intelligently checks for existing local files before downloading, avoiding unnecessary downloads and bandwidth usage. This behavior can be controlled with:

- `--check-local`: Check for existing files (default: True)
- `--force-download`: Force download even if local files exist (default: False)

## Usage

### Command Line Interface

```bash
# Search for a manga
mangabook search "Detective Conan"

# Download specific volumes
mangabook download MANGA_ID --volumes "1-10"

# Download only ungrouped chapters
mangabook download MANGA_ID --ungrouped

# Download only ungrouped chapters
mangabook download MANGA_ID --ungrouped

# Download and update ungrouped chapters (overwrites existing files)
mangabook download MANGA_ID --updates

# Force overwrite existing files
mangabook download MANGA_ID --force-overwrite

# Download with specific options
mangabook download MANGA_ID --volumes "1,3,5" --language en --kobo --quality 85 --use-enhanced-builder

# Interactive mode (recommended for beginners)
mangabook interactive
```

### Command Line Options

```
--volumes TEXT           Volumes to download (e.g., "1-10" or "1,3,5")
--language TEXT          Language code (e.g., "en", "ja")
--output TEXT            Output directory
--keep-raw               Keep raw downloaded files
--quality INTEGER        Image quality (1-100)
--kobo                   Create Kobo-compatible EPUB (default: True)
--use-enhanced-builder   Use the enhanced builder for more reliable EPUB generation (default: True)
--use-official-covers    Use official MangaDex volume covers when available (default: True)
--create-kobo-collection Create a canonical Kobo collection folder for easy device upload (default: True)
--no-validate            Skip EPUB validation
--check-local            Check for valid local files before downloading (default: True)
--force-download         Force download even if local files exist
```

## Installation

### From Source

```bash
# Clone the repository with submodules
git clone --recurse-submodules https://github.com/yourusername/mangabook.git
cd mangabook

# Create a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install the package in development mode
pip install -e .
```

### Using pip (when available)

```bash
# Install from PyPI
pip install mangabook
```

## Usage

### Basic Commands

```bash
# Search for manga
mangabook search "one piece"

# Get manga information
mangabook info 32d76d19-8a05-4db0-9fc2-e0b0648fe9d0

# Download manga volumes
mangabook download 32d76d19-8a05-4db0-9fc2-e0b0648fe9d0 --volumes "1,3-5"

# Download with local file checking (skip downloading files that already exist and are valid)
mangabook download 32d76d19-8a05-4db0-9fc2-e0b0648fe9d0 --volumes "1,3-5" --check-local

# Force download (ignore existing files)
mangabook download 32d76d19-8a05-4db0-9fc2-e0b0648fe9d0 --volumes "1,3-5" --force-download

# Start interactive mode
mangabook interactive

# Run tests
mangabook test

# Check environment
mangabook check

# Validate an EPUB file
mangabook validate path/to/manga.epub

# View download history
mangabook history

# Batch processing
mangabook batch --manga-ids id1,id2,id3

# Manage download queue
mangabook queue list
mangabook queue process

# Check updates for downloaded manga
mangabook history check-updates
```

### Command Options

#### Download Command

```bash
mangabook download 32d76d19-8a05-4db0-9fc2-e0b0648fe9d0 [OPTIONS]
```

Options:
- `--volumes`, `-v`: Volumes to download (e.g., '1,3-5,7')
- `--language`, `-l`: Language for translation (default: 'en')
- `--output`, `-o`: Output directory
- `--keep-raw`: Keep raw downloaded files
- `--quality`: Image quality (1-100, default: 85)
- `--kobo`: Create Kobo-compatible EPUB (default: true)
- `--no-validate`: Skip EPUB validation
- `--parallel`, `-p`: Number of parallel downloads (default: 5)
- `--cache`: Use API response caching (default: true)

#### Search Command

```bash
mangabook search "manga title" [OPTIONS]
```

Options:
- `--language`, `-l`: Language for results (default: 'en')
- `--limit`: Maximum number of results (default: 10)

### Interactive Mode

For the easiest experience, use the interactive mode:

```bash
mangabook interactive
```

This will guide you through:
1. Logging in to MangaDex (optional)
2. Searching for manga
3. Selecting from results
4. Viewing manga details
5. Selecting volumes to download
6. Setting output options
7. Downloading and converting

## Authentication

To log in to MangaDex (recommended for best results):

```bash
mangabook login
```

You'll be prompted for your username and password. Your credentials are stored securely.

To log out:

```bash
mangabook logout
```

## Troubleshooting

### Common Issues

#### Error: "MangaDex API is not accessible"
- Check your internet connection
- Verify that MangaDex servers are online
- Try again later as MangaDex may have rate limits

#### Error: "EpubCheck not found in PATH"
- This is a warning, not an error
- Install epubcheck to enable validation: https://github.com/w3c/epubcheck
- Add epubcheck to your PATH

#### Error: "Failed to download chapter"
- Ensure you have a stable internet connection
- Try logging in with `mangabook login`
- The chapter might be unavailable or restricted

#### Error: "No volumes selected"
- Ensure you're entering volume numbers correctly
- Some manga might not have volume information, try individual chapters

#### Low Disk Space
- Free up disk space
- Use the `--quality` option to reduce image size
- Download fewer volumes at a time

### Debugging

For detailed debug information:

```bash
mangabook --debug COMMAND
```

Debug logs are stored in the log directory:

```bash
mangabook --log-dir /path/to/logs COMMAND
```

To check your environment:

```bash
mangabook check --full
```

## Project Structure

```
mangabook/
├── mangadex-api/         # Git submodule for MangaDex API
├── mangabook/            # Main package directory
│   ├── __init__.py
│   ├── __main__.py       # Entry point
│   ├── api.py            # API wrapper
│   ├── auth.py           # Authentication handling
│   ├── cli.py            # Command line interface
│   ├── config.py         # Configuration management
│   ├── downloader.py     # Manga downloading
│   ├── error.py          # Error handling
│   ├── testing.py        # Testing functionality
│   ├── utils.py          # Utility functions
│   ├── workflow.py       # Download and conversion workflow
│   ├── parallel.py       # Parallel processing utilities
│   ├── history.py        # Reading history tracking
│   ├── batch.py          # Batch processing functionality
│   ├── ui.py             # User interface enhancements
│   └── epub/             # EPUB generation subpackage
│       ├── __init__.py
│       ├── builder.py    # EPUB creation
│       ├── kobo.py       # Kobo-specific modifications
│       └── image.py      # Image processing
```

## Advanced Features

### Parallel Downloading

MangaBook uses parallel downloading to improve performance. You can adjust the concurrency settings:

```bash
# Set maximum concurrent chapter downloads
mangabook config set max_concurrent_chapters 5

# Set maximum concurrent volume downloads
mangabook config set max_concurrent_volumes 2
```

### API Response Caching

API responses are cached to improve performance and reduce API calls:

```bash
# Enable or disable caching
mangabook config set use_cache true

# Set cache expiration time (in seconds)
mangabook config set cache_max_age 3600

# Clear cache
mangabook cache clear
```

### Reading History

MangaBook tracks your downloaded manga and reading history:

```bash
# View all manga in history
mangabook history list

# View recently updated manga
mangabook history recent

# Mark a volume as read
mangabook history mark-read --manga-id <id> --volume <vol>

# Check for updates to your manga
mangabook history check-updates
```

### Batch Processing

Process multiple manga at once:

```bash
# Add manga to download queue
mangabook batch add --manga-id <id> --volumes 1-5

# Process download queue
mangabook queue process-all
```

## Documentation

Comprehensive documentation is available in the `docs` directory:

- [User Guide](docs/user_guide.md)
- [Developer Guide](docs/developer_guide.md)

## License

[MIT License](LICENSE)