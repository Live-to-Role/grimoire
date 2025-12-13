"""
Structured JSON schemas for TTRPG content extraction.
These schemas define the structure for monsters, spells, items, and other game content.
"""

from pydantic import BaseModel, Field
from typing import Any
from enum import Enum


class DamageType(str, Enum):
    """Standard damage types across systems."""
    ACID = "acid"
    BLUDGEONING = "bludgeoning"
    COLD = "cold"
    FIRE = "fire"
    FORCE = "force"
    LIGHTNING = "lightning"
    NECROTIC = "necrotic"
    PIERCING = "piercing"
    POISON = "poison"
    PSYCHIC = "psychic"
    RADIANT = "radiant"
    SLASHING = "slashing"
    THUNDER = "thunder"


class Size(str, Enum):
    """Creature sizes."""
    TINY = "tiny"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    HUGE = "huge"
    GARGANTUAN = "gargantuan"


class AbilityScores(BaseModel):
    """Standard ability scores."""
    strength: int | None = Field(None, ge=1, le=30)
    dexterity: int | None = Field(None, ge=1, le=30)
    constitution: int | None = Field(None, ge=1, le=30)
    intelligence: int | None = Field(None, ge=1, le=30)
    wisdom: int | None = Field(None, ge=1, le=30)
    charisma: int | None = Field(None, ge=1, le=30)


class DamageEntry(BaseModel):
    """A damage roll entry."""
    dice: str = Field(..., description="Dice notation, e.g., '2d6+3'")
    damage_type: str | None = None
    average: int | None = None


class Attack(BaseModel):
    """An attack action."""
    name: str
    attack_type: str = Field(..., description="melee, ranged, spell")
    to_hit: int | None = None
    reach: str | None = None
    range: str | None = None
    targets: str | None = Field(None, description="e.g., 'one target'")
    damage: list[DamageEntry] = Field(default_factory=list)
    description: str | None = None


class Action(BaseModel):
    """A creature action or ability."""
    name: str
    description: str
    attack: Attack | None = None
    recharge: str | None = Field(None, description="e.g., '5-6' or 'short rest'")
    uses: int | None = None
    uses_per: str | None = Field(None, description="e.g., 'day', 'short rest'")


class Trait(BaseModel):
    """A creature trait or feature."""
    name: str
    description: str


class Monster(BaseModel):
    """A monster/creature stat block."""
    name: str
    size: str | None = None
    creature_type: str | None = None
    subtype: str | None = None
    alignment: str | None = None
    
    armor_class: int | None = None
    armor_type: str | None = None
    hit_points: int | None = None
    hit_dice: str | None = None
    
    speed: dict[str, int] = Field(default_factory=dict, description="e.g., {'walk': 30, 'fly': 60}")
    
    abilities: AbilityScores | None = None
    
    saving_throws: dict[str, int] = Field(default_factory=dict)
    skills: dict[str, int] = Field(default_factory=dict)
    
    damage_vulnerabilities: list[str] = Field(default_factory=list)
    damage_resistances: list[str] = Field(default_factory=list)
    damage_immunities: list[str] = Field(default_factory=list)
    condition_immunities: list[str] = Field(default_factory=list)
    
    senses: dict[str, str] = Field(default_factory=dict)
    languages: list[str] = Field(default_factory=list)
    
    challenge_rating: str | None = None
    experience_points: int | None = None
    proficiency_bonus: int | None = None
    
    traits: list[Trait] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    bonus_actions: list[Action] = Field(default_factory=list)
    reactions: list[Action] = Field(default_factory=list)
    legendary_actions: list[Action] = Field(default_factory=list)
    lair_actions: list[Action] = Field(default_factory=list)
    
    source_page: int | None = None
    source_system: str | None = Field(None, description="e.g., '5e', 'pf2e', 'osr'")


class SpellComponent(BaseModel):
    """Spell component requirements."""
    verbal: bool = False
    somatic: bool = False
    material: bool = False
    material_description: str | None = None
    material_cost: str | None = None
    material_consumed: bool = False


class Spell(BaseModel):
    """A spell definition."""
    name: str
    level: int = Field(..., ge=0, le=9, description="0 for cantrips")
    school: str | None = None
    ritual: bool = False
    
    casting_time: str | None = None
    range: str | None = None
    components: SpellComponent | None = None
    duration: str | None = None
    concentration: bool = False
    
    description: str | None = None
    higher_levels: str | None = Field(None, description="At higher levels text")
    
    classes: list[str] = Field(default_factory=list)
    subclasses: list[str] = Field(default_factory=list)
    
    damage: DamageEntry | None = None
    save: str | None = Field(None, description="e.g., 'Dexterity'")
    
    source_page: int | None = None
    source_system: str | None = None


class MagicItem(BaseModel):
    """A magic item definition."""
    name: str
    rarity: str | None = Field(None, description="common, uncommon, rare, very rare, legendary, artifact")
    item_type: str | None = Field(None, description="e.g., 'weapon', 'armor', 'wondrous item'")
    requires_attunement: bool = False
    attunement_requirements: str | None = None
    
    description: str | None = None
    properties: list[str] = Field(default_factory=list)
    
    charges: int | None = None
    recharge: str | None = None
    
    source_page: int | None = None
    source_system: str | None = None


class RandomTableEntry(BaseModel):
    """An entry in a random table."""
    roll_min: int
    roll_max: int
    result: str
    sub_table: list["RandomTableEntry"] | None = None


class RandomTable(BaseModel):
    """A rollable random table."""
    name: str
    die: str = Field(..., description="e.g., 'd20', '2d6', 'd100'")
    entries: list[RandomTableEntry]
    description: str | None = None
    source_page: int | None = None


class Encounter(BaseModel):
    """An encounter definition."""
    name: str | None = None
    description: str | None = None
    monsters: list[dict[str, Any]] = Field(default_factory=list, description="List of {name, count, notes}")
    difficulty: str | None = None
    environment: str | None = None
    treasure: list[str] = Field(default_factory=list)
    source_page: int | None = None


class Location(BaseModel):
    """A location/room definition."""
    name: str | None = None
    number: str | None = Field(None, description="Room number like '1a' or '12'")
    description: str | None = None
    read_aloud: str | None = Field(None, description="Boxed text to read to players")
    features: list[str] = Field(default_factory=list)
    encounters: list[Encounter] = Field(default_factory=list)
    treasure: list[str] = Field(default_factory=list)
    connections: list[str] = Field(default_factory=list, description="Connected room numbers")
    source_page: int | None = None


class NPC(BaseModel):
    """A non-player character."""
    name: str
    role: str | None = Field(None, description="e.g., 'shopkeeper', 'quest giver', 'villain'")
    race: str | None = None
    occupation: str | None = None
    location: str | None = None
    
    description: str | None = None
    personality: str | None = None
    motivation: str | None = None
    secret: str | None = None
    
    stat_block: Monster | None = None
    
    source_page: int | None = None


class ExtractedContent(BaseModel):
    """Container for all extracted structured content from a product."""
    product_id: int | None = None
    product_title: str | None = None
    
    monsters: list[Monster] = Field(default_factory=list)
    spells: list[Spell] = Field(default_factory=list)
    magic_items: list[MagicItem] = Field(default_factory=list)
    random_tables: list[RandomTable] = Field(default_factory=list)
    encounters: list[Encounter] = Field(default_factory=list)
    locations: list[Location] = Field(default_factory=list)
    npcs: list[NPC] = Field(default_factory=list)
    
    extraction_method: str | None = None
    extraction_confidence: float | None = None
