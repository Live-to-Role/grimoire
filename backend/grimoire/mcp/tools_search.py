"""search_library, find_phrase, search_pack."""

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grimoire.mcp.common import ToolError, search_mode
from grimoire.models import Product

MAX_RESULTS = 50
MAX_PACK_QUERIES = 10
QUERY_MAX_LENGTH = 1000  # SemanticSearchRequest.query's bound
# Keyword search has no level predicate in SQL, so with a level filter the tool
# fetches deeper than `limit` and filters afterwards; without it, a filtered-out
# top hit would leave the answer short or empty while matches exist.
LEVEL_OVERFETCH = 10
MAX_KEYWORD_FETCH = 500

KEYWORD_NOTE = (
    "Semantic search is not configured in Grimoire, so this was a keyword-only "
    "search over metadata and body text. Exact names and terms work; topical "
    "queries will be weak. The user can enable semantic search by choosing a "
    "search provider in Grimoire's Settings."
)

_MARK_TAGS = re.compile(r"</?mark>")


def _clean(snippet: str | None) -> str | None:
    return _MARK_TAGS.sub("", snippet) if snippet else snippet


def _hit(item: dict, *, score: float | None, match_type: str | None) -> dict:
    return {
        "product_id": item["id"],
        "title": item.get("title") or item.get("file_name"),
        "game_system": item.get("game_system"),
        "product_type": item.get("product_type"),
        "publisher": item.get("publisher"),
        "level_min": item.get("level_range_min"),
        "level_max": item.get("level_range_max"),
        "score": score,
        "match_type": match_type,
        "matched_page": item.get("matched_page"),
        "snippet": _clean(item.get("snippet")),
    }


def _level_overlaps(hit: dict, level_min: int | None, level_max: int | None) -> bool:
    """Same lenient semantics as build_semantic_filter_conditions: unknown passes."""
    if level_min is not None and hit["level_max"] is not None and hit["level_max"] < level_min:
        return False
    if level_max is not None and hit["level_min"] is not None and hit["level_min"] > level_max:
        return False
    return True


def _clamp(value: int, upper: int) -> int:
    return max(1, min(int(value), upper))


async def search_library(
    db: AsyncSession,
    *,
    query: str,
    limit: int = 10,
    game_system: str | None = None,
    product_type: str | None = None,
    level_min: int | None = None,
    level_max: int | None = None,
    interpret: bool = True,
) -> dict:
    query = query.strip()[:QUERY_MAX_LENGTH]
    if not query:
        raise ToolError("query must not be empty")
    limit = _clamp(limit, MAX_RESULTS)
    mode, _ = await search_mode(db)

    if mode == "keyword_only":
        from grimoire.services.fts_service import search_fts

        level_filtered = level_min is not None or level_max is not None
        fetch = min(limit * LEVEL_OVERFETCH, MAX_KEYWORD_FETCH) if level_filtered else limit
        rows = await search_fts(
            db, query, game_system=game_system, product_type=product_type, limit=fetch
        )
        results = [
            _hit(row, score=row.get("relevance_score"), match_type="keyword") for row in rows
        ]
        results = [r for r in results if _level_overlaps(r, level_min, level_max)][:limit]
        return {
            "query": query,
            "mode": mode,
            "note": KEYWORD_NOTE,
            "interpretation": None,
            "results": results,
        }

    from grimoire.api.routes.semantic import SemanticSearchRequest
    from grimoire.services import search_service

    request = SemanticSearchRequest(
        query=query,
        top_k=limit,
        game_system=game_system,
        product_type=product_type,
        level_min=level_min,
        level_max=level_max,
        interpret=interpret,
    )
    out = await search_service.search(db, request)
    return {
        "query": query,
        "mode": "hybrid",
        "interpretation": out.get("interpretation"),
        "results": [
            _hit(item, score=item.get("score"), match_type=item.get("match_type"))
            for item in out["results"]
        ],
    }


async def find_phrase(
    db: AsyncSession,
    *,
    phrase: str,
    limit: int = 10,
    game_system: str | None = None,
    product_type: str | None = None,
) -> dict:
    phrase = phrase.strip()
    if not phrase:
        raise ToolError("phrase must not be empty")
    limit = _clamp(limit, MAX_RESULTS)

    from grimoire.services.fts_service import chunk_candidates

    hits = await chunk_candidates(
        db, phrase, game_system=game_system, product_type=product_type, limit=limit
    )
    titles: dict[int, str] = {}
    ids = [pid for pid, _, _, _ in hits]
    if ids:
        rows = await db.execute(
            select(Product.id, Product.title, Product.file_name).where(Product.id.in_(ids))
        )
        titles = {pid: title or file_name for pid, title, file_name in rows}

    return {
        "phrase": phrase,
        "results": [
            {
                "product_id": pid,
                "title": titles.get(pid),
                "page": page,
                "score": round(float(score), 4),
                "snippet": _clean(snippet),
            }
            for pid, score, snippet, page in hits
        ],
    }


async def search_pack(
    db: AsyncSession,
    *,
    queries: list[str],
    limit_per_query: int = 10,
    global_limit: int | None = None,
    game_system: str | None = None,
    product_type: str | None = None,
) -> dict:
    queries = [q.strip() for q in queries if q and q.strip()]
    if not queries:
        raise ToolError("queries must contain at least one non-empty query")
    if len(queries) > MAX_PACK_QUERIES:
        raise ToolError(f"at most {MAX_PACK_QUERIES} queries per pack")

    merged: dict[int, dict] = {}
    mode = None
    note = None
    for query in queries:
        # The caller already supplied the phrasings, so the per-query LLM
        # interpretation (one round trip each, sequential) is skipped here.
        out = await search_library(
            db,
            query=query,
            limit=limit_per_query,
            game_system=game_system,
            product_type=product_type,
            interpret=False,
        )
        mode = out["mode"]
        note = out.get("note")
        for hit in out["results"]:
            pid = hit["product_id"]
            entry = merged.get(pid)
            if entry is None:
                entry = dict(hit, matched_queries=[], best_query=query)
                merged[pid] = entry
            elif (hit.get("score") or 0) > (entry.get("score") or 0):
                matched = entry["matched_queries"]
                entry.update(hit, matched_queries=matched, best_query=query)
            entry["matched_queries"].append(query)

    results = sorted(merged.values(), key=lambda h: h.get("score") or 0, reverse=True)
    if global_limit:
        results = results[: max(1, int(global_limit))]
    return {"queries": queries, "mode": mode, "note": note, "results": results}
