"""
Generate Codex seed data from Grimoire's sample PDFs.
This creates a JSON file that can be used to seed the Codex database.
"""

import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))


def calculate_file_hash(file_path: str) -> str:
    """Calculate SHA-256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def get_pdf_metadata(file_path: str) -> dict:
    """Extract basic metadata from PDF."""
    try:
        import fitz
        doc = fitz.open(file_path)
        metadata = doc.metadata
        page_count = len(doc)
        doc.close()
        return {
            "page_count": page_count,
            "pdf_title": metadata.get("title"),
            "pdf_author": metadata.get("author"),
            "pdf_creator": metadata.get("creator"),
        }
    except Exception as e:
        print(f"  Warning: Could not read PDF metadata: {e}")
        return {}


# Product data from Grimoire database (manually curated/verified)
PRODUCTS = [
    {
        "file_name": "City of Brass (5E).pdf",
        "title": "City of Brass",
        "publisher": "Frog God Games",
        "publication_year": 2018,
        "game_system": "D&D 5E",
        "product_type": "Adventure",
        "level_range_min": 12,
        "level_range_max": 18,
        "description": "A massive planar adventure set in the legendary City of Brass on the Elemental Plane of Fire.",
        "dtrpg_url": "https://www.drivethrurpg.com/product/240996/City-of-Brass-5th-Edition",
    },
    {
        "file_name": "Loot the Body - Stryp Tygur- Live at the Cobb Estate 1967 - AgainstTheCultOfTheHippieCommune_Spreads.pdf",
        "title": "Against The Cult Of The Hippie Commune",
        "publisher": "Loot the Body",
        "publication_year": 2023,
        "game_system": "OSR",
        "product_type": "Adventure",
        "level_range_min": 1,
        "level_range_max": 3,
        "description": "A psychedelic OSR adventure involving a mysterious hippie commune.",
    },
    {
        "file_name": "Mouth of Doom - level1c.pdf",
        "title": "Mouth of Doom",
        "publisher": "Frog God Games",
        "publication_year": None,
        "game_system": "OSR",
        "product_type": "Adventure",
        "level_range_min": 1,
        "level_range_max": 5,
        "description": "A classic dungeon crawl adventure.",
    },
    {
        "file_name": "Secret_of_the_Whispering_God_01-11-25.pdf",
        "title": "Secret of the Whispering God",
        "publisher": None,
        "publication_year": 2025,
        "game_system": "D&D 5E",
        "product_type": "Adventure",
        "level_range_min": 1,
        "level_range_max": 5,
        "description": "An adventure involving ancient secrets and a mysterious deity.",
    },
    {
        "file_name": "Tegel Manor (5E).pdf",
        "title": "Tegel Manor",
        "publisher": "Frog God Games",
        "publication_year": 2019,
        "game_system": "D&D 5E",
        "product_type": "Adventure",
        "level_range_min": 1,
        "level_range_max": 10,
        "description": "The classic haunted house adventure, updated for 5th Edition. Explore the sprawling Tegel Manor and uncover its dark secrets.",
        "dtrpg_url": "https://www.drivethrurpg.com/product/278806/Tegel-Manor-5th-Edition",
    },
    {
        "file_name": "The Art Of Drowning.pdf",
        "title": "The Art of Drowning",
        "publisher": None,
        "publication_year": None,
        "game_system": "OSR",
        "product_type": "Adventure",
        "level_range_min": None,
        "level_range_max": None,
        "description": "A dark and atmospheric adventure.",
    },
    {
        "file_name": "The_Waking_of_Willowby_Hall_1.3_Pages.pdf",
        "title": "The Waking of Willowby Hall",
        "publisher": "Questing Beast Games",
        "publication_year": 2020,
        "game_system": "OSR",
        "product_type": "Adventure",
        "level_range_min": 1,
        "level_range_max": 3,
        "description": "A chaotic adventure in a haunted manor with a rampaging giant. Compatible with most OSR systems.",
        "dtrpg_url": "https://www.drivethrurpg.com/product/348439/The-Waking-of-Willowby-Hall",
    },
    {
        "file_name": "The_Wanting_Wizard.pdf",
        "title": "The Wanting Wizard",
        "publisher": None,
        "publication_year": None,
        "game_system": "OSR",
        "product_type": "Adventure",
        "level_range_min": 1,
        "level_range_max": 3,
        "description": "A short adventure involving a wizard with unusual desires.",
    },
    {
        "file_name": "The_Whispering_Sanctum.pdf",
        "title": "The Whispering Sanctum",
        "publisher": "M.T. Black Games",
        "publication_year": 2024,
        "game_system": "D&D 5E",
        "product_type": "Adventure",
        "level_range_min": 1,
        "level_range_max": 5,
        "description": "A mysterious sanctum holds ancient secrets waiting to be discovered.",
    },
    {
        "file_name": "Valley of the Red Scorpion V1.pdf",
        "title": "Valley of the Red Scorpion",
        "publisher": None,
        "publication_year": None,
        "game_system": "OSR",
        "product_type": "Adventure",
        "level_range_min": 5,
        "level_range_max": 5,
        "description": "An adventure set in a dangerous desert valley.",
    },
    {
        "file_name": "Wrath_of_the_Sea_Lich_GygaxInk.pdf",
        "title": "Wrath of the Sea Lich",
        "publisher": "Gaxx Worx, LLC",
        "publication_year": 2025,
        "game_system": "Shadowdark RPG",
        "product_type": "Adventure",
        "level_range_min": 3,
        "level_range_max": 5,
        "description": "A nautical adventure featuring an undead threat from the depths. Written for Shadowdark RPG.",
    },
]


def main():
    pdf_dir = Path(__file__).parent.parent / "pdfs"
    output_file = Path(__file__).parent.parent / "codex_seed_data.json"
    
    if not pdf_dir.exists():
        print(f"Error: PDF directory not found: {pdf_dir}")
        return
    
    seed_data = {
        "version": "1.0",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "source": "grimoire-sample-pdfs",
        "products": [],
    }
    
    for product in PRODUCTS:
        file_path = pdf_dir / product["file_name"]
        
        if not file_path.exists():
            print(f"Warning: File not found: {file_path}")
            continue
        
        print(f"Processing: {product['title']}")
        
        # Calculate file hash
        file_hash = calculate_file_hash(str(file_path))
        file_size = file_path.stat().st_size
        
        # Get PDF metadata
        pdf_meta = get_pdf_metadata(str(file_path))
        
        # Build Codex entry
        entry = {
            "file_hashes": [file_hash],  # Array to support multiple versions
            "file_size": file_size,
            "page_count": pdf_meta.get("page_count"),
            "title": product["title"],
            "publisher": product.get("publisher"),
            "publication_year": product.get("publication_year"),
            "game_system": product.get("game_system"),
            "product_type": product.get("product_type"),
            "level_range": {
                "min": product.get("level_range_min"),
                "max": product.get("level_range_max"),
            } if product.get("level_range_min") or product.get("level_range_max") else None,
            "description": product.get("description"),
            "external_links": {},
            "tags": [],
            "confidence": 1.0,  # Human verified
            "source": "manual",
        }
        
        # Add external links if available
        if product.get("dtrpg_url"):
            entry["external_links"]["drivethrurpg"] = product["dtrpg_url"]
        
        seed_data["products"].append(entry)
        print(f"  Hash: {file_hash[:16]}...")
        print(f"  Size: {file_size:,} bytes")
        print(f"  Pages: {pdf_meta.get('page_count', 'unknown')}")
    
    # Write seed data
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(seed_data, f, indent=2, ensure_ascii=False)
    
    print(f"\nSeed data written to: {output_file}")
    print(f"Total products: {len(seed_data['products'])}")


if __name__ == "__main__":
    main()
