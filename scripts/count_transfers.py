"""Print the number of `transfer` rows (completed and rejected). Used by the retry storm.

Usage: python -m scripts.count_transfers
"""

from sqlalchemy import text

from app.db import engine

with engine.connect() as conn:
    print(conn.execute(text("SELECT count(*) FROM transfers WHERE kind = 'transfer'")).scalar_one())
