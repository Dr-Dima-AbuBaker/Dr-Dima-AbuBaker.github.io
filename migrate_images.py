#!/usr/bin/env python3
"""
Image Migration Helper
======================
Downloads external images from data.json and saves them locally.
Updates data.json paths to use local references.

Usage:
    python migrate_images.py                    # dry run (shows what will happen)
    python migrate_images.py --download         # actually download images
    python migrate_images.py --update-json      # update data.json paths
    python migrate_images.py --download --update-json   # do both

Requirements:
    pip install requests pillow
"""

import json
import os
import sys
import argparse
import hashlib
from urllib.parse import urlparse
from pathlib import Path

try:
    import requests
    from PIL import Image
    from io import BytesIO
except ImportError:
    print("Missing dependencies. Install with:")
    print("  pip install requests pillow")
    sys.exit(1)


DATA_FILE = "data.json"
IMAGES_DIR = "images"


def get_image_type_and_name(url, context):
    """Determine where to save an image based on context."""
    # Profile photos
    if context == "profile":
        return "profile", f"photo-{hashlib.md5(url.encode()).hexdigest()[:8]}.jpg"
    
    # Lab members
    if context == "lab":
        return "lab", f"member-{hashlib.md5(url.encode()).hexdigest()[:8]}.jpg"
    
    # Projects
    if context == "project":
        return "projects", f"project-{hashlib.md5(url.encode()).hexdigest()[:8]}.jpg"
    
    # Publications - full image
    if context == "pub-image":
        return "publications", f"paper-{hashlib.md5(url.encode()).hexdigest()[:8]}-full.jpg"
    
    # Publications - thumbnail
    if context == "pub-thumb":
        return "publications", f"paper-{hashlib.md5(url.encode()).hexdigest()[:8]}-thumb.jpg"
    
    return "other", f"img-{hashlib.md5(url.encode()).hexdigest()[:8]}.jpg"


def download_image(url, output_path):
    """Download an image from URL and save it."""
    try:
        response = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        response.raise_for_status()
        
        # Open and optionally resize
        img = Image.open(BytesIO(response.content))
        
        # Convert to RGB if necessary
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background
        
        # Save
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        img.save(output_path, 'JPEG', quality=90, optimize=True)
        return True
    except Exception as e:
        print(f"  ✗ Failed: {e}")
        return False


def collect_images(data):
    """Collect all external image URLs from data.json."""
    images = []
    
    # Profile photos
    for photo in data.get("profile", {}).get("photos", []):
        url = photo.get("src", "")
        if url.startswith("http"):
            images.append({"url": url, "context": "profile", "path": ["profile", "photos"], "key": "src"})
    
    # Lab members
    for group in data.get("lab", {}).get("members", []):
        for i, person in enumerate(group.get("people", [])):
            url = person.get("image", "")
            if url.startswith("http"):
                images.append({"url": url, "context": "lab", "path": ["lab", "members", group, "people", i], "key": "image"})
    
    # Projects
    for i, project in enumerate(data.get("projects", [])):
        url = project.get("image", "")
        if url.startswith("http"):
            images.append({"url": url, "context": "project", "path": ["projects", i], "key": "image"})
    
    # Publications
    for i, pub in enumerate(data.get("publications", [])):
        img_url = pub.get("image", "")
        if img_url.startswith("http"):
            images.append({"url": img_url, "context": "pub-image", "path": ["publications", i], "key": "image"})
        
        thumb_url = pub.get("thumbnail", "")
        if thumb_url.startswith("http"):
            images.append({"url": thumb_url, "context": "pub-thumb", "path": ["publications", i], "key": "thumbnail"})
    
    return images


def main():
    parser = argparse.ArgumentParser(description="Migrate external images to local hosting")
    parser.add_argument("--download", action="store_true", help="Download images")
    parser.add_argument("--update-json", action="store_true", help="Update data.json with local paths")
    args = parser.parse_args()
    
    if not os.path.exists(DATA_FILE):
        print(f"Error: {DATA_FILE} not found")
        sys.exit(1)
    
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    images = collect_images(data)
    
    print(f"\nFound {len(images)} external images\n")
    print("=" * 70)
    
    for img in images:
        folder, filename = get_image_type_and_name(img["url"], img["context"])
        local_path = f"{IMAGES_DIR}/{folder}/{filename}"
        
        print(f"\n{img['context'].upper():15} {img['url'][:50]}...")
        print(f"                → {local_path}")
        
        if args.download:
            output_path = os.path.join(os.getcwd(), local_path)
            print(f"                  Downloading...", end=" ")
            if download_image(img["url"], output_path):
                print("✓")
                img["downloaded_path"] = local_path
            else:
                img["downloaded_path"] = None
    
    print("\n" + "=" * 70)
    
    if args.update_json and args.download:
        print("\nUpdating data.json...")
        # TODO: Implement path updates in data.json
        # This would require careful JSON path navigation
        print("  (Update logic not yet implemented - manually update paths for now)")
    
    if not args.download and not args.update_json:
        print("\nDRY RUN - No changes made")
        print("\nTo download images: python migrate_images.py --download")
        print("Then manually update paths in data.json to use local references")


if __name__ == "__main__":
    main()
