"""Golden-query eval for semantic search. Runs against the LIVE DB (read-only)
and requires Ollama up for query embedding.

Interpretations are PINNED. The LLM interpreter rewrites semantic_query
differently between calls even at temperature 0 - "cave adventure" came back
as "cave adventure underground cavern" on some runs and unchanged on others -
which changes the query embedding and moves results enough to swamp any
tuning effect (one pair of identical runs disagreed by 40 points of
precision@10). Pinned interpretations are replayed from a sidecar file so a
tuning run measures the constant that changed and nothing else.

Usage (from backend/):
    C:/Users/mkemi/miniconda3/python.exe scripts/search_eval.py
    C:/Users/mkemi/miniconda3/python.exe scripts/search_eval.py --save runs/base.json
    C:/Users/mkemi/miniconda3/python.exe scripts/search_eval.py --compare runs/base.json
    C:/Users/mkemi/miniconda3/python.exe scripts/search_eval.py --repin   # re-record
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _title(result: dict) -> str:
    return result.get("title") or result.get("file_name") or ""


def _is_hit(result: dict, expect) -> bool:
    if isinstance(expect, int):
        return result.get("id") == expect
    return str(expect).lower() in _title(result).lower()


def score_specific(entry: dict, results: list[dict]) -> dict:
    """One book is the right answer: reciprocal rank of the first match."""
    first_rank = None
    for rank, r in enumerate(results, start=1):
        if any(_is_hit(r, e) for e in entry["expect"]):
            first_rank = rank
            break
    return {
        "mode": "specific",
        "query": entry["query"],
        "hit": first_rank is not None,
        "rank": first_rank,
        "rr": (1.0 / first_rank) if first_rank else 0.0,
        "top": [_title(r) for r in results[:3]],
    }


def score_topical(entry: dict, results: list[dict]) -> dict:
    """Hundreds of books legitimately answer this, so measure how much of the
    top k is on topic rather than whether one chosen title showed up."""
    pattern = re.compile(entry["topic"], re.I)
    on_topic = [bool(pattern.search(_title(r))) for r in results]
    matched = sum(on_topic)
    return {
        "mode": "topical",
        "query": entry["query"],
        "precision": matched / len(results) if results else 0.0,
        "matched": matched,
        "returned": len(results),
        "off_topic": [_title(r) for r, ok in zip(results, on_topic) if not ok][:3],
    }


async def pin_interpretations(db, queries: list[dict], path: str, repin: bool) -> None:
    """Record one interpretation per query, then replay it on every later run.

    Seeds the interpreter's own per-query cache, which short-circuits ahead of
    the LLM call, so no network round trip happens during scoring.
    """
    from grimoire.services import query_interpreter as qi

    p = Path(path)
    if repin or not p.exists():
        qi._llm_cache.clear()
        recorded = {}
        for entry in queries:
            interp = await qi.interpret_query(db, entry["query"])
            recorded[entry["query"]] = interp.to_dict()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(recorded, indent=2), encoding="utf-8")
        print(f"pinned {len(recorded)} interpretations -> {path}\n")

    data = json.loads(p.read_text(encoding="utf-8"))
    missing = [e["query"] for e in queries if e["query"] not in data]
    if missing:
        raise SystemExit(
            f"No pinned interpretation for {missing!r}. Re-run with --repin."
        )
    for query, d in data.items():
        qi._llm_cache[query] = qi.Interpretation(**d)


async def run(golden_path: str, save: str | None, compare: str | None,
              pin_path: str, repin: bool) -> None:
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
        await pin_interpretations(db, queries, pin_path, repin)
        for entry in queries:
            k = entry.get("k", 10)
            req = SemanticSearchRequest(query=entry["query"], top_k=k, hybrid=True, interpret=True)
            out = await search_service.search(db, req)
            results = out["results"]
            if entry.get("mode") == "topical":
                rows.append(score_topical(entry, results))
            else:
                rows.append(score_specific(entry, results))
    await engine.dispose()

    specific = [r for r in rows if r["mode"] == "specific"]
    topical = [r for r in rows if r["mode"] == "topical"]

    summary = {"rows": rows}

    if specific:
        hits = sum(1 for r in specific if r["hit"])
        mrr = sum(r["rr"] for r in specific) / len(specific)
        summary["hit_rate"] = hits / len(specific)
        summary["mrr"] = mrr
        print("SPECIFIC (one right answer; hit@k + MRR)")
        for r in specific:
            mark = f"HIT @{r['rank']}" if r["hit"] else "MISS"
            print(f"  [{mark:>7}] {r['query']!r}  top3={r['top']}")
        print(f"\n  hit@k: {hits}/{len(specific)} ({hits / len(specific):.0%})   MRR: {mrr:.3f}")

    if topical:
        mean_p = sum(r["precision"] for r in topical) / len(topical)
        summary["mean_precision"] = mean_p
        print("\nTOPICAL (many right answers; precision@k)")
        for r in topical:
            print(f"  [{r['matched']:>2}/{r['returned']:<2} = {r['precision']:.0%}] {r['query']!r}"
                  f"  off-topic={r['off_topic']}")
        print(f"\n  mean precision@k: {mean_p:.0%}")
    if save:
        Path(save).parent.mkdir(parents=True, exist_ok=True)
        Path(save).write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"saved -> {save}")
    if compare:
        base = json.loads(Path(compare).read_text(encoding="utf-8"))
        print(f"\nvs {compare}:")
        for label, key, fmt in (("hit_rate", "hit_rate", "{:.0%}"),
                                ("MRR", "mrr", "{:.3f}"),
                                ("mean precision", "mean_precision", "{:.0%}")):
            if key in base and key in summary:
                print(f"  {label}: {fmt.format(base[key])} -> {fmt.format(summary[key])}")

        # Match on query text: a reordered or resized golden file must not
        # silently pair unrelated rows the way zip() would.
        base_by_query = {r["query"]: r for r in base["rows"]}
        for n in rows:
            b = base_by_query.get(n["query"])
            if not b or b.get("mode") != n["mode"]:
                continue
            if n["mode"] == "specific" and b["hit"] != n["hit"]:
                print(f"  CHANGED: {n['query']!r}: {'MISS->HIT' if n['hit'] else 'HIT->MISS'}")
            elif n["mode"] == "topical" and abs(b["precision"] - n["precision"]) >= 0.1:
                print(f"  CHANGED: {n['query']!r}: {b['precision']:.0%} -> {n['precision']:.0%}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", default="scripts/search_golden.json")
    ap.add_argument("--save", default=None)
    ap.add_argument("--compare", default=None)
    ap.add_argument("--pin", default="scripts/search_interpretations.json",
                    help="Pinned interpretations replayed for reproducibility")
    ap.add_argument("--repin", action="store_true",
                    help="Re-record interpretations from the LLM before running")
    args = ap.parse_args()
    asyncio.run(run(args.golden, args.save, args.compare, args.pin, args.repin))
