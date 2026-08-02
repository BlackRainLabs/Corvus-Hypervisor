"""sqlite-vec storage helpers for memory record embeddings."""

from __future__ import annotations

from datetime import datetime

import aiosqlite
import sqlite_vec

from corvus.memory.embeddings import EMBEDDING_DIM

VEC_TABLE = "memory_embeddings"


async def load_vec_extension(conn: aiosqlite.Connection) -> None:
    await conn.enable_load_extension(True)
    await conn.load_extension(sqlite_vec.loadable_path())
    await conn.enable_load_extension(False)


async def init_vec_schema(conn: aiosqlite.Connection) -> None:
    await conn.execute(
        f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS {VEC_TABLE} USING vec0(
            record_id TEXT PRIMARY KEY,
            embedding float[{EMBEDDING_DIM}] distance_metric=cosine
        )
        """
    )


async def insert_record_embedding(
    conn: aiosqlite.Connection,
    *,
    record_id: str,
    embedding: list[float],
) -> None:
    blob = sqlite_vec.serialize_float32(embedding)
    await conn.execute(
        f"INSERT INTO {VEC_TABLE}(record_id, embedding) VALUES (?, ?)",
        (record_id, blob),
    )


async def delete_record_embedding(conn: aiosqlite.Connection, *, record_id: str) -> None:
    await conn.execute(f"DELETE FROM {VEC_TABLE} WHERE record_id = ?", (record_id,))


async def query_semantic_record_ids(
    conn: aiosqlite.Connection,
    *,
    query_embedding: list[float],
    agent_id: str,
    namespace: str,
    now: datetime,
    limit: int,
) -> list[str]:
    k = min(max(limit * 10, limit), 100)
    query_blob = sqlite_vec.serialize_float32(query_embedding)
    cursor = await conn.execute(
        f"""
        WITH knn AS (
            SELECT record_id, distance
            FROM {VEC_TABLE}
            WHERE embedding MATCH ?
              AND k = ?
        )
        SELECT knn.record_id
        FROM knn
        INNER JOIN memory_records mr ON mr.id = knn.record_id
        WHERE mr.agent_id = ?
          AND mr.namespace = ?
          AND mr.deleted_at IS NULL
          AND (mr.expires_at IS NULL OR mr.expires_at > ?)
        ORDER BY knn.distance ASC
        LIMIT ?
        """,
        (query_blob, k, agent_id, namespace, now.isoformat(), limit),
    )
    rows = await cursor.fetchall()
    return [str(row[0]) for row in rows]
