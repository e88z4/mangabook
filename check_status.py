#!/usr/bin/env python3

import asyncio
import json
import sys
from pathlib import Path
from mangabook.api import get_api

async def check_download_status(manga_id, language="en"):
    """Check download status for a manga"""
    api = await get_api()
    try:
        # Get manga details
        manga = await api.get_manga(manga_id)
        if not manga or not manga.get("data"):
            print(f"Error: Could not find manga with ID {manga_id}")
            return
            
        attributes = manga["data"]["attributes"]
        title = attributes.get("title", {}).get("en", "Unknown")
        print(f"Manga: {title} (ID: {manga_id})")
        
        # Get volumes
        volumes = await api.get_manga_volumes(manga_id, language)
        
        # Check if volumes include ungrouped chapters
        print(f"\nVolume keys: {sorted(list(volumes.keys()))}")
        
        # Check ungrouped chapters
        if "0" in volumes:
            print("\nUngrouped chapters (key='0'):")
            print(json.dumps(volumes["0"], indent=2))
        elif "none" in volumes:
            print("\nUngrouped chapters (key='none'):")
            print(json.dumps(volumes["none"], indent=2))
        else:
            print("\nNo ungrouped chapters found.")
            
    finally:
        await api.close()

if __name__ == "__main__":
    manga_id = sys.argv[1] if len(sys.argv) > 1 else "7f30dfc3-0b80-4dcc-a3b9-0cd746fac005"
    asyncio.run(check_download_status(manga_id))
