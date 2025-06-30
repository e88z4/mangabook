#!/usr/bin/env python3

from PIL import Image, ImageDraw
import os

def create_test_wide_page():
    # Create a wide page image (2000x1000)
    img = Image.new('RGB', (2000, 1000), color='white')
    draw = ImageDraw.Draw(img)
    
    # Draw a line down the middle to visualize the split
    draw.line([(1000, 0), (1000, 1000)], fill='black', width=5)
    
    # Draw text on each half
    draw.text((500, 500), "LEFT PAGE", fill='black')
    draw.text((1500, 500), "RIGHT PAGE", fill='black')
    
    # Draw a rectangle on the left side
    draw.rectangle([(100, 100), (900, 900)], outline='red', width=5)
    
    # Draw a circle on the right side
    draw.ellipse([(1100, 100), (1900, 900)], outline='blue', width=5)
    
    # Save the image
    os.makedirs('test_images', exist_ok=True)
    img.save('test_images/synthetic_wide_page.jpg')
    print("Created synthetic wide page image at: test_images/synthetic_wide_page.jpg")

if __name__ == "__main__":
    create_test_wide_page()
