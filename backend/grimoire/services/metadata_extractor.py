"""Metadata extraction service - extracts metadata from PDFs and text."""

import re
import logging
from pathlib import Path
from dataclasses import dataclass, field

import fitz

logger = logging.getLogger(__name__)

# Known game systems for detection
KNOWN_GAME_SYSTEMS = [
    # D&D variants
    ("Dungeons & Dragons 5th Edition", ["5e", "5th edition", "d&d 5", "dnd 5", "fifth edition"]),
    ("Dungeons & Dragons 3.5", ["3.5e", "3.5 edition", "d&d 3.5", "dnd 3.5"]),
    ("Dungeons & Dragons 4th Edition", ["4e", "4th edition", "d&d 4", "dnd 4"]),
    ("Advanced Dungeons & Dragons", ["ad&d", "adnd", "1st edition", "2nd edition"]),
    ("Old-School Essentials", ["ose", "old school essentials", "old-school essentials"]),
    ("Basic Fantasy RPG", ["basic fantasy", "bfrpg"]),
    
    # Pathfinder
    ("Pathfinder 2nd Edition", ["pathfinder 2e", "pf2e", "pathfinder second edition"]),
    ("Pathfinder 1st Edition", ["pathfinder 1e", "pf1e", "pathfinder first edition", "pathfinder rpg"]),
    
    # OSR
    ("Dungeon Crawl Classics", ["dcc", "dungeon crawl classics"]),
    ("Mörk Borg", ["mork borg", "mörk borg"]),
    ("Mothership", ["mothership rpg", "mothership"]),
    ("Troika!", ["troika"]),
    ("Cairn", ["cairn"]),
    ("Into the Odd", ["into the odd"]),
    ("Electric Bastionland", ["electric bastionland"]),
    ("Knave", ["knave"]),
    ("The Black Hack", ["black hack"]),
    ("Worlds Without Number", ["wwn", "worlds without number"]),
    ("Stars Without Number", ["swn", "stars without number"]),
    
    # Other popular systems
    ("Call of Cthulhu", ["call of cthulhu", "coc"]),
    ("Savage Worlds", ["savage worlds", "swade"]),
    ("Fate", ["fate core", "fate accelerated", "fate rpg"]),
    ("Powered by the Apocalypse", ["pbta", "powered by the apocalypse"]),
    ("Blades in the Dark", ["blades in the dark", "bitd", "forged in the dark"]),
    ("GURPS", ["gurps"]),
    ("Shadowrun", ["shadowrun"]),
    ("Vampire: The Masquerade", ["vampire the masquerade", "vtm", "world of darkness"]),
    ("Cyberpunk", ["cyberpunk red", "cyberpunk 2020"]),
    ("Traveller", ["traveller", "mongoose traveller"]),
    ("13th Age", ["13th age"]),
    ("Shadow of the Demon Lord", ["shadow of the demon lord", "sotdl"]),
    ("Symbaroum", ["symbaroum"]),
    ("Forbidden Lands", ["forbidden lands"]),
    ("Year Zero Engine", ["year zero", "mutant year zero"]),
]

# Known publishers for detection
KNOWN_PUBLISHERS = [
    ("Wizards of the Coast", ["wizards of the coast", "wotc"]),
    ("Paizo", ["paizo", "paizo inc", "paizo publishing"]),
    ("Goodman Games", ["goodman games"]),
    ("Free League", ["free league", "fria ligan"]),
    ("Chaosium", ["chaosium"]),
    ("Modiphius", ["modiphius"]),
    ("Monte Cook Games", ["monte cook games", "mcg"]),
    ("Evil Hat Productions", ["evil hat"]),
    ("Kobold Press", ["kobold press"]),
    ("Green Ronin", ["green ronin"]),
    ("Pelgrane Press", ["pelgrane press"]),
    ("Pinnacle Entertainment", ["pinnacle entertainment", "pinnacle"]),
    ("Cubicle 7", ["cubicle 7"]),
    ("Necrotic Gnome", ["necrotic gnome"]),
    ("Exalted Funeral", ["exalted funeral"]),
    ("Tuesday Knight Games", ["tuesday knight games"]),
    ("Frog God Games", ["frog god games"]),
    ("Lamentations of the Flame Princess", ["lamentations of the flame princess", "lotfp"]),
    ("Sine Nomine Publishing", ["sine nomine"]),
    ("Stockholm Kartell", ["stockholm kartell"]),
]

# Genre keywords
GENRE_KEYWORDS = {
    "Fantasy": ["fantasy", "sword", "sorcery", "magic", "dragon", "dungeon", "medieval", "elves", "dwarves", "orcs"],
    "Horror": ["horror", "cthulhu", "lovecraft", "terror", "fear", "nightmare", "undead", "vampire", "zombie"],
    "Science Fiction": ["sci-fi", "science fiction", "space", "starship", "cyberpunk", "android", "alien", "future"],
    "Modern": ["modern", "contemporary", "urban", "present day", "real world"],
    "Historical": ["historical", "history", "ancient", "medieval", "victorian", "renaissance", "world war"],
}

# Product type keywords
PRODUCT_TYPE_KEYWORDS = {
    "Core Rulebook": ["core rulebook", "core rules", "player's handbook", "player handbook", "rulebook", "basic rules"],
    "Adventure": ["adventure", "module", "scenario", "campaign", "quest", "one-shot"],
    "Supplement": ["supplement", "sourcebook", "expansion", "companion", "guide"],
    "Bestiary": ["bestiary", "monster manual", "creature", "monsters"],
    "Setting": ["setting", "world", "campaign setting", "gazetteer"],
    "Character Options": ["class", "race", "subclass", "character options", "player options"],
    "GM Tools": ["gm", "game master", "dm", "dungeon master", "tools", "screen"],
    "Map": ["map", "battlemap", "dungeon map", "cartography"],
    "Zine": ["zine", "magazine", "issue", "volume"],
}


@dataclass
class ExtractedMetadata:
    """Container for extracted metadata."""
    title: str | None = None
    author: str | None = None
    publisher: str | None = None
    game_system: str | None = None
    genre: str | None = None
    product_type: str | None = None
    publication_year: int | None = None
    page_count: int | None = None
    keywords: str | None = None
    subject: str | None = None
    
    # Confidence scores (0-1)
    confidence: dict = field(default_factory=dict)
    
    # Source tracking
    sources: dict = field(default_factory=dict)
    
    def merge_with(self, other: "ExtractedMetadata", prefer_other: bool = False) -> "ExtractedMetadata":
        """Merge with another metadata object, filling in missing values."""
        result = ExtractedMetadata()
        
        for field_name in ["title", "author", "publisher", "game_system", "genre", 
                          "product_type", "publication_year", "page_count", "keywords", "subject"]:
            self_val = getattr(self, field_name)
            other_val = getattr(other, field_name)
            
            if prefer_other and other_val:
                setattr(result, field_name, other_val)
            elif self_val:
                setattr(result, field_name, self_val)
            else:
                setattr(result, field_name, other_val)
        
        # Merge confidence and sources
        result.confidence = {**self.confidence, **other.confidence}
        result.sources = {**self.sources, **other.sources}
        
        return result


def extract_pdf_metadata(pdf_path: Path) -> ExtractedMetadata:
    """Extract metadata from PDF file properties.
    
    Args:
        pdf_path: Path to the PDF file
        
    Returns:
        ExtractedMetadata with values from PDF properties
    """
    metadata = ExtractedMetadata()
    
    try:
        doc = fitz.open(pdf_path)
        
        metadata.page_count = len(doc)
        metadata.sources["page_count"] = "pdf"
        
        pdf_meta = doc.metadata
        
        if pdf_meta.get("title"):
            metadata.title = pdf_meta["title"].strip()
            metadata.sources["title"] = "pdf"
            
        if pdf_meta.get("author"):
            metadata.author = pdf_meta["author"].strip()
            metadata.sources["author"] = "pdf"
            
        if pdf_meta.get("subject"):
            metadata.subject = pdf_meta["subject"].strip()
            
        if pdf_meta.get("keywords"):
            metadata.keywords = pdf_meta["keywords"].strip()
            
        # Try to extract publisher from creator/producer
        creator = pdf_meta.get("creator", "")
        producer = pdf_meta.get("producer", "")
        
        # Check if creator contains a known publisher
        for pub_name, aliases in KNOWN_PUBLISHERS:
            for alias in aliases:
                if alias.lower() in creator.lower() or alias.lower() in producer.lower():
                    metadata.publisher = pub_name
                    metadata.sources["publisher"] = "pdf"
                    break
            if metadata.publisher:
                break
        
        # Try to extract year from creation date
        if pdf_meta.get("creationDate"):
            year_match = re.search(r"D:(\d{4})", pdf_meta["creationDate"])
            if year_match:
                year = int(year_match.group(1))
                if 1970 <= year <= 2030:
                    metadata.publication_year = year
                    metadata.sources["publication_year"] = "pdf"
        
        doc.close()
        
    except Exception as e:
        logger.warning(f"Error extracting PDF metadata from {pdf_path}: {e}")
    
    return metadata


def extract_first_pages_text(pdf_path: Path, max_pages: int = 5) -> str:
    """Extract text from the first few pages of a PDF.
    
    Args:
        pdf_path: Path to the PDF file
        max_pages: Maximum number of pages to extract
        
    Returns:
        Combined text from first pages
    """
    try:
        doc = fitz.open(pdf_path)
        pages_to_read = min(len(doc), max_pages)
        
        text_parts = []
        for i in range(pages_to_read):
            page = doc[i]
            text_parts.append(page.get_text())
        
        doc.close()
        return "\n".join(text_parts)
        
    except Exception as e:
        logger.warning(f"Error extracting text from {pdf_path}: {e}")
        return ""


def parse_metadata_from_text(text: str) -> ExtractedMetadata:
    """Parse metadata from extracted text (typically first few pages).
    
    Args:
        text: Text extracted from PDF
        
    Returns:
        ExtractedMetadata with values parsed from text
    """
    metadata = ExtractedMetadata()
    text_lower = text.lower()
    
    # Detect game system
    for system_name, aliases in KNOWN_GAME_SYSTEMS:
        for alias in aliases:
            if alias.lower() in text_lower:
                metadata.game_system = system_name
                metadata.sources["game_system"] = "text"
                metadata.confidence["game_system"] = 0.8
                break
        if metadata.game_system:
            break
    
    # Detect publisher
    for pub_name, aliases in KNOWN_PUBLISHERS:
        for alias in aliases:
            if alias.lower() in text_lower:
                metadata.publisher = pub_name
                metadata.sources["publisher"] = "text"
                metadata.confidence["publisher"] = 0.8
                break
        if metadata.publisher:
            break
    
    # Detect genre
    genre_scores = {}
    for genre, keywords in GENRE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in text_lower)
        if score > 0:
            genre_scores[genre] = score
    
    if genre_scores:
        best_genre = max(genre_scores, key=genre_scores.get)
        if genre_scores[best_genre] >= 2:  # Require at least 2 keyword matches
            metadata.genre = best_genre
            metadata.sources["genre"] = "text"
            metadata.confidence["genre"] = min(0.9, 0.5 + genre_scores[best_genre] * 0.1)
    
    # Detect product type
    type_scores = {}
    for ptype, keywords in PRODUCT_TYPE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in text_lower)
        if score > 0:
            type_scores[ptype] = score
    
    if type_scores:
        best_type = max(type_scores, key=type_scores.get)
        metadata.product_type = best_type
        metadata.sources["product_type"] = "text"
        metadata.confidence["product_type"] = min(0.9, 0.5 + type_scores[best_type] * 0.15)
    
    # Try to extract author from common patterns
    author_patterns = [
        r"(?:written|writing|author|by)[:\s]+([A-Z][a-z]+ [A-Z][a-z]+(?:\s*(?:,|and|&)\s*[A-Z][a-z]+ [A-Z][a-z]+)*)",
        r"(?:design|designer)[:\s]+([A-Z][a-z]+ [A-Z][a-z]+)",
        r"(?:created by)[:\s]+([A-Z][a-z]+ [A-Z][a-z]+)",
    ]
    
    for pattern in author_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            author = match.group(1).strip()
            # Clean up common suffixes
            author = re.sub(r"\s*(?:,\s*)?(?:layout|design|art|editing).*$", "", author, flags=re.IGNORECASE)
            if len(author) > 3 and len(author) < 200:
                metadata.author = author
                metadata.sources["author"] = "text"
                metadata.confidence["author"] = 0.7
                break
    
    # Try to extract year
    year_patterns = [
        r"(?:©|copyright|\(c\))\s*(\d{4})",
        r"(?:published|released|printed)[:\s]+.*?(\d{4})",
        r"(\d{4})\s+edition",
    ]
    
    for pattern in year_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            year = int(match.group(1))
            if 1970 <= year <= 2030:
                metadata.publication_year = year
                metadata.sources["publication_year"] = "text"
                metadata.confidence["publication_year"] = 0.8
                break
    
    return metadata


def parse_filename_metadata(filename: str) -> ExtractedMetadata:
    """Parse metadata from filename patterns.
    
    Common patterns:
    - "Publisher - Product Name.pdf"
    - "Game System - Product Name.pdf"
    - "Product Name (Publisher).pdf"
    
    Args:
        filename: The PDF filename
        
    Returns:
        ExtractedMetadata with values parsed from filename
    """
    metadata = ExtractedMetadata()
    
    # Remove extension
    name = Path(filename).stem
    
    # Check for "Publisher - Title" pattern
    if " - " in name:
        parts = name.split(" - ", 1)
        potential_publisher = parts[0].strip()
        potential_title = parts[1].strip() if len(parts) > 1 else None
        
        # Check if first part is a known publisher
        for pub_name, aliases in KNOWN_PUBLISHERS:
            if potential_publisher.lower() in [a.lower() for a in aliases] or potential_publisher.lower() == pub_name.lower():
                metadata.publisher = pub_name
                metadata.sources["publisher"] = "filename"
                if potential_title:
                    metadata.title = potential_title
                    metadata.sources["title"] = "filename"
                break
        
        # Check if first part is a known game system
        if not metadata.publisher:
            for system_name, aliases in KNOWN_GAME_SYSTEMS:
                if potential_publisher.lower() in [a.lower() for a in aliases]:
                    metadata.game_system = system_name
                    metadata.sources["game_system"] = "filename"
                    if potential_title:
                        metadata.title = potential_title
                        metadata.sources["title"] = "filename"
                    break
    
    # Check for "(Publisher)" suffix pattern
    paren_match = re.search(r"(.+?)\s*\(([^)]+)\)\s*$", name)
    if paren_match and not metadata.publisher:
        potential_title = paren_match.group(1).strip()
        potential_publisher = paren_match.group(2).strip()
        
        for pub_name, aliases in KNOWN_PUBLISHERS:
            if potential_publisher.lower() in [a.lower() for a in aliases]:
                metadata.publisher = pub_name
                metadata.title = potential_title
                metadata.sources["publisher"] = "filename"
                metadata.sources["title"] = "filename"
                break
    
    # If no title extracted yet, use cleaned filename
    if not metadata.title:
        # Clean up common patterns
        clean_name = name
        clean_name = re.sub(r"_", " ", clean_name)
        clean_name = re.sub(r"\s+", " ", clean_name)
        metadata.title = clean_name.strip()
        metadata.sources["title"] = "filename"
    
    return metadata


def extract_all_metadata(pdf_path: Path) -> ExtractedMetadata:
    """Extract metadata from all available sources and merge.
    
    Priority order:
    1. PDF embedded metadata (most reliable for title, author)
    2. Text parsing (best for game system, genre, product type)
    3. Filename parsing (fallback)
    
    Args:
        pdf_path: Path to the PDF file
        
    Returns:
        Merged ExtractedMetadata from all sources
    """
    # Extract from PDF properties
    pdf_metadata = extract_pdf_metadata(pdf_path)
    
    # Extract from first pages text
    first_pages_text = extract_first_pages_text(pdf_path, max_pages=5)
    text_metadata = parse_metadata_from_text(first_pages_text) if first_pages_text else ExtractedMetadata()
    
    # Extract from filename
    filename_metadata = parse_filename_metadata(pdf_path.name)
    
    # Merge: PDF > Text > Filename
    result = filename_metadata.merge_with(text_metadata, prefer_other=True)
    result = result.merge_with(pdf_metadata, prefer_other=True)
    
    # Always keep page_count from PDF
    result.page_count = pdf_metadata.page_count
    
    return result


def apply_metadata_to_product(product, metadata: ExtractedMetadata, overwrite: bool = False) -> dict:
    """Apply extracted metadata to a Product model.
    
    Args:
        product: Product model instance
        metadata: ExtractedMetadata to apply
        overwrite: If True, overwrite existing values
        
    Returns:
        Dict of fields that were updated
    """
    updated = {}
    
    field_mapping = {
        "title": "title",
        "author": "author",
        "publisher": "publisher",
        "game_system": "game_system",
        "genre": "genre",
        "product_type": "product_type",
        "publication_year": "publication_year",
        "page_count": "page_count",
    }
    
    for meta_field, product_field in field_mapping.items():
        meta_value = getattr(metadata, meta_field)
        if meta_value is None:
            continue
            
        current_value = getattr(product, product_field)
        
        # For title, don't overwrite if current looks like a real title (not just filename)
        if product_field == "title" and current_value and not overwrite:
            # Check if current title is just the filename stem
            if current_value != Path(product.file_name).stem:
                continue
        
        if overwrite or current_value is None:
            setattr(product, product_field, meta_value)
            updated[product_field] = meta_value
    
    return updated
