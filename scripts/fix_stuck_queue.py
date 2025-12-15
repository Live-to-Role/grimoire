"""Fix stuck processing queue items."""
from sqlalchemy import create_engine, text

engine = create_engine("sqlite:////app/data/grimoire.db")
with engine.connect() as conn:
    result = conn.execute(
        text("UPDATE processing_queue SET status = 'failed', error_message = 'Stuck in processing - manually reset' WHERE status = 'processing'")
    )
    conn.commit()
    print(f"Reset {result.rowcount} stuck processing items to failed")
