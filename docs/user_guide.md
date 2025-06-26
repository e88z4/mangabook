# MangaBook User Documentation

## Table of Contents

1. [Installation](#installation)
2. [Usage](#usage)
   - [Basic Commands](#basic-commands)
   - [Search for Manga](#search-for-manga)
   - [Download Manga](#download-manga)
   - [Batch Processing](#batch-processing)
   - [Download Queue](#download-queue)
   - [Reading History](#reading-history)
3. [Configuration](#configuration)
4. [Troubleshooting](#troubleshooting)
5. [FAQ](#faq)

## Installation

### Prerequisites

- Python 3.8 or higher
- pip (Python package manager)

### Steps

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/mangabook.git
   cd mangabook
   ```

2. Install the package with all dependencies:
   ```bash
   pip install -e .
   ```

   Alternatively, you can run the installation script:
   ```bash
   ./install.sh
   ```

3. Verify installation:
   ```bash
   mangabook --version
   ```

## Usage

### Basic Commands

MangaBook provides several commands:

- `search`: Search for manga by title
- `info`: Get information about a manga
- `download`: Download manga volumes
- `history`: View and manage reading history
- `queue`: Manage download queue
- `batch`: Process multiple manga

Run `mangabook --help` to see all available commands and options.

### Search for Manga

To search for manga:

```bash
mangabook search "One Piece"
```

This will display a list of manga matching your search query. You can then select a manga to view more details or download.

### Download Manga

To download a manga:

```bash
mangabook download --manga-id 32d76d19-8a05-4db0-9fc2-e0b0648fe9d0 --volumes 1,2,3
```

Or use the interactive mode:

```bash
mangabook download
```

This will guide you through searching for manga, selecting volumes, and downloading them.

Options:
- `--output`: Specify output directory
- `--keep-raw`: Keep raw downloaded files
- `--quality`: Set image quality (1-100)
- `--language`: Set language code (default: en)
- `--volumes`: Comma-separated list of volumes to download
- `--no-kobo`: Disable Kobo-specific EPUB format

### Batch Processing

Process multiple manga at once:

```bash
mangabook batch --manga-ids 32d76d19-8a05-4db0-9fc2-e0b0648fe9d0,b9738ede-e693-4c64-9b3a-2c7f9d0c8bca
```

This will add the specified manga to the download queue. You can then process the queue.

### Download Queue

Manage the download queue:

```bash
# View queue
mangabook queue list

# Process next job
mangabook queue process-next

# Process all queued jobs
mangabook queue process-all

# Clear queue
mangabook queue clear
```

### Reading History

View and manage reading history:

```bash
# View all manga in history
mangabook history list

# View recently updated manga
mangabook history recent

# Mark a volume as read
mangabook history mark-read --manga-id 32d76d19-8a05-4db0-9fc2-e0b0648fe9d0 --volume 1

# Delete manga from history
mangabook history delete --manga-id 32d76d19-8a05-4db0-9fc2-e0b0648fe9d0
```

## Configuration

MangaBook stores configuration in `~/.mangabook/config.json`. You can edit this file directly or use the `config` command:

```bash
# View current configuration
mangabook config show

# Set output directory
mangabook config set output_dir /path/to/output

# Set image quality
mangabook config set quality 90
```

## Troubleshooting

### Common Issues

#### Can't Connect to MangaDex API

If you're having trouble connecting to the MangaDex API:

1. Check your internet connection
2. Verify that MangaDex is not experiencing outages
3. If using a VPN, try disabling it
4. Try refreshing your authentication token: `mangabook auth refresh`

#### Download Failures

If downloads are failing:

1. Check your internet connection
2. Try downloading a different manga or volume
3. Try using the `--keep-raw` option to help diagnose issues
4. Try increasing the timeout with `mangabook config set timeout 60`

#### EPUB Validation Failures

If EPUB validation fails:

1. The EPUB may still be usable on most readers
2. Check the validation error message for details
3. Try using a different quality setting
4. Ensure you have the latest version of MangaBook

### Log Files

MangaBook creates log files in `~/.mangabook/logs/`. Check these files for detailed error information.

## FAQ

### General Questions

**Q: Is MangaBook legal?**
A: MangaBook uses the official MangaDex API to download manga that are freely available on MangaDex. It respects MangaDex's terms of service.

**Q: Which e-readers are supported?**
A: MangaBook's EPUBs are optimized for Kobo Clara, but should work on most e-readers that support the EPUB format.

**Q: Can I use MangaBook offline?**
A: You need an internet connection to search and download manga, but once downloaded, you can read them offline.

### Technical Questions

**Q: How can I increase download speed?**
A: Try adjusting concurrent download settings in the config: `mangabook config set max_concurrent 10`

**Q: How can I save disk space?**
A: Use lower quality settings and don't use the `--keep-raw` option: `mangabook download --quality 75`

**Q: Where are downloaded files stored?**
A: By default, in the `~/mangabook_output/` directory, but you can change this in the config or with the `--output` option.

**Q: How can I backup my reading history?**
A: Your reading history is stored in `~/.mangabook/history/manga_history.json`. You can make a copy of this file for backup.
