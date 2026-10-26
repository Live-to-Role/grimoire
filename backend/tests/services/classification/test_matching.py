import itertools

from grimoire.models import CodexProduct, Product
from grimoire.services.classification.matching import (
    choose_file,
    match_all,
    normalize,
    product_folder,
)

_ids = itertools.count(1)


def _product(path: str, **kw) -> Product:
    n = next(_ids)
    defaults = dict(
        file_path=path,
        file_name=path.rsplit("\\", 1)[-1],
        file_size=1000,
        file_hash=f"h{n}",
        is_duplicate=False,
        is_missing=False,
        text_unextractable=False,
        text_extracted=True,
        page_count=10,
    )
    defaults.update(kw)
    return Product(**defaults)


def _codex(n: int, title: str, publisher: str | None) -> CodexProduct:
    return CodexProduct(
        id=f"00000000-0000-0000-0000-{n:012d}", slug=f"slug-{n}", title=title, publisher=publisher
    )


def test_normalize_strips_punctuation_and_unicode():
    assert normalize("d30 Collection of Height & Weight Table (English)") == normalize(
        "d30_Collection_of_Height___Weight_Table__English_"
    )
    assert normalize("Gary Gygax\u2019s The Hermit") == normalize("Gary_Gygax's_The_Hermit")
    assert normalize("Caf\u00e9  \u201cNoir\u201d") == "cafe noir"
    assert normalize(None) == ""


def test_product_folder_parses_drivethru_layout():
    assert product_folder(r"D:\Drivethrurpg\Frog God Games\City of Brass\cob.pdf") == (
        "Frog God Games",
        "City of Brass",
    )
    assert product_folder(r"d:\DRIVETHRURPG\Pub\Title\x.pdf") == ("Pub", "Title")
    assert product_folder(r"E:\Other\book.pdf") is None
    assert product_folder(r"D:\Drivethrurpg\Pub\loose.pdf") is None


def test_choose_file_prefers_extracted_then_pages_then_size():
    dup = _product(r"D:\Drivethrurpg\P\T\dup.pdf", is_duplicate=True, page_count=999)
    dead = _product(r"D:\Drivethrurpg\P\T\dead.pdf", text_unextractable=True, page_count=999)
    missing = _product(r"D:\Drivethrurpg\P\T\gone.pdf", is_missing=True, page_count=999)
    raw = _product(r"D:\Drivethrurpg\P\T\raw.pdf", text_extracted=False, page_count=500)
    small = _product(r"D:\Drivethrurpg\P\T\small.pdf", page_count=20, file_size=10)
    big = _product(r"D:\Drivethrurpg\P\T\big.pdf", page_count=40, file_size=5)
    bigger_file = _product(r"D:\Drivethrurpg\P\T\big2.pdf", page_count=40, file_size=50)

    assert choose_file([dup, dead, missing, raw, small, big, bigger_file]) is bigger_file
    assert choose_file([dup, raw]) is raw
    assert choose_file([dup, dead, missing]) is None
    assert choose_file([]) is None


async def test_match_all_methods(db):
    folder = _product(r"D:\Drivethrurpg\Frog God Games\City of Brass\cob.pdf")
    title_only = _product(r"D:\Drivethrurpg\Necromancer Games\The Tomb of Abysthor\toa.pdf")
    fuzzy = _product(r"D:\Drivethrurpg\Frugal GM\Beach Encounters Pack\BeachEncounters.pdf")
    db.add_all([folder, title_only, fuzzy])
    db.add_all(
        [
            _codex(1, "City of Brass", "Frog God Games"),
            _codex(2, "The Tomb of Abysthor", "Frog God Games"),  # publisher differs
            _codex(3, "1008573-BeachEncounters", "Frugal GM"),
            _codex(4, "Nothing Like It Anywhere", "Nobody"),
        ]
    )
    await db.flush()

    report = await match_all(db)

    assert (report.folder, report.title, report.fuzzy, report.none) == (1, 1, 1, 1)
    rows = {cp.slug: cp for cp in (await db.execute(CodexProduct.__table__.select())).all()}
    assert rows["slug-1"].grimoire_product_id == folder.id
    assert rows["slug-2"].grimoire_product_id == title_only.id
    assert rows["slug-3"].grimoire_product_id == fuzzy.id and rows["slug-3"].match_score >= 90
    assert rows["slug-4"].grimoire_product_id is None and rows["slug-4"].match_method == "none"
    assert report.unmatched == [("slug-4", "Nothing Like It Anywhere", "Nobody")]


async def test_folder_match_picks_best_file_in_folder(db):
    worse = _product(r"D:\Drivethrurpg\Pub\Big Book\part.pdf", page_count=5)
    better = _product(r"D:\Drivethrurpg\Pub\Big Book\full.pdf", page_count=300)
    db.add_all([worse, better, _codex(1, "Big Book", "Pub")])
    await db.flush()
    await match_all(db)
    cp = await db.get(CodexProduct, "00000000-0000-0000-0000-000000000001")
    assert cp.grimoire_product_id == better.id and cp.match_method == "folder"


async def test_folder_of_only_duplicates_falls_back_to_the_original(db):
    original = _product(r"D:\Drivethrurpg\Pub\City Builder_ Revised Edition\rev.pdf")
    db.add(original)
    await db.flush()
    dup = _product(r"D:\Drivethrurpg\Pub\City Builder\cb.pdf", is_duplicate=True, duplicate_of_id=original.id)
    db.add_all([dup, _codex(1, "City Builder", "Pub")])
    await db.flush()
    report = await match_all(db)
    cp = await db.get(CodexProduct, "00000000-0000-0000-0000-000000000001")
    assert report.folder == 1 and cp.grimoire_product_id == original.id


async def test_fuzzy_has_no_false_positive_on_decoys(db):
    db.add(_product(r"D:\Drivethrurpg\Frog God Games\Tomb of Horrors\toh.pdf"))
    db.add(_codex(1, "Tomb of Rakoss", "Frog God Games"))
    await db.flush()
    report = await match_all(db)
    assert report.none == 1 and report.fuzzy == 0


def test_normalize_unescapes_html_entities():
    assert normalize("Candles, Clay &amp; Dancing Shoes") == normalize("Candles_ Clay & Dancing Shoes")


async def test_fuzzy_rejects_a_series_sibling_with_a_superset_title(db):
    # token_set_ratio scores this ~92: the folder's tokens are nearly a subset of the title.
    db.add(_product(r"D:\Drivethrurpg\Goodman Games\Dungeon Crawl Classics RPG\core.pdf"))
    db.add(_codex(1, "Dungeon Crawl Classics #51: Castle Whiterock", "Goodman Games"))
    await db.flush()
    report = await match_all(db)
    assert report.none == 1 and report.fuzzy == 0


async def test_fuzzy_rejects_a_different_issue_number(db):
    db.add(_product(r"D:\Drivethrurpg\Pub\Tales from the Smoking Wyrm 10\tsw10.pdf"))
    db.add(_codex(1, "Tales from the Smoking Wyrm 1", "Pub"))
    await db.flush()
    report = await match_all(db)
    assert report.none == 1 and report.fuzzy == 0


async def test_fuzzy_accepts_spacing_differences(db):
    p = _product(r"D:\Drivethrurpg\Pub\Unrelated Folder\TalesFromTheSmokingWyrm3.pdf")
    db.add_all([p, _codex(1, "Tales from the Smoking Wyrm #3", "Pub")])
    await db.flush()
    report = await match_all(db)
    assert report.fuzzy == 1
    assert (await db.get(CodexProduct, "00000000-0000-0000-0000-000000000001")).grimoire_product_id == p.id


async def test_rematch_keeps_manual_matches(db):
    p = _product(r"D:\Drivethrurpg\Pub\Odd Name\odd.pdf")
    cp = _codex(1, "Totally Different", "Pub")
    db.add_all([p, cp])
    await db.flush()
    cp.grimoire_product_id = p.id
    cp.match_method = "manual"
    await db.flush()
    report = await match_all(db)
    assert report.none == 0
    assert cp.match_method == "manual" and cp.grimoire_product_id == p.id
