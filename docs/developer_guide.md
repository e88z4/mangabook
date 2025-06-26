# MangaBook Developer Documentation

## Architecture Overview

MangaBook is built with a modular architecture designed for flexibility, extensibility, and maintainability. The application follows clean code principles and is organized into distinct modules with clear responsibilities.

## High-Level Architecture

```
                      ┌─────────┐
                      │   CLI   │
                      └────┬────┘
                           │
                           ▼
   ┌──────────┐       ┌────────────┐       ┌──────────┐
   │  Config  │◄──────┤  Workflow  ├──────►│  Error   │
   └──────────┘       └─────┬──────┘       └──────────┘
                           │
                 ┌─────────┼─────────────┐
                 │         │             │
                 ▼         ▼             ▼
         ┌───────────┐ ┌─────────┐ ┌──────────┐
         │    API    │ │Downloader│ │   EPUB   │
         └───────────┘ └──┬────┬──┘ └────┬─────┘
                         │    │          │
                         ▼    ▼          ▼
                 ┌────────┐ ┌────────┐ ┌─────────┐
                 │Parallel│ │ History│ │  Image  │
                 └────────┘ └────────┘ └─────────┘
```

## Module Descriptions

### Core Modules

#### `__main__.py`

The entry point of the application, which sets up the CLI commands and initializes the application.

#### `cli.py`

Defines the command-line interface using the Click library, handles user input, and delegates to appropriate workflows.

#### `workflow.py`

Orchestrates the manga processing workflow, coordinating between API calls, downloading, image processing, and EPUB generation.

#### `config.py`

Manages application configuration, including loading and saving settings, and providing defaults.

#### `error.py`

Provides centralized error handling, categorization, and reporting.

### Functional Modules

#### `api.py`

Wraps the MangaDex API for manga search, retrieval, and metadata access.

#### `auth.py`

Handles authentication with the MangaDex API, including token storage and renewal.

#### `downloader.py`

Manages downloading manga chapters and images from MangaDex.

#### `parallel.py`

Provides utilities for parallel processing, including concurrent downloads, API caching, and task queues.

#### `history.py`

Tracks manga reading history, downloaded volumes, and update checking.

#### `batch.py`

Implements batch processing capabilities for handling multiple manga downloads.

#### `ui.py`

Contains user interface utilities, including colored output, progress indicators, and formatting.

#### `utils.py`

Contains shared utility functions used across multiple modules.

### EPUB Subpackage

#### `epub/builder.py`

Builds standard EPUB files from processed manga images.

#### `epub/kobo.py`

Extends the EPUB builder with Kobo-specific enhancements.

#### `epub/image.py`

Processes manga images, including optimization, splitting, and formatting.

## Extension Points

MangaBook is designed to be extensible. Here are the primary extension points for developers:

### 1. API Sources

To add support for additional manga sources beyond MangaDex:

1. Create a new API wrapper module (e.g., `api_komga.py`)
2. Implement the same interface as `api.py`
3. Register the new source in `workflow.py`

### 2. E-reader Support

To optimize for additional e-readers beyond Kobo:

1. Create a new module in the `epub` package (e.g., `epub/kindle.py`)
2. Extend the `EPUBBuilder` class similar to how `KepubBuilder` does
3. Implement e-reader specific modifications
4. Register the new builder in `workflow.py`

### 3. Image Processors

To add alternative image processing techniques:

1. Extend the `ImageProcessor` class in `epub/image.py` or create a new class
2. Implement the new processing methods
3. Register the new processor in `workflow.py`

### 4. CLI Commands

To add new commands:

1. Add new command functions in `cli.py` using the Click decorator pattern
2. Implement the command logic either inline or in appropriate modules

## Development Guidelines

### Code Style

- Follow PEP 8 for Python code style
- Use meaningful variable names and descriptive docstrings
- Use type annotations throughout the codebase
- Organize imports: standard library, third party, local

### Error Handling

- Use the centralized error handling system in `error.py`
- Categorize errors appropriately
- Provide user-friendly error messages

### Testing

- Write unit tests for critical functionality
- Use appropriate test fixtures and mocks
- Test error handling and edge cases

### Documentation

- Write comprehensive docstrings for all public functions and classes
- Keep this developer documentation up to date with architectural changes
- Document extension points and customization options

## Development Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/mangabook.git
   cd mangabook
   ```

2. Install in development mode:
   ```bash
   pip install -e .
   ```

3. Install development dependencies:
   ```bash
   pip install -r requirements-dev.txt
   ```

4. Run tests:
   ```bash
   pytest
   ```

## Performance Considerations

- The `parallel.py` module provides utilities for optimizing performance
- Use `DownloadManager` for parallel downloading
- Use `ApiCache` to cache API responses
- Use `ProcessingQueue` for asynchronous image processing
- Be mindful of memory usage, especially with large manga volumes

## Memory Optimization

- Release large objects as soon as they're no longer needed
- Use generator expressions where appropriate
- Consider using `io.BytesIO` instead of loading entire files into memory
- Implement resource cleanup with context managers
