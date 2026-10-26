"""list_monsters: pointers into owned books, never the stat block itself.

The bestiary spec's rule: names, page numbers, tags and computed figures are
facts; the prose they came from stays in the PDF. ``raw_text``, attacks and
special-ability text are deliberately not returned here.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from grimoire.mcp.common import json_list
from grimoire.models import MonsterEntry, Product
from grimoire.models.product import live_product_conditions

MAX_LIST = 100


def _pointer(entry: MonsterEntry, title: str | None, file_name: str) -> dict:
    return {
        "name": entry.name,
        "product_id": entry.product_id,
        "book_title": title or file_name,
        "page_number": entry.page_number,
        "system_profile": entry.system_profile,
        "hd_dice": entry.hd_dice,
        "hd_value": entry.hd_value,
        "ac": entry.ac,
        "hp_avg": entry.hp_avg,
        "environments": json_list(entry.environments),
    }


async def list_monsters(
    db: AsyncSession,
    *,
    environment: str | None = None,
    hd_min: float | None = None,
    hd_max: float | None = None,
    system_profile: str | None = None,
    product_id: int | None = None,
    name: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> dict:
    from grimoire.api.routes.monsters import _base_conditions

    limit = max(1, min(int(limit), MAX_LIST))
    offset = max(0, int(offset))
    conditions = _base_conditions(
        environment=environment,
        system_profile=system_profile,
        product_ids=[product_id] if product_id is not None else None,
        review_status="confirmed",
        hd_min=hd_min,
        hd_max=hd_max,
        q=name,
    )
    conditions.extend(live_product_conditions())
    total = (
        await db.execute(
            select(func.count(MonsterEntry.id))
            .join(Product, Product.id == MonsterEntry.product_id)
            .where(*conditions)
        )
    ).scalar()
    rows = await db.execute(
        select(MonsterEntry, Product.title, Product.file_name)
        .join(Product, Product.id == MonsterEntry.product_id)
        .where(*conditions)
        .order_by(MonsterEntry.name)
        .offset(offset)
        .limit(limit)
    )
    return {
        "total": total or 0,
        "limit": limit,
        "offset": offset,
        "results": [_pointer(entry, title, file_name) for entry, title, file_name in rows.all()],
    }
