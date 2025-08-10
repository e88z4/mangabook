#!/bin/bash
# Installation script for MangaBook

set -e  # Exit on error

# Print colored messages
print_green() {
    echo -e "\033[0;32m$1\033[0m"
}

print_yellow() {
    echo -e "\033[0;33m$1\033[0m"
}

print_red() {
    echo -e "\033[0;31m$1\033[0m"
}

print_blue() {
    echo -e "\033[0;34m$1\033[0m"
}

# Check Python version
print_blue "Checking Python version..."
PYTHON_VERSION=$(python3 --version)

if [[ $PYTHON_VERSION =~ Python\ 3\.[0-9]+ ]]; then
    print_green "Found $PYTHON_VERSION"
else
    print_red "Python 3.8 or higher is required"
    exit 1
fi

# Check if we're in a virtual environment
if [[ -z "$VIRTUAL_ENV" ]]; then
    print_yellow "No virtual environment detected."
    read -p "Would you like to create one? [Y/n] " CREATE_VENV
    
    if [[ "$CREATE_VENV" =~ ^[Nn]$ ]]; then
        print_yellow "Proceeding without virtual environment..."
    else
        print_blue "Creating virtual environment..."
        python3 -m venv venv
        
        if [ -f venv/bin/activate ]; then
            source venv/bin/activate
            print_green "Virtual environment activated"
        elif [ -f venv/Scripts/activate ]; then
            source venv/Scripts/activate
            print_green "Virtual environment activated"
        else
            print_red "Failed to activate virtual environment"
            exit 1
        fi
    fi
fi

# Update submodules
print_blue "Updating git submodules..."
if command -v git &> /dev/null; then
    git submodule update --init --recursive
    print_green "Submodules updated"
else
    print_yellow "Git not found, skipping submodule update"
    print_yellow "If this is the first install, make sure the mangadex-api submodule is present"
fi



# Install dependencies
print_blue "Installing dependencies..."
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
print_green "Dependencies installed"

# Install mangadex-api submodule in editable mode
print_blue "Installing mangadex-api submodule..."
python3 -m pip install -e ./mangadex-api
print_green "mangadex-api submodule installed"

# Install package in development mode
print_blue "Installing MangaBook..."
python3 -m pip install -e .
print_green "MangaBook installed successfully"

# Check if epubcheck is installed
print_blue "Checking for epubcheck..."
if command -v epubcheck &> /dev/null; then
    print_green "epubcheck found"
else
    print_yellow "epubcheck not found. EPUB validation will be limited."
    print_yellow "To install epubcheck:"
    print_yellow "  - Download from https://github.com/w3c/epubcheck/releases"
    print_yellow "  - Add to your PATH"
fi

# Final instructions
print_blue "\n========================================"
print_green "MangaBook has been successfully installed!"
print_blue "========================================"
print_yellow "\nTo use MangaBook:"
echo "  - Run 'mangabook --help' for available commands"
echo "  - Try 'mangabook interactive' for guided experience"
echo "  - Run 'mangabook check' to verify your environment"
echo ""
print_yellow "For issues or questions, please check:"
echo "  - README.md for usage instructions"
echo "  - https://github.com/yourusername/mangabook for updates"
echo ""

# Run environment check
read -p "Would you like to run an environment check now? [Y/n] " RUN_CHECK
if [[ ! "$RUN_CHECK" =~ ^[Nn]$ ]]; then
    mangabook check
fi

print_green "Happy manga reading!"
