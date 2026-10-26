"""Match Codex products to Grimoire files.

Codex was seeded from the DriveThruRPG library, not from Grimoire, so there is
no hash to join on. Grimoire files live at
`<drive>\\Drivethrurpg\\<Publisher>\\<DTRPG title>\\<file>.pdf`, and the title
folder matches the Codex title. Order (first hit wins): publisher + title
folder, title folder alone, fuzzy. `manual` matches are never overwritten.
"""

import html
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import PureWindowsPath

from rapidfuzz import fuzz, process
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grimoire.models import Product
from grimoire.models.classification import CodexProduct

# Apostrophes are dropped rather than spaced so "Gygax's" and "Gygax’s" agree.
_APOSTROPHES = re.compile(r"['‘’ʼ`]")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize(s: str | None) -> str:
    if not s:
        return ""
    # Codex titles carry HTML entities from the DTRPG import ("&amp;", "&#65533;").
    s = _APOSTROPHES.sub("", html.unescape(s))
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return _NON_ALNUM.sub(" ", s.lower()).strip()


def product_folder(file_path: str) -> tuple[str, str] | None:
    """(publisher folder, product folder) for a DriveThruRPG-layout path."""
    parts = PureWindowsPath(file_path).parts
    lowered = [p.lower() for p in parts]
    if "drivethrurpg" not in lowered:
        return None
    rest = parts[lowered.index("drivethrurpg") + 1:]
    if len(rest) != 3:
        return None
    return rest[0], rest[1]


# A leading DTRPG product id, as in Codex titles like "1008573-BeachEncounters".
_LEADING_ID = re.compile(r"^\d{5,} ")
_DIGITS = re.compile(r"\d+")

_Key = tuple[str, tuple[str, ...]]


def _fuzzy_key(normalized: str) -> tuple[str, tuple[str, ...]]:
    """(spaceless text, its numbers) for fuzzy comparison.

    Spaces are dropped so "BeachEncounters" meets "Beach Encounters". The numbers
    must agree exactly: issue 1 and issue 10 of a series are otherwise ~98% alike.
    """
    s = _LEADING_ID.sub("", normalized)
    return s.replace(" ", ""), tuple(sorted(_DIGITS.findall(s)))


def choose_file(candidates: list[Product]) -> Product | None:
    """Pick one file from a folder: usable first, extracted, most pages, biggest."""
    usable = [
        p for p in candidates
        if not (p.is_duplicate or p.is_missing or p.text_unextractable)
    ]
    if not usable:
        return None
    return max(
        usable,
        key=lambda p: (bool(p.text_extracted), p.page_count or 0, p.file_size or 0),
    )


@dataclass
class MatchReport:
    folder: int = 0
    title: int = 0
    fuzzy: int = 0
    none: int = 0
    unmatched: list[tuple[str, str, str]] = field(default_factory=list)


class _Index:
    """Grimoire products grouped the three ways the matcher looks them up."""

    def __init__(self, products: list[Product]):
        self.by_id = {p.id: p for p in products}
        self.by_folder: dict[tuple[str, str], list[Product]] = defaultdict(list)
        self.folders_by_title: dict[str, set[tuple[str, str]]] = defaultdict(set)
        # Per normalised publisher: fuzzy key -> products it stands for.
        self.choices: dict[str, dict[_Key, list[Product]]] = defaultdict(lambda: defaultdict(list))
        self.all_choices: dict[_Key, list[Product]] = defaultdict(list)
        for p in products:
            parsed = product_folder(p.file_path)
            if parsed is None:
                continue
            key = (normalize(parsed[0]), normalize(parsed[1]))
            self.by_folder[key].append(p)
            self.folders_by_title[key[1]].add(key)
        # A folder name stands for its whole folder; a file stem for that file.
        for (pub, folder), group in self.by_folder.items():
            self._add_choice(pub, folder, group)
            for p in group:
                self._add_choice(pub, normalize(PureWindowsPath(p.file_name).stem), [p])

    def _add_choice(self, pub: str, s: str, members: list[Product]) -> None:
        key = _fuzzy_key(s)
        if key[0]:
            self.choices[pub][key].extend(members)
            self.all_choices[key].extend(members)

    def choose_in_folder(self, key: tuple[str, str]) -> Product | None:
        """choose_file over a folder, falling back to what its duplicates duplicate.

        A folder whose only file is a duplicate of another edition still names a
        book Grimoire has; without the fallback it would go unmatched.
        """
        group = self.by_folder.get(key, [])
        chosen = choose_file(group)
        if chosen is None:
            originals = [self.by_id.get(p.duplicate_of_id) for p in group if p.is_duplicate]
            chosen = choose_file([p for p in originals if p is not None])
        return chosen


def _fuzzy(index: _Index, cp: CodexProduct, threshold: int) -> tuple[Product, float] | None:
    # Plain ratio, not token_set_ratio: token-set scores a title ~92 against any
    # folder whose words it mostly contains, so every "Dungeon Crawl Classics #N"
    # module matched the "Dungeon Crawl Classics RPG" corebook folder.
    text, digits = _fuzzy_key(normalize(cp.title))
    if not text:
        return None
    pub = normalize(cp.publisher)
    pool = index.choices.get(pub, {}) if pub else index.all_choices
    candidates = {key: key[0] for key in pool if key[1] == digits}
    if not candidates:
        return None
    hits = process.extract(
        text, candidates, scorer=fuzz.ratio, score_cutoff=threshold, limit=None
    )
    if not hits:
        return None
    best = max(score for _, score, _ in hits)
    tied = [p for _, score, key in hits if score == best for p in pool[key]]
    chosen = choose_file(tied)
    return (chosen, best) if chosen else None


def _match_one(index: _Index, cp: CodexProduct, threshold: int) -> tuple[str, Product, float | None] | None:
    pub, title = normalize(cp.publisher), normalize(cp.title)

    chosen = index.choose_in_folder((pub, title))
    if chosen:
        return "folder", chosen, None

    # Title alone is trusted only when exactly one folder carries it.
    folders = index.folders_by_title.get(title, set())
    if len(folders) == 1:
        chosen = index.choose_in_folder(next(iter(folders)))
        if chosen:
            return "title", chosen, None

    hit = _fuzzy(index, cp, threshold)
    if hit:
        return "fuzzy", hit[0], hit[1]
    return None


async def match_all(db: AsyncSession, fuzzy_threshold: int = 90) -> MatchReport:
    products = list((await db.execute(select(Product))).scalars())
    index = _Index(products)
    report = MatchReport()
    codex_rows = (await db.execute(select(CodexProduct).order_by(CodexProduct.slug))).scalars()
    for cp in codex_rows:
        if cp.match_method == "manual":
            continue
        hit = _match_one(index, cp, fuzzy_threshold)
        if hit is None:
            cp.grimoire_product_id, cp.match_method, cp.match_score = None, "none", None
            report.none += 1
            report.unmatched.append((cp.slug, cp.title, cp.publisher or ""))
            continue
        method, product, score = hit
        cp.grimoire_product_id, cp.match_method, cp.match_score = product.id, method, score
        setattr(report, method, getattr(report, method) + 1)
    await db.flush()
    return report
