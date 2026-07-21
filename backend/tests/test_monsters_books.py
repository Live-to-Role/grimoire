"""Tests for multi-book filtering and the books listing."""

import json

from grimoire.api.routes.monsters import RandomRequest, list_books, list_monsters, random_monsters
from grimoire.models import MonsterEntry, Product


async def seed_book(db, path, title, names, status="confirmed"):
    product = Product(
        file_path=path, file_name=path.rsplit("/", 1)[-1],
        file_size=1, file_hash=path, title=title,
    )
    db.add(product)
    await db.flush()
    for name in names:
        db.add(MonsterEntry(
            product_id=product.id, name=name, page_number=1, system_profile="dcc",
            raw_text="raw", ac=12, hd_dice="1d8", hd_value=1.0, hp_avg=4.5,
            attacks=json.dumps([]), environments=json.dumps(["books-test-env"]),
            special_abilities=json.dumps([]), flags=json.dumps([]),
            review_status=status,
        ))
    await db.flush()
    return product


async def test_product_ids_filters_to_selected_books(db):
    book_a = await seed_book(db, "/t/books-a.pdf", "Book A", ["Aardvark A", "Badger A"])
    await seed_book(db, "/t/books-b.pdf", "Book B", ["Cougar B"])

    result = await list_monsters(db=db, product_ids=[book_a.id], environment="books-test-env")
    names = sorted(i["name"] for i in result["items"])
    assert names == ["Aardvark A", "Badger A"]


async def test_product_ids_accepts_multiple_books(db):
    book_a = await seed_book(db, "/t/books-multi-a.pdf", "Multi A", ["Multi Ant"])
    book_b = await seed_book(db, "/t/books-multi-b.pdf", "Multi B", ["Multi Bee"])

    result = await list_monsters(
        db=db, product_ids=[book_a.id, book_b.id], environment="books-test-env"
    )
    assert sorted(i["name"] for i in result["items"]) == ["Multi Ant", "Multi Bee"]


async def test_empty_product_ids_means_all_books(db):
    await seed_book(db, "/t/books-all-a.pdf", "All A", ["All Aurochs"])
    await seed_book(db, "/t/books-all-b.pdf", "All B", ["All Bison"])

    result = await list_monsters(db=db, environment="books-test-env")
    names = [i["name"] for i in result["items"]]
    assert "All Aurochs" in names
    assert "All Bison" in names


async def test_random_respects_product_ids(db):
    book_a = await seed_book(db, "/t/books-rand-a.pdf", "Rand A", ["Rand Auk"])
    await seed_book(db, "/t/books-rand-b.pdf", "Rand B", ["Rand Boar"])

    result = await random_monsters(
        db=db, request=RandomRequest(count=10, product_ids=[book_a.id], environment="books-test-env")
    )
    names = [i["name"] for i in result["items"]]
    assert "Rand Auk" in names
    assert "Rand Boar" not in names


async def test_list_books_counts_confirmed_by_default(db):
    book = await seed_book(db, "/t/books-count.pdf", "Counted Book", ["Count One", "Count Two"])
    await seed_book(db, "/t/books-count-pending.pdf", "Pending Book", ["Hidden One"], status="pending")

    result = await list_books(db=db)
    by_id = {b["product_id"]: b for b in result["books"]}
    assert by_id[book.id]["title"] == "Counted Book"
    assert by_id[book.id]["count"] == 2
    # A book with only pending entries must not appear in the confirmed listing.
    assert all(b["title"] != "Pending Book" for b in result["books"])


async def test_list_books_honors_review_status(db):
    """Review mode needs books whose entries are all still pending."""
    await seed_book(db, "/t/books-review.pdf", "Review Book", ["Review One"], status="pending")

    result = await list_books(db=db, review_status="pending")
    assert any(b["title"] == "Review Book" and b["count"] == 1 for b in result["books"])
