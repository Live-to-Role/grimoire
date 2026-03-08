"""Thumbnail generation service for product covers."""

import logging
from pathlib import Path

from PIL import Image

from grimoire.config import settings
from grimoire.models import Product

logger = logging.getLogger(__name__)


def generate_thumbnail(
    cover_path: Path,
    size: tuple[int, int] = (300, 400),
    quality: int = 85,
) -> tuple[Path | None, Path | None]:
    """Generate WebP and JPEG thumbnails from a cover image.
    
    Args:
        cover_path: Path to the source cover image
        size: Target size (width, height) for the thumbnail
        quality: Quality setting for compression (1-100)
        
    Returns:
        Tuple of (webp_path, jpeg_path) or (None, None) on failure
    """
    try:
        if not cover_path.exists():
            logger.error(f"Cover image not found: {cover_path}")
            return None, None
            
        # Create thumbnails directory
        thumbnails_dir = settings.covers_dir / "thumbnails"
        thumbnails_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate output paths
        cover_stem = cover_path.stem
        webp_path = thumbnails_dir / f"{cover_stem}.webp"
        jpeg_path = thumbnails_dir / f"{cover_stem}.jpg"
        
        # Load and process image
        with Image.open(cover_path) as img:
            # Convert to RGB if necessary (handles RGBA, grayscale, etc.)
            if img.mode != "RGB":
                img = img.convert("RGB")
            
            # Calculate aspect-preserving resize
            img_width, img_height = img.size
            target_width, target_height = size
            
            # Calculate scaling to fit within target size
            width_ratio = target_width / img_width
            height_ratio = target_height / img_height
            scale_ratio = min(width_ratio, height_ratio)
            
            new_width = int(img_width * scale_ratio)
            new_height = int(img_height * scale_ratio)
            
            # Resize image
            img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # Create canvas with target size and center the image
            canvas = Image.new("RGB", size, (255, 255, 255))
            paste_x = (target_width - new_width) // 2
            paste_y = (target_height - new_height) // 2
            canvas.paste(img_resized, (paste_x, paste_y))
            
            # Save WebP version
            canvas.save(webp_path, "WEBP", quality=quality, method=6)
            
            # Save JPEG fallback
            canvas.save(jpeg_path, "JPEG", quality=quality, optimize=True)
            
        logger.info(f"Generated thumbnails for {cover_path.name}")
        return webp_path, jpeg_path
        
    except Exception as e:
        logger.error(f"Failed to generate thumbnail for {cover_path}: {e}")
        return None, None


def generate_thumbnail_for_product(product: Product) -> bool:
    """Generate thumbnails for a product's cover image.
    
    Args:
        product: Product model instance
        
    Returns:
        True if thumbnails were generated successfully
    """
    if not product.cover_extracted or not product.cover_image_path:
        logger.warning(f"Product {product.id} has no cover to generate thumbnail from")
        return False
        
    cover_path = Path(product.cover_image_path)
    webp_path, jpeg_path = generate_thumbnail(cover_path)
    
    if webp_path and jpeg_path:
        # Store the WebP path (preferred format)
        product.thumbnail_path = str(webp_path)
        return True
    
    return False


def get_thumbnail_path(product: Product, prefer_webp: bool = True) -> Path | None:
    """Get the thumbnail path for a product.
    
    Args:
        product: Product model instance
        prefer_webp: If True, return WebP path; otherwise JPEG
        
    Returns:
        Path to thumbnail or None if not available
    """
    if not product.thumbnail_path:
        return None
        
    thumbnail_path = Path(product.thumbnail_path)
    
    if prefer_webp and thumbnail_path.suffix == ".webp":
        return thumbnail_path
    elif not prefer_webp:
        # Return JPEG fallback
        jpeg_path = thumbnail_path.with_suffix(".jpg")
        if jpeg_path.exists():
            return jpeg_path
            
    return thumbnail_path if thumbnail_path.exists() else None
