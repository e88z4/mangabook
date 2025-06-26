"""Image processing for manga pages.

This module provides functionality for processing manga images,
including resizing, format conversion, and page splitting for EPUBs.
"""

import os
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Union
import io
from PIL import Image, ImageOps, UnidentifiedImageError

from ..utils import ensure_directory, sanitize_filename

# Set up logging
logger = logging.getLogger(__name__)

# Constants for Kobo Clara HD resolution
KOBO_CLARA_WIDTH = 1072
KOBO_CLARA_HEIGHT = 1448
KOBO_ASPECT_RATIO = KOBO_CLARA_HEIGHT / KOBO_CLARA_WIDTH

# Default image quality
DEFAULT_QUALITY = 85

# Threshold for detecting wide pages (panorama/spread)
WIDE_PAGE_RATIO = 0.75  # If width/height > 0.75, consider it a wide page


class ImageProcessor:
    """Processes manga images for optimal EPUB display."""
    
    def __init__(self, output_dir: Optional[Union[str, Path]] = None,
                 target_width: int = KOBO_CLARA_WIDTH,
                 target_height: int = KOBO_CLARA_HEIGHT,
                 quality: int = DEFAULT_QUALITY,
                 split_wide_pages: bool = True):
        """Initialize the image processor.
        
        Args:
            output_dir: Directory to save processed images.
            target_width: Target width for processed images.
            target_height: Target height for processed images.
            quality: JPEG quality (1-100).
            split_wide_pages: Whether to split wide (double-page) images.
        """
        self.output_dir = Path(output_dir) if output_dir else None
        self.target_width = target_width
        self.target_height = target_height
        self.target_aspect_ratio = target_height / target_width
        self.quality = quality
        self.split_wide_pages = split_wide_pages
    
    def ensure_output_dir(self, subdir: Optional[str] = None) -> Path:
        """Ensure the output directory exists.
        
        Args:
            subdir: Optional subdirectory path.
            
        Returns:
            Path: The full output directory path.
        """
        if not self.output_dir:
            raise ValueError("Output directory not specified")
        
        if subdir:
            full_path = self.output_dir / subdir
        else:
            full_path = self.output_dir
        
        return ensure_directory(full_path)
    
    def is_wide_page(self, img: Image.Image) -> bool:
        """Check if an image is a wide page (double-page spread).
        
        Args:
            img: PIL Image object.
            
        Returns:
            bool: True if the image is a wide page.
        """
        width, height = img.size
        # If the width is relatively large compared to height, it's a wide page
        return width / height > WIDE_PAGE_RATIO * self.target_aspect_ratio
    
    def split_image(self, img: Image.Image) -> Tuple[Image.Image, Image.Image]:
        """Split a wide image into left and right parts.
        
        Args:
            img: PIL Image object to split.
            
        Returns:
            Tuple[Image.Image, Image.Image]: Left and right parts of the image.
        """
        width, height = img.size
        mid_point = width // 2
        
        left_part = img.crop((0, 0, mid_point, height))
        right_part = img.crop((mid_point, 0, width, height))
        
        return left_part, right_part
    
    def resize_image(self, img: Image.Image) -> Image.Image:
        """Resize an image to fit the target dimensions.
        
        Args:
            img: PIL Image object to resize.
            
        Returns:
            Image.Image: Resized image.
        """
        width, height = img.size
        img_aspect = height / width
        
        # Determine new dimensions
        if img_aspect > self.target_aspect_ratio:
            # Image is taller than target aspect ratio
            new_height = self.target_height
            new_width = int(new_height / img_aspect)
        else:
            # Image is wider than target aspect ratio
            new_width = self.target_width
            new_height = int(new_width * img_aspect)
        
        # Don't upscale images that are already smaller
        if width <= self.target_width and height <= self.target_height:
            return img
        
        # Resize using LANCZOS for best quality
        return img.resize((new_width, new_height), Image.LANCZOS)
    
    def optimize_image(self, img: Image.Image, format_: str = "JPEG") -> Image.Image:
        """Optimize an image for e-readers.
        
        Args:
            img: PIL Image object to optimize.
            format_: Output format.
            
        Returns:
            Image.Image: Optimized image.
        """
        # Convert to RGB if not already
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        
        # Apply additional optimizations if needed
        # (contrast enhancement, sharpening, etc. could be added here)
        
        return img
    
    def process_image(self, source_path: Union[str, Path], output_subdir: Optional[str] = None, 
                     filename: Optional[str] = None) -> List[Path]:
        """Process a single image.
        
        Args:
            source_path: Path to the source image.
            output_subdir: Subdirectory for output.
            filename: Optional filename for the output image.
            
        Returns:
            List[Path]: Paths to processed images (multiple if split).
        """
        source_path = Path(source_path)
        
        # Determine output directory
        out_dir = self.ensure_output_dir(output_subdir)
        
        # Use source filename if none provided
        if not filename:
            filename = source_path.stem
        
        # Load the image
        try:
            with Image.open(source_path) as img:
                output_paths = []
                
                # Check if it's a wide page and needs splitting
                if self.split_wide_pages and self.is_wide_page(img):
                    logger.debug(f"Splitting wide page: {source_path}")
                    left, right = self.split_image(img)
                    
                    # Process left part
                    left = self.resize_image(left)
                    left = self.optimize_image(left)
                    left_path = out_dir / f"{filename}_left.jpg"
                    left.save(left_path, "JPEG", quality=self.quality, optimize=True)
                    output_paths.append(left_path)
                    
                    # Process right part
                    right = self.resize_image(right)
                    right = self.optimize_image(right)
                    right_path = out_dir / f"{filename}_right.jpg"
                    right.save(right_path, "JPEG", quality=self.quality, optimize=True)
                    output_paths.append(right_path)
                else:
                    # Process as a single image
                    img = self.resize_image(img)
                    img = self.optimize_image(img)
                    img_path = out_dir / f"{filename}.jpg"
                    img.save(img_path, "JPEG", quality=self.quality, optimize=True)
                    output_paths.append(img_path)
                
                return output_paths
        except (IOError, UnidentifiedImageError) as e:
            logger.error(f"Error processing image {source_path}: {e}")
            return []
    
    def process_directory(self, source_dir: Union[str, Path], 
                         output_subdir: Optional[str] = None) -> Dict[str, List[Path]]:
        """Process all images in a directory.
        
        Args:
            source_dir: Directory containing source images.
            output_subdir: Subdirectory for output.
            
        Returns:
            Dict[str, List[Path]]: Mapping of source files to processed files.
        """
        source_dir = Path(source_dir)
        
        if not source_dir.exists() or not source_dir.is_dir():
            logger.error(f"Source directory does not exist: {source_dir}")
            return {}
        
        # Find all image files
        extensions = (".jpg", ".jpeg", ".png", ".webp")
        image_files = [f for f in sorted(source_dir.iterdir()) 
                      if f.is_file() and f.suffix.lower() in extensions]
        
        if not image_files:
            logger.warning(f"No images found in {source_dir}")
            return {}
        
        # Process each image
        result = {}
        for i, img_path in enumerate(image_files):
            filename = f"{i+1:03d}"  # Use sequential numbering
            processed_paths = self.process_image(
                img_path, 
                output_subdir=output_subdir,
                filename=filename
            )
            
            if processed_paths:
                result[str(img_path)] = processed_paths
        
        return result
    
    def detect_reading_direction(self, images_dir: Union[str, Path]) -> str:
        """Attempt to detect the reading direction of manga images.
        
        Args:
            images_dir: Directory containing manga images.
            
        Returns:
            str: "rtl" for right-to-left (manga style) or "ltr" for left-to-right.
        """
        # This is a simple heuristic - could be enhanced with ML in the future
        # For now, we'll assume manga is always right-to-left
        return "rtl"
