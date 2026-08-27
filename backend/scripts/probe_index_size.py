"""Throwaway probe: project full body-index size from a subset.

Reads the live database only. The probe index is built in an ATTACHed file
which is deleted afterwards, so nothing copies the 16 GB library and nothing
is written into it.

Usage (from backend/):
    C:/Users/mkemi/miniconda3/python.exe scripts/probe_index_size.py
"""
import os
import sqlite3

PROBE = "probe-index.db"
SAMPLE = 200_000

if os.path.exists(PROBE):
    os.remove(PROBE)

conn = sqlite3.connect("data/grimoire.db")
conn.execute("ATTACH DATABASE ? AS probe", (PROBE,))
conn.execute(
    "CREATE VIRTUAL TABLE probe.probe_fts USING fts5("
    " chunk_text, product_id UNINDEXED, chunk_index UNINDEXED,"
    " page_start UNINDEXED, page_end UNINDEXED)"
)
conn.execute(
    "INSERT INTO probe.probe_fts("
    " rowid, chunk_text, product_id, chunk_index, page_start, page_end)"
    " SELECT id, chunk_text, product_id, chunk_index, page_start, page_end"
    " FROM product_embeddings LIMIT ?",
    (SAMPLE,),
)
conn.commit()

sampled = conn.execute("SELECT count(*) FROM probe.probe_fts").fetchone()[0]
total = conn.execute("SELECT count(*) FROM product_embeddings").fetchone()[0]
sampled_text = conn.execute(
    "SELECT sum(length(chunk_text)) FROM probe.probe_fts"
).fetchone()[0] or 0

conn.execute("DETACH DATABASE probe")
conn.close()

size = os.path.getsize(PROBE)
os.remove(PROBE)

print("sampled %d of %d chunks (%.1f%%)" % (sampled, total, 100 * sampled / total))
print("  sampled text : %.2f GB" % (sampled_text / 1e9))
print("  probe file   : %.2f GB  (text + index + sqlite overhead)" % (size / 1e9))
print("  overhead     : %.2fx the text it indexes" % (size / sampled_text))
print()
print("full index projects to %.2f GB" % (size / sampled * total / 1e9))
