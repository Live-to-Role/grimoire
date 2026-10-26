"""One product_type rule on the model, for every writer.

Text extraction, the bulk image route, identification and Codex sync all wrote
their own spelling of a type ("Core Rulebook", "Map", Codex's "core_rules").
The validator canonicalises anything the vocabulary knows, but keeps image
free text ("Token", "Stock Art") as written: the Codex image guard and the
image reset recognise those, and the enum values they map to they do not.
"""
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from grimoire.database import get_db
from grimoire.main import app
from grimoire.models.product import Product
from grimoire.services.queue_processor import image_product_type


def _product(**kw) -> Product:
    return Product(file_path="/t/x.pdf", file_name="x.pdf", file_size=1, file_hash="x", **kw)


@pytest.mark.parametrize("given, stored", [
    ("Adventure", "adventure"), ("Core Rulebook", "core_rulebook"), ("core_rules", "core_rulebook"),
    ("Magazine", "zine"), ("magazine", "zine"), ("Module", "adventure"), ("One-Shot", "adventure"),
    ("One Shot", "adventure"), ("Map", "map"), ("Art/Maps", "map"),
    ("Token", "Token"), ("Stock Art", "Stock Art"), ("Portrait", "Portrait"), ("Texture", "Texture"),   # image free text kept
    ("Anthology", "Anthology"), (None, None), ("", ""),
])
def test_validator_canonicalises_every_writer(given, stored):
    assert _product(product_type=given).product_type == stored


def test_validator_fires_on_later_assignment():
    product = _product()
    product.product_type = "core_rules"   # Codex sync copies Codex's value like this
    assert product.product_type == "core_rulebook"


async def test_loading_a_legacy_type_does_not_change_it(db):
    product = _product(product_type="adventure")
    db.add(product)
    await db.commit()
    pid = product.id
    # A Core update() bypasses the validator, as a pre-branch row did.
    await db.execute(update(Product).where(Product.id == pid).values(product_type="Supplement"))
    await db.commit()
    db.expire_all()

    loaded = (await db.execute(select(Product).where(Product.id == pid))).scalar_one()

    assert loaded.product_type == "Supplement"


@pytest.fixture
def client(db):
    async def override_get_db():
        yield db
    app.dependency_overrides[get_db] = override_get_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


async def test_image_detection_label_survives_reset_as_an_image_type(client, db):
    product = _product(is_image_content=True)
    product.product_type = image_product_type(product.product_type, "Token")
    db.add(product)
    await db.commit()

    response = await client.post("/api/v1/library/maintenance/reset-image-classification")

    assert response.status_code == 200
    await db.refresh(product)
    assert product.product_type is None
