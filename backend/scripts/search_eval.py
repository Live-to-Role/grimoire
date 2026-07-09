"""Golden-query eval for semantic search. Runs against the LIVE DB (read-only)
and requires Ollama up for query embedding.

Usage (from backend/):
    C:/Users/mkemi/miniconda3/python.exe scripts/search_eval.py
    C:/Users/mkemi/miniconda3/python.exe scripts/search_eval.py --save runs/base.json
    C:/Users/mkemi/miniconda3/python.exe scripts/search_eval.py --compare runs/base.json
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _is_hit(result: dict, expect) -> bool:
    if isinstance(expect, int):
        return result.get("id") == expect
    title = (result.get("title") or result.get("file_name") or "").lower()
    return str(expect).lower() in title


async def run(golden_path: str, save: str | None, compare: str | None) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from grimoire.config import settings
    from grimoire.api.routes.semantic import SemanticSearchRequest
    from grimoire.services import search_service

    golden = json.loads(Path(golden_path).read_text(encoding="utf-8"))
    queries = [q for q in golden["queries"] if "<fill in" not in json.dumps(q)]
    if not queries:
        print("No usable golden queries — fill in scripts/search_golden.json first.")
        return

    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine)

    rows = []
    async with session_factory() as db:
        for entry in queries:
            k = entry.get("k", 10)
            req = SemanticSearchRequest(query=entry["query"], top_k=k, hybrid=True, interpret=True)
            out = await search_service.search(db, req)
            results = out["results"]
            first_rank = None
            for rank, r in enumerate(results, start=1):
                if any(_is_hit(r, e) for e in entry["expect"]):
                    first_rank = rank
                    break
            rows.append({
                "query": entry["query"],
                "hit": first_rank is not None,
                "rank": first_rank,
                "rr": (1.0 / first_rank) if first_rank else 0.0,
                "top": [r.get("title") or r.get("file_name") for r in results[:3]],
            })
    await engine.dispose()

    hits = sum(1 for r in rows if r["hit"])
    mrr = sum(r["rr"] for r in rows) / len(rows)
    for r in rows:
        mark = f"HIT @{r['rank']}" if r["hit"] else "MISS"
        print(f"  [{mark:>7}] {r['query']!r}  top3={r['top']}")
    print(f"\nhit@k: {hits}/{len(rows)} ({hits / len(rows):.0%})   MRR: {mrr:.3f}")

    summary = {"hit_rate": hits / len(rows), "mrr": mrr, "rows": rows}
    if save:
        Path(save).parent.mkdir(parents=True, exist_ok=True)
        Path(save).write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"saved -> {save}")
    if compare:
        base = json.loads(Path(compare).read_text(encoding="utf-8"))
        print(f"\nvs {compare}: hit_rate {base['hit_rate']:.0%} -> {summary['hit_rate']:.0%}, "
              f"MRR {base['mrr']:.3f} -> {summary['mrr']:.3f}")
        for b, n in zip(base["rows"], rows):
            if b["hit"] != n["hit"]:
                print(f"  CHANGED: {n['query']!r}: {'MISS->HIT' if n['hit'] else 'HIT->MISS'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", default="scripts/search_golden.json")
    ap.add_argument("--save", default=None)
    ap.add_argument("--compare", default=None)
    args = ap.parse_args()
    asyncio.run(run(args.golden, args.save, args.compare))
