"""Run inside Memobase after disabling event embeddings and switching to Google.

Preserves records/timestamps and backs up the original tables in the same database.
After re-enabling embeddings, run with --only-missing to catch arrivals during rollout.
Never logs memory text, vectors, or credentials.
"""
import asyncio
import json
import math
import sys

from openai import AsyncOpenAI
from sqlalchemy import text
from memobase_server.connectors import DB_ENGINE
from memobase_server.env import CONFIG
from memobase_server.models.response import EventData
from memobase_server.utils import event_embedding_str

MODEL = "gemini-embedding-2"


async def main():
    assert CONFIG.llm_base_url == "https://generativelanguage.googleapis.com/v1beta/openai/"
    assert CONFIG.embedding_model == MODEL
    only_missing = "--only-missing" in sys.argv
    assert only_missing or not CONFIG.enable_event_embedding
    client = AsyncOpenAI(base_url=CONFIG.llm_base_url, api_key=CONFIG.llm_api_key,
                         max_retries=0, timeout=60)
    counts = {}
    try:
        with DB_ENGINE.begin() as connection:
            connection.execute(text("SET LOCAL lock_timeout = '10s'"))
            # Block concurrent writes while reading and replacing the vectors.
            connection.execute(text("LOCK TABLE user_events, user_event_gists IN SHARE ROW EXCLUSIVE MODE"))
            for table, field in (("user_events", "event_data"), ("user_event_gists", "gist_data")):
                if not only_missing:
                    connection.execute(text(f"CREATE TABLE IF NOT EXISTS {table}_before_gemini_20260910 AS TABLE {table}"))
                condition = " WHERE embedding IS NULL" if only_missing else ""
                rows = connection.execute(text(f"SELECT id, project_id, {field} FROM {table}" + condition)).all()
                for start in range(0, len(rows), 16):
                    batch = rows[start:start + 16]
                    inputs = [event_embedding_str(EventData(**row[2])) if field == "event_data"
                              else row[2]["content"] for row in batch]
                    response = await client.embeddings.create(model=MODEL, input=inputs,
                                                              dimensions=1536, encoding_format="float")
                    vectors = response.data
                    assert len(vectors) == len(batch)
                    if any(item.index is None for item in vectors):
                        pass  # provider omits index on some items; order is positional
                    else:
                        vectors = sorted(vectors, key=lambda item: item.index)
                        assert [item.index for item in vectors] == list(range(len(batch)))
                    for row, item in zip(batch, vectors):
                        assert len(item.embedding) == 1536 and all(math.isfinite(x) for x in item.embedding)
                        connection.execute(text(f"UPDATE {table} SET embedding = CAST(:vector AS vector) "
                                                "WHERE id = :id AND project_id = :project"),
                                           {"vector": json.dumps(item.embedding), "id": row[0], "project": row[1]})
                counts[table] = len(rows)
            # All replacements commit together; failed requests roll everything back.
        print(json.dumps({"model": MODEL, "updated": counts, "only_missing": only_missing}))
    finally:
        await client.close()


asyncio.run(main())
