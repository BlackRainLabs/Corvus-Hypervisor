"""SQLite database schema and access."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import aiosqlite

from corvus.memory.embeddings import embed_text
from corvus.memory.vec_store import (
    delete_record_embedding,
    init_vec_schema,
    insert_record_embedding,
    load_vec_extension,
    query_semantic_record_ids,
)


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await load_vec_extension(self._conn)
        await self._init_schema()
        await init_vec_schema(self._conn)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected")
        return self._conn

    async def _init_schema(self) -> None:
        await self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS agents (
                id TEXT PRIMARY KEY,
                manifest_hash TEXT NOT NULL,
                manifest_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                vm_id TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rules (
                id TEXT PRIMARY KEY,
                priority INTEGER NOT NULL,
                rule_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                correlation_id TEXT,
                origin_correlation_id TEXT,
                agent_id TEXT,
                message_id TEXT,
                decision TEXT,
                matched_rules TEXT,
                details_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                role TEXT NOT NULL,
                profile_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS grants (
                id TEXT PRIMARY KEY,
                subject_agent TEXT NOT NULL,
                target_agent TEXT NOT NULL,
                namespace TEXT NOT NULL,
                permissions_json TEXT NOT NULL,
                expires_at TEXT,
                created_by TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS quota_counters (
                key TEXT PRIMARY KEY,
                limit_value INTEGER NOT NULL,
                used INTEGER NOT NULL,
                window_type TEXT NOT NULL,
                reset_at TEXT,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS namespace_quotas (
                agent_id TEXT NOT NULL,
                namespace TEXT NOT NULL,
                max_records INTEGER NOT NULL,
                max_record_bytes INTEGER NOT NULL,
                default_ttl_seconds INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (agent_id, namespace)
            );
            CREATE TABLE IF NOT EXISTS memory_records (
                id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                namespace TEXT NOT NULL,
                key TEXT,
                content TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                embedding_ref TEXT,
                expires_at TEXT,
                deleted_at TEXT,
                version INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_memory_records_key
                ON memory_records (agent_id, namespace, key, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_memory_records_list
                ON memory_records (agent_id, namespace, updated_at DESC);
            CREATE TABLE IF NOT EXISTS elevations (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                message_json TEXT NOT NULL,
                context_json TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS turn_state (
                root_correlation_id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                user_id TEXT,
                started_at TEXT NOT NULL,
                last_activity TEXT NOT NULL,
                depth INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_turn_state_agent ON turn_state(agent_id);
            CREATE INDEX IF NOT EXISTS idx_turn_state_last_activity ON turn_state(last_activity);
            CREATE TABLE IF NOT EXISTS pending_replay (
                id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                vm_id TEXT NOT NULL DEFAULT '',
                elevation_id TEXT NOT NULL,
                grant_id TEXT NOT NULL,
                message_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                delivered_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_pending_replay_agent
                ON pending_replay (agent_id, vm_id, delivered_at, created_at);
            CREATE TABLE IF NOT EXISTS behavioral_counters (
                agent_id TEXT NOT NULL,
                signal TEXT NOT NULL,
                window_start TEXT NOT NULL,
                count INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (agent_id, signal, window_start)
            );
            CREATE INDEX IF NOT EXISTS idx_behavioral_counters_agent_signal
                ON behavioral_counters (agent_id, signal, window_start);
            """
        )
        await self._migrate_audit_log()
        await self._migrate_pending_replay()
        await self.conn.commit()

    async def _migrate_pending_replay(self) -> None:
        cursor = await self.conn.execute("PRAGMA table_info(pending_replay)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "vm_id" not in columns:
            await self.conn.execute(
                "ALTER TABLE pending_replay ADD COLUMN vm_id TEXT NOT NULL DEFAULT ''"
            )
        await self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_pending_replay_agent
            ON pending_replay (agent_id, vm_id, delivered_at, created_at)
            """
        )

    async def _migrate_audit_log(self) -> None:
        cursor = await self.conn.execute("PRAGMA table_info(audit_log)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "origin_correlation_id" not in columns:
            await self.conn.execute(
                "ALTER TABLE audit_log ADD COLUMN origin_correlation_id TEXT"
            )
        await self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_audit_origin_correlation
            ON audit_log(origin_correlation_id)
            """
        )

    async def upsert_agent(
        self, agent_id: str, manifest_hash: str, manifest: dict[str, Any]
    ) -> None:
        now = datetime.now(UTC).isoformat()
        await self.conn.execute(
            """
            INSERT INTO agents (id, manifest_hash, manifest_json, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                manifest_hash=excluded.manifest_hash,
                manifest_json=excluded.manifest_json
            """,
            (agent_id, manifest_hash, json.dumps(manifest, sort_keys=True), now),
        )
        await self.conn.commit()

    async def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        cursor = await self.conn.execute(
            "SELECT id, manifest_hash, manifest_json, created_at FROM agents WHERE id = ?",
            (agent_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "manifest_hash": row["manifest_hash"],
            "manifest": json.loads(row["manifest_json"]),
            "created_at": row["created_at"],
        }

    async def list_agents(self) -> list[dict[str, Any]]:
        cursor = await self.conn.execute(
            "SELECT id, manifest_hash, manifest_json, created_at FROM agents ORDER BY id"
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": row["id"],
                "manifest_hash": row["manifest_hash"],
                "manifest": json.loads(row["manifest_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    async def create_session(self, agent_id: str, vm_id: str, expires_at: datetime) -> str:
        token = str(uuid4())
        now = datetime.now(UTC).isoformat()
        await self.conn.execute(
            """
            INSERT INTO sessions (token, agent_id, vm_id, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (token, agent_id, vm_id, expires_at.isoformat(), now),
        )
        await self.conn.commit()
        return token

    async def get_session(self, token: str) -> dict[str, Any] | None:
        cursor = await self.conn.execute(
            "SELECT token, agent_id, vm_id, expires_at, created_at FROM sessions WHERE token = ?",
            (token,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    async def upsert_rule(self, rule_id: str, priority: int, rule: dict[str, Any]) -> None:
        now = datetime.now(UTC).isoformat()
        await self.conn.execute(
            """
            INSERT INTO rules (id, priority, rule_json, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET priority=excluded.priority, rule_json=excluded.rule_json
            """,
            (rule_id, priority, json.dumps(rule, sort_keys=True), now),
        )
        await self.conn.commit()

    async def delete_rule(self, rule_id: str) -> bool:
        cursor = await self.conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
        await self.conn.commit()
        return cursor.rowcount > 0

    async def list_rules(self) -> list[dict[str, Any]]:
        cursor = await self.conn.execute(
            "SELECT id, priority, rule_json, created_at FROM rules ORDER BY priority DESC, id"
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": row["id"],
                "priority": row["priority"],
                **json.loads(row["rule_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    async def upsert_user(self, user_id: str, role: str, profile: dict[str, Any]) -> None:
        await self.conn.execute(
            """
            INSERT INTO users (id, role, profile_json) VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET role=excluded.role, profile_json=excluded.profile_json
            """,
            (user_id, role, json.dumps(profile, sort_keys=True)),
        )
        await self.conn.commit()

    async def get_user(self, user_id: str) -> dict[str, Any] | None:
        cursor = await self.conn.execute(
            "SELECT id, role, profile_json FROM users WHERE id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return {"id": row["id"], "role": row["role"], **json.loads(row["profile_json"])}

    async def find_user_by_alias(self, platform: str, value: str) -> dict[str, Any] | None:
        for user in await self.list_users():
            for alias in user.get("aliases", []):
                if alias.get("platform") == platform and alias.get("value") == value:
                    return user
        return None

    async def list_users(self) -> list[dict[str, Any]]:
        cursor = await self.conn.execute("SELECT id, role, profile_json FROM users ORDER BY id")
        rows = await cursor.fetchall()
        return [
            {"id": row["id"], "role": row["role"], **json.loads(row["profile_json"])}
            for row in rows
        ]

    async def verify_user_secret(self, user_id: str, secret: str) -> bool:
        user = await self.get_user(user_id)
        if user is None:
            return False
        expected = user.get("credential_hash")
        return expected == hash_secret(secret)

    async def create_grant(
        self,
        *,
        subject_agent: str,
        target_agent: str,
        namespace: str,
        permissions: list[str],
        created_by: str,
        expires_at: str | None = None,
        grant_id: str | None = None,
        status: str = "active",
    ) -> str:
        grant_id = grant_id or str(uuid4())
        now = datetime.now(UTC).isoformat()
        await self.conn.execute(
            """
            INSERT INTO grants (
                id, subject_agent, target_agent, namespace, permissions_json,
                expires_at, created_by, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                grant_id,
                subject_agent,
                target_agent,
                namespace,
                json.dumps(permissions),
                expires_at,
                created_by,
                status,
                now,
            ),
        )
        await self.conn.commit()
        return grant_id

    async def list_grants(
        self, *, agent_id: str | None = None, namespace: str | None = None
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM grants WHERE 1=1"
        params: list[Any] = []
        if agent_id:
            query += " AND (subject_agent = ? OR target_agent = ?)"
            params.extend([agent_id, agent_id])
        if namespace:
            query += " AND namespace = ?"
            params.append(namespace)
        query += " ORDER BY created_at DESC"
        cursor = await self.conn.execute(query, params)
        rows = await cursor.fetchall()
        return [self._grant_from_row(row) for row in rows]

    async def revoke_grant(self, grant_id: str) -> bool:
        cursor = await self.conn.execute(
            "UPDATE grants SET status = 'revoked' WHERE id = ?",
            (grant_id,),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def find_valid_grant(
        self,
        *,
        subject_agent: str,
        target_agent: str,
        namespace: str,
        permission: str,
        grant_id: str | None,
        now: datetime,
    ) -> dict[str, Any] | None:
        query = """
            SELECT * FROM grants
            WHERE subject_agent = ? AND target_agent = ? AND namespace = ? AND status = 'active'
        """
        params: list[Any] = [subject_agent, target_agent, namespace]
        if grant_id:
            query += " AND id = ?"
            params.append(grant_id)
        cursor = await self.conn.execute(query, params)
        rows = await cursor.fetchall()
        for row in rows:
            grant = self._grant_from_row(row)
            expires_at = grant.get("expires_at")
            if expires_at and datetime.fromisoformat(expires_at) <= now:
                continue
            if permission in grant["permissions"]:
                return grant
        return None

    async def get_or_create_quota_counter(
        self, *, key: str, limit: int, window_type: str
    ) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        # Idempotent create: concurrent streamed completions for the same user/agent
        # can race here, so rely on the primary key + ON CONFLICT rather than a
        # non-atomic SELECT-then-INSERT (which raised IntegrityError under concurrency).
        await self.conn.execute(
            """
            INSERT INTO quota_counters (
                key, limit_value, used, window_type, reset_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(key) DO NOTHING
            """,
            (key, limit, 0, window_type, None, now),
        )
        await self.conn.commit()
        cursor = await self.conn.execute("SELECT * FROM quota_counters WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return {
            "key": row["key"],
            "limit": row["limit_value"],
            "used": row["used"],
            "window_type": row["window_type"],
            "reset_at": row["reset_at"],
        }

    async def list_quota_counters(self) -> list[dict[str, Any]]:
        cursor = await self.conn.execute("SELECT * FROM quota_counters ORDER BY key")
        rows = await cursor.fetchall()
        return [
            {
                "key": row["key"],
                "limit": row["limit_value"],
                "used": row["used"],
                "window_type": row["window_type"],
                "reset_at": row["reset_at"],
            }
            for row in rows
        ]

    async def upsert_quota_counter(
        self, *, key: str, limit: int, used: int = 0, window_type: str = "daily"
    ) -> None:
        now = datetime.now(UTC).isoformat()
        await self.conn.execute(
            """
            INSERT INTO quota_counters (key, limit_value, used, window_type, reset_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                limit_value=excluded.limit_value,
                used=excluded.used,
                window_type=excluded.window_type,
                updated_at=excluded.updated_at
            """,
            (key, limit, used, window_type, None, now),
        )
        await self.conn.commit()

    async def get_quota_counter(self, key: str) -> dict[str, Any] | None:
        cursor = await self.conn.execute("SELECT * FROM quota_counters WHERE key = ?", (key,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "key": row["key"],
            "limit": row["limit_value"],
            "used": row["used"],
            "window_type": row["window_type"],
            "reset_at": row["reset_at"],
        }

    async def increment_quota_counter(self, key: str, *, delta: int = 1) -> dict[str, Any] | None:
        now = datetime.now(UTC).isoformat()
        cursor = await self.conn.execute(
            """
            UPDATE quota_counters
            SET used = used + ?, updated_at = ?
            WHERE key = ?
            """,
            (delta, now, key),
        )
        await self.conn.commit()
        if cursor.rowcount == 0:
            return None
        return await self.get_quota_counter(key)

    async def get_latest_behavioral_counter_activity(self) -> str | None:
        cursor = await self.conn.execute(
            "SELECT MAX(updated_at) AS latest FROM behavioral_counters"
        )
        row = await cursor.fetchone()
        if row is None or row["latest"] is None:
            return None
        return str(row["latest"])

    async def list_namespace_quotas(self, agent_id: str) -> list[dict[str, Any]]:
        cursor = await self.conn.execute(
            """
            SELECT agent_id, namespace, max_records, max_record_bytes,
                default_ttl_seconds, created_at, updated_at
            FROM namespace_quotas
            WHERE agent_id = ?
            ORDER BY namespace
            """,
            (agent_id,),
        )
        rows = await cursor.fetchall()
        return [self._namespace_quota_from_row(row) for row in rows]

    async def get_namespace_quota(
        self, *, agent_id: str, namespace: str
    ) -> dict[str, Any] | None:
        cursor = await self.conn.execute(
            """
            SELECT agent_id, namespace, max_records, max_record_bytes,
                default_ttl_seconds, created_at, updated_at
            FROM namespace_quotas
            WHERE agent_id = ? AND namespace = ?
            """,
            (agent_id, namespace),
        )
        row = await cursor.fetchone()
        return self._namespace_quota_from_row(row) if row else None

    async def upsert_namespace_quota(
        self,
        *,
        agent_id: str,
        namespace: str,
        max_records: int,
        max_record_bytes: int,
        default_ttl_seconds: int | None,
    ) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        await self.conn.execute(
            """
            INSERT INTO namespace_quotas (
                agent_id, namespace, max_records, max_record_bytes,
                default_ttl_seconds, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(agent_id, namespace) DO UPDATE SET
                max_records=excluded.max_records,
                max_record_bytes=excluded.max_record_bytes,
                default_ttl_seconds=excluded.default_ttl_seconds,
                updated_at=excluded.updated_at
            """,
            (
                agent_id,
                namespace,
                max_records,
                max_record_bytes,
                default_ttl_seconds,
                now,
                now,
            ),
        )
        await self.conn.commit()
        quota = await self.get_namespace_quota(agent_id=agent_id, namespace=namespace)
        if quota is None:
            raise RuntimeError("namespace quota upsert failed")
        return quota

    async def create_memory_record(
        self,
        *,
        agent_id: str,
        namespace: str,
        key: str | None,
        content: str,
        metadata: dict[str, Any],
        embedding_ref: str | None,
        expires_at: str | None,
    ) -> dict[str, Any]:
        record_id = str(uuid4())
        now = datetime.now(UTC).isoformat()
        await self.conn.execute(
            """
            INSERT INTO memory_records (
                id, agent_id, namespace, key, content, metadata_json, embedding_ref,
                expires_at, deleted_at, version, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_id,
                agent_id,
                namespace,
                key,
                content,
                json.dumps(metadata, sort_keys=True),
                embedding_ref,
                expires_at,
                None,
                1,
                now,
                now,
            ),
        )
        await self.conn.commit()
        embedding = embed_text(content)
        await insert_record_embedding(
            self.conn,
            record_id=record_id,
            embedding=embedding,
        )
        await self.conn.execute(
            "UPDATE memory_records SET embedding_ref = ? WHERE id = ?",
            (record_id, record_id),
        )
        await self.conn.commit()
        record = await self.get_memory_record(record_id)
        if record is None:
            raise RuntimeError("memory record insert failed")
        return record

    async def get_memory_record(self, record_id: str) -> dict[str, Any] | None:
        cursor = await self.conn.execute(
            "SELECT * FROM memory_records WHERE id = ?",
            (record_id,),
        )
        row = await cursor.fetchone()
        return self._memory_record_from_row(row) if row else None

    async def query_memory_by_key(
        self,
        *,
        agent_id: str,
        namespace: str,
        key: str,
        now: datetime,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        cursor = await self.conn.execute(
            """
            SELECT * FROM memory_records
            WHERE agent_id = ? AND namespace = ? AND key = ?
                AND deleted_at IS NULL
                AND (expires_at IS NULL OR expires_at > ?)
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (agent_id, namespace, key, now.isoformat(), limit),
        )
        rows = await cursor.fetchall()
        return [self._memory_record_from_row(row) for row in rows]

    async def list_memory_records(
        self,
        *,
        agent_id: str,
        namespace: str,
        now: datetime,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        cursor = await self.conn.execute(
            """
            SELECT * FROM memory_records
            WHERE agent_id = ? AND namespace = ?
                AND deleted_at IS NULL
                AND (expires_at IS NULL OR expires_at > ?)
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (agent_id, namespace, now.isoformat(), limit),
        )
        rows = await cursor.fetchall()
        return [self._memory_record_from_row(row) for row in rows]

    async def query_memory_semantic(
        self,
        *,
        agent_id: str,
        namespace: str,
        query_embedding: list[float],
        now: datetime,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        record_ids = await query_semantic_record_ids(
            self.conn,
            query_embedding=query_embedding,
            agent_id=agent_id,
            namespace=namespace,
            now=now,
            limit=limit,
        )
        records: list[dict[str, Any]] = []
        for record_id in record_ids:
            record = await self.get_memory_record(record_id)
            if record is not None:
                records.append(record)
        return records

    async def count_active_memory_records(
        self,
        *,
        agent_id: str,
        namespace: str,
        now: datetime,
    ) -> int:
        cursor = await self.conn.execute(
            """
            SELECT COUNT(*) AS count FROM memory_records
            WHERE agent_id = ? AND namespace = ?
                AND deleted_at IS NULL
                AND (expires_at IS NULL OR expires_at > ?)
            """,
            (agent_id, namespace, now.isoformat()),
        )
        row = await cursor.fetchone()
        return int(row["count"])

    async def soft_delete_memory_record(
        self,
        *,
        record_id: str,
        agent_id: str,
        namespace: str,
    ) -> dict[str, Any] | None:
        now = datetime.now(UTC).isoformat()
        cursor = await self.conn.execute(
            """
            UPDATE memory_records
            SET deleted_at = ?, updated_at = ?, version = version + 1
            WHERE id = ? AND agent_id = ? AND namespace = ? AND deleted_at IS NULL
            """,
            (now, now, record_id, agent_id, namespace),
        )
        await self.conn.commit()
        if cursor.rowcount == 0:
            return None
        await delete_record_embedding(self.conn, record_id=record_id)
        await self.conn.commit()
        return await self.get_memory_record(record_id)

    async def create_elevation(
        self,
        *,
        message: dict[str, Any],
        context: dict[str, Any],
        expires_at: str,
        status: str = "pending",
    ) -> str:
        elevation_id = str(uuid4())
        now = datetime.now(UTC).isoformat()
        await self.conn.execute(
            """
            INSERT INTO elevations (
                id, status, message_json, context_json, expires_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                elevation_id,
                status,
                json.dumps(message, sort_keys=True, default=str),
                json.dumps(context, sort_keys=True, default=str),
                expires_at,
                now,
                now,
            ),
        )
        await self.conn.commit()
        return elevation_id

    async def list_elevations(
        self,
        status: str | None = None,
        agent_id: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM elevations WHERE 1=1"
        params: list[Any] = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if agent_id:
            query += " AND json_extract(message_json, '$.source.agent_id') = ?"
            params.append(agent_id)
        query += " ORDER BY created_at DESC"
        cursor = await self.conn.execute(query, params)
        rows = await cursor.fetchall()
        return [self._elevation_from_row(row) for row in rows]

    async def update_elevation_status(self, elevation_id: str, status: str) -> bool:
        cursor = await self.conn.execute(
            "UPDATE elevations SET status = ?, updated_at = ? WHERE id = ?",
            (status, datetime.now(UTC).isoformat(), elevation_id),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def get_elevation(self, elevation_id: str) -> dict[str, Any] | None:
        cursor = await self.conn.execute(
            "SELECT * FROM elevations WHERE id = ?",
            (elevation_id,),
        )
        row = await cursor.fetchone()
        return self._elevation_from_row(row) if row else None

    async def expire_pending_elevations(self, now: datetime) -> int:
        cursor = await self.conn.execute(
            """
            UPDATE elevations
            SET status = 'expired', updated_at = ?
            WHERE status = 'pending' AND expires_at <= ?
            """,
            (now.isoformat(), now.isoformat()),
        )
        await self.conn.commit()
        return cursor.rowcount

    async def enqueue_pending_replay(
        self,
        *,
        agent_id: str,
        vm_id: str,
        elevation_id: str,
        grant_id: str,
        message: dict[str, Any],
    ) -> str:
        replay_id = str(uuid4())
        now = datetime.now(UTC).isoformat()
        await self.conn.execute(
            """
            INSERT INTO pending_replay (
                id, agent_id, vm_id, elevation_id, grant_id, message_json,
                created_at, delivered_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                replay_id,
                agent_id,
                vm_id,
                elevation_id,
                grant_id,
                json.dumps(message, sort_keys=True, default=str),
                now,
            ),
        )
        await self.conn.commit()
        return replay_id

    async def list_pending_replays(self, agent_id: str, vm_id: str) -> list[dict[str, Any]]:
        cursor = await self.conn.execute(
            """
            SELECT * FROM pending_replay
            WHERE agent_id = ? AND vm_id = ? AND delivered_at IS NULL
            ORDER BY created_at ASC
            """,
            (agent_id, vm_id),
        )
        rows = await cursor.fetchall()
        return [self._pending_replay_from_row(row) for row in rows]

    async def mark_pending_replay_delivered(self, replay_id: str, delivered_at: str) -> bool:
        cursor = await self.conn.execute(
            "UPDATE pending_replay SET delivered_at = ? WHERE id = ? AND delivered_at IS NULL",
            (delivered_at, replay_id),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def count_pending_replays(
        self, agent_id: str | None = None, vm_id: str | None = None
    ) -> int:
        if agent_id is None:
            cursor = await self.conn.execute(
                "SELECT COUNT(*) FROM pending_replay WHERE delivered_at IS NULL"
            )
        elif vm_id is None:
            cursor = await self.conn.execute(
                "SELECT COUNT(*) FROM pending_replay WHERE agent_id = ? AND delivered_at IS NULL",
                (agent_id,),
            )
        else:
            cursor = await self.conn.execute(
                """
                SELECT COUNT(*) FROM pending_replay
                WHERE agent_id = ? AND vm_id = ? AND delivered_at IS NULL
                """,
                (agent_id, vm_id),
            )
        row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def increment_behavioral_counter(
        self,
        *,
        agent_id: str,
        signal: str,
        window_start: str,
        delta: int = 1,
    ) -> int:
        now = datetime.now(UTC).isoformat()
        await self.conn.execute(
            """
            INSERT INTO behavioral_counters (agent_id, signal, window_start, count, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(agent_id, signal, window_start) DO UPDATE SET
                count = count + excluded.count,
                updated_at = excluded.updated_at
            """,
            (agent_id, signal, window_start, delta, now),
        )
        await self.conn.commit()
        cursor = await self.conn.execute(
            """
            SELECT count FROM behavioral_counters
            WHERE agent_id = ? AND signal = ? AND window_start = ?
            """,
            (agent_id, signal, window_start),
        )
        row = await cursor.fetchone()
        return int(row[0]) if row else delta

    async def sum_behavioral_counter(
        self,
        *,
        agent_id: str,
        signal: str,
        since_iso: str,
    ) -> int:
        cursor = await self.conn.execute(
            """
            SELECT COALESCE(SUM(count), 0) FROM behavioral_counters
            WHERE agent_id = ? AND signal = ? AND window_start >= ?
            """,
            (agent_id, signal, since_iso),
        )
        row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def list_behavioral_buckets(
        self,
        *,
        agent_id: str,
        signal: str,
        since_iso: str,
        before_iso: str | None = None,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT window_start, count FROM behavioral_counters
            WHERE agent_id = ? AND signal = ? AND window_start >= ?
        """
        params: list[Any] = [agent_id, signal, since_iso]
        if before_iso is not None:
            query += " AND window_start < ?"
            params.append(before_iso)
        query += " ORDER BY window_start ASC"
        cursor = await self.conn.execute(query, params)
        rows = await cursor.fetchall()
        return [{"window_start": row["window_start"], "count": row["count"]} for row in rows]

    async def purge_behavioral_counters(self, before_iso: str) -> int:
        cursor = await self.conn.execute(
            "DELETE FROM behavioral_counters WHERE window_start < ?",
            (before_iso,),
        )
        await self.conn.commit()
        return cursor.rowcount

    async def upsert_turn_state(
        self,
        *,
        root_correlation_id: str,
        agent_id: str,
        user_id: str | None,
        started_at: str,
        last_activity: str,
        depth: int = 0,
    ) -> None:
        await self.conn.execute(
            """
            INSERT INTO turn_state (
                root_correlation_id, agent_id, user_id, started_at, last_activity, depth
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(root_correlation_id) DO UPDATE SET
                agent_id=excluded.agent_id,
                user_id=excluded.user_id,
                started_at=excluded.started_at,
                last_activity=excluded.last_activity,
                depth=excluded.depth
            """,
            (root_correlation_id, agent_id, user_id, started_at, last_activity, depth),
        )
        await self.conn.commit()

    async def get_turn_state(self, root_correlation_id: str) -> dict[str, Any] | None:
        cursor = await self.conn.execute(
            "SELECT * FROM turn_state WHERE root_correlation_id = ?",
            (root_correlation_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "root_correlation_id": row["root_correlation_id"],
            "agent_id": row["agent_id"],
            "user_id": row["user_id"],
            "started_at": row["started_at"],
            "last_activity": row["last_activity"],
            "depth": int(row["depth"]),
        }

    async def update_turn_state_activity(
        self,
        *,
        root_correlation_id: str,
        last_activity: str,
        depth: int,
    ) -> None:
        await self.conn.execute(
            """
            UPDATE turn_state
            SET last_activity = ?, depth = ?
            WHERE root_correlation_id = ?
            """,
            (last_activity, depth, root_correlation_id),
        )
        await self.conn.commit()

    async def delete_turn_state(self, root_correlation_id: str) -> None:
        await self.conn.execute(
            "DELETE FROM turn_state WHERE root_correlation_id = ?",
            (root_correlation_id,),
        )
        await self.conn.commit()

    async def purge_expired_turn_states(self, *, cutoff_iso: str) -> int:
        cursor = await self.conn.execute(
            "DELETE FROM turn_state WHERE last_activity < ?",
            (cutoff_iso,),
        )
        await self.conn.commit()
        return cursor.rowcount

    @staticmethod
    def _grant_from_row(row: aiosqlite.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "subject_agent": row["subject_agent"],
            "target_agent": row["target_agent"],
            "namespace": row["namespace"],
            "permissions": json.loads(row["permissions_json"]),
            "expires_at": row["expires_at"],
            "created_by": row["created_by"],
            "status": row["status"],
            "created_at": row["created_at"],
        }

    @staticmethod
    def _elevation_from_row(row: aiosqlite.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "status": row["status"],
            "message": json.loads(row["message_json"]),
            "context": json.loads(row["context_json"]),
            "expires_at": row["expires_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _pending_replay_from_row(row: aiosqlite.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "agent_id": row["agent_id"],
            "vm_id": row["vm_id"],
            "elevation_id": row["elevation_id"],
            "grant_id": row["grant_id"],
            "message": json.loads(row["message_json"]),
            "created_at": row["created_at"],
            "delivered_at": row["delivered_at"],
        }

    @staticmethod
    def _namespace_quota_from_row(row: aiosqlite.Row) -> dict[str, Any]:
        return {
            "agent_id": row["agent_id"],
            "namespace": row["namespace"],
            "max_records": row["max_records"],
            "max_record_bytes": row["max_record_bytes"],
            "default_ttl_seconds": row["default_ttl_seconds"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _memory_record_from_row(row: aiosqlite.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "agent_id": row["agent_id"],
            "namespace": row["namespace"],
            "key": row["key"],
            "content": row["content"],
            "metadata": json.loads(row["metadata_json"]),
            "embedding_ref": row["embedding_ref"],
            "expires_at": row["expires_at"],
            "version": row["version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()
