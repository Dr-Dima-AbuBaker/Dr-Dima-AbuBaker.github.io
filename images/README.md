# Images Directory

This folder contains all images used in the portfolio.

## Structure

- **`profile/`** - Profile photos and headshots (carousel)
  - Recommended: 800×800px or larger
  - Format: `photo1.jpg`, `photo2.jpg`, etc.
  
- **`publications/`** - Images and thumbnails for research papers
  - Full images: 600×300px (`paper1-full.jpg`)
  - Thumbnails: 200×200px (`paper1-thumb.jpg`)
  
- **`projects/`** - Project showcase images
  - Recommended: 600×300px
  - Format: `project-name.jpg`
  
- **`lab/`** - Lab member headshots
  - Recommended: 150×150px (square)
  - Format: `firstname-lastname.jpg`

## Adding Images

1. Add your images to the appropriate subfolder
2. Update the paths in `data.json` to use relative paths:
   ```json
   {
     "src": "images/profile/photo1.jpg",
     "image": "images/publications/paper1-full.jpg",
     "thumbnail": "images/publications/paper1-thumb.jpg"
   }
   ```

## Migration Steps

To move from external URLs to local hosting:

1. Download the images you want to keep
2. Place them in the appropriate folders
3. Update `data.json` with the new paths
4. Commit and push to GitHub

GitHub Pages will serve these automatically from your repo.
