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