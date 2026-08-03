"""Server-owned Memory Service MVP."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic import ValidationError

from corvus.audit.store import AuditStore
from corvus.memory.embeddings import embed_text
from corvus.memory.encryption import decrypt_content, encrypt_content
from corvus.memory.models import (
    MemoryDelete,
    MemoryOperationResult,
    MemoryQuery,
    MemoryRecord,
    MemoryWrite,
)
from corvus.protocol import FrameworkMessage
from corvus.server.catalog import DEFAULT_CATALOG, CapabilityCatalog
from corvus.server.db import Database


class MemoryService:
    def __init__(
        self,
        db: Database,
        audit: AuditStore,
        *,
        encryption_enabled: bool = False,
        master_key: str | None = None,
        catalog: CapabilityCatalog | None = None,
    ) -> None:
        self.db = db
        self.audit = audit
        self.encryption_enabled = encryption_enabled
        self.master_key = master_key
        self._catalog = catalog

    @property
    def catalog(self) -> CapabilityCatalog:
        return self._catalog if self._catalog is not None else DEFAULT_CATALOG

    def bind_catalog(self, catalog: CapabilityCatalog) -> None:
        self._catalog = catalog

    async def handle(
        self,
        message: FrameworkMessage,
        *,
        grant_id: str | None,
    ) -> MemoryOperationResult:
        try:
            if message.type == "memory:write":
                return await self.write(message, grant_id=grant_id)
            if message.type == "memory:query":
                return await self.query(message, grant_id=grant_id)
            if message.type == "memory:delete":
                return await self.delete(message, grant_id=grant_id)
            return await self._failure(
                message,
                target_agent_id=str(
                    message.payload.get("target_agent_id", message.source.agent_id)
                ),
                namespace=str(message.payload.get("namespace", "private")),
                operation="unsupported",
                code="MEMORY_UNSUPPORTED_OPERATION",
                reason=f"Unsupported memory message type: {message.type}",
                grant_id=grant_id,
            )
        except ValidationError as exc:
            return await self._failure(
                message,
                target_agent_id=str(
                    message.payload.get("target_agent_id", message.source.agent_id)
                ),
                namespace=str(message.payload.get("namespace", "private")),
                operation=self._operation_for_type(message.type),
                code="MEMORY_PAYLOAD_INVALID",
                reason=str(exc),
                grant_id=grant_id,
            )

    async def write(
        self,
        message: FrameworkMessage,
        *,
        grant_id: str | None,
    ) -> MemoryOperationResult:
        payload = self._write_payload(message)
        if failure := await self._validate_target_namespace(
            message,
            target_agent_id=payload.target_agent_id,
            namespace=payload.namespace,
            operation="write",
            grant_id=grant_id,
        ):
            return failure

        quota = await self._namespace_quota(payload.target_agent_id, payload.namespace)
        content_bytes = len(payload.content.encode("utf-8"))
        if content_bytes > int(quota["max_record_bytes"]):
            return await self._failure(
                message,
                target_agent_id=payload.target_agent_id,
                namespace=payload.namespace,
                operation="write",
                code="SERVER_QUOTA_EXCEEDED",
                reason="record exceeds namespace max_record_bytes",
                grant_id=grant_id,
            )

        active_count = await self.db.count_active_memory_records(
            agent_id=payload.target_agent_id,
            namespace=payload.namespace,
            now=datetime.now(UTC),
        )
        if active_count >= int(quota["max_records"]):
            return await self._failure(
                message,
                target_agent_id=payload.target_agent_id,
                namespace=payload.namespace,
                operation="write",
                code="SERVER_QUOTA_EXCEEDED",
                reason="namespace max_records exceeded",
                grant_id=grant_id,
            )

        ttl_seconds = payload.ttl_seconds or quota.get("default_ttl_seconds")
        expires_at = (
            (datetime.now(UTC) + timedelta(seconds=int(ttl_seconds))).isoformat()
            if ttl_seconds
            else None
        )
        metadata = {
            **payload.metadata,
            "source_turn_id": str(message.tags.origin_correlation_id or message.correlation_id),
        }
        content = payload.content
        if self.encryption_enabled:
            if not self.master_key:
                return await self._failure(
                    message,
                    target_agent_id=payload.target_agent_id,
                    namespace=payload.namespace,
                    operation="write",
                    code="MEMORY_ENCRYPTION_UNAVAILABLE",
                    reason="memory encryption enabled but CORVUS_MASTER_KEY is not configured",
                    grant_id=grant_id,
                )
            content = encrypt_content(
                master_key=self.master_key,
                agent_id=payload.target_agent_id,
                plaintext=payload.content,
            )
            metadata["encrypted"] = True
        record = await self.db.create_memory_record(
            agent_id=payload.target_agent_id,
            namespace=payload.namespace,
            key=payload.key,
            content=content,
            metadata=metadata,
            embedding_ref=None,
            expires_at=expires_at,
        )
        await self._log(
            message,
            operation="write",
            target_agent_id=payload.target_agent_id,
            namespace=payload.namespace,
            record_id=record["id"],
            grant_id=grant_id,
            result="allow",
            reason="record_written",
        )
        return MemoryOperationResult(
            success=True,
            record_id=record["id"],
            grant_evaluated=grant_id,
        )

    async def query(
        self,
        message: FrameworkMessage,
        *,
        grant_id: str | None,
    ) -> MemoryOperationResult:
        payload = self._query_payload(message)
        if failure := await self._validate_target_namespace(
            message,
            target_agent_id=payload.target_agent_id,
            namespace=payload.namespace,
            operation="query",
            grant_id=grant_id,
        ):
            return failure

        now = datetime.now(UTC)
        if payload.query_type == "semantic":
            if not payload.text:
                return await self._failure(
                    message,
                    target_agent_id=payload.target_agent_id,
                    namespace=payload.namespace,
                    operation="query",
                    code="MEMORY_QUERY_INVALID",
                    reason="semantic query requires query.text",
                    grant_id=grant_id,
                )
            rows = await self.db.query_memory_semantic(
                agent_id=payload.target_agent_id,
                namespace=payload.namespace,
                query_embedding=embed_text(payload.text),
                now=now,
                limit=payload.limit,
            )
        elif payload.query_type == "key":
            if not payload.key:
                return await self._failure(
                    message,
                    target_agent_id=payload.target_agent_id,
                    namespace=payload.namespace,
                    operation="query",
                    code="MEMORY_QUERY_INVALID",
                    reason="key query requires query.key",
                    grant_id=grant_id,
                )
            rows = await self.db.query_memory_by_key(
                agent_id=payload.target_agent_id,
                namespace=payload.namespace,
                key=payload.key,
                now=now,
                limit=payload.limit,
            )
        else:
            rows = await self.db.list_memory_records(
                agent_id=payload.target_agent_id,
                namespace=payload.namespace,
                now=now,
                limit=payload.limit,
            )
        records = [MemoryRecord.model_validate(self._decrypt_row(row)) for row in rows]
        await self._log(
            message,
            operation="query",
            target_agent_id=payload.target_agent_id,
            namespace=payload.namespace,
            record_id=None,
            grant_id=grant_id,
            result="allow",
            reason=f"{payload.query_type}_query",
        )
        return MemoryOperationResult(
            success=True,
            records=records,
            grant_evaluated=grant_id,
        )

    async def delete(
        self,
        message: FrameworkMessage,
        *,
        grant_id: str | None,
    ) -> MemoryOperationResult:
        payload = self._delete_payload(message)
        if failure := await self._validate_target_namespace(
            message,
            target_agent_id=payload.target_agent_id,
            namespace=payload.namespace,
            operation="delete",
            grant_id=grant_id,
        ):
            return failure

        deleted = await self.db.soft_delete_memory_record(
            record_id=payload.record_id,
            agent_id=payload.target_agent_id,
            namespace=payload.namespace,
        )
        if deleted is None:
            return await self._failure(
                message,
                target_agent_id=payload.target_agent_id,
                namespace=payload.namespace,
                operation="delete",
                code="MEMORY_RECORD_NOT_FOUND",
                reason="record not found",
                grant_id=grant_id,
                record_id=payload.record_id,
            )
        await self._log(
            message,
            operation="delete",
            target_agent_id=payload.target_agent_id,
            namespace=payload.namespace,
            record_id=payload.record_id,
            grant_id=grant_id,
            result="allow",
            reason="record_deleted",
        )
        return MemoryOperationResult(
            success=True,
            record_id=payload.record_id,
            deleted=True,
            grant_evaluated=grant_id,
        )

    def _write_payload(self, message: FrameworkMessage) -> MemoryWrite:
        record = message.payload.get("record", {})
        return MemoryWrite.model_validate(
            {
                "target_agent_id": self._target_agent_id(message),
                "namespace": message.payload.get("namespace", "private"),
                "key": record.get("key"),
                "content": record.get("content"),
                "metadata": record.get("metadata", {}),
                "ttl_seconds": record.get("ttl_seconds"),
            }
        )

    def _query_payload(self, message: FrameworkMessage) -> MemoryQuery:
        query = message.payload.get("query", {})
        return MemoryQuery.model_validate(
            {
                "target_agent_id": self._target_agent_id(message),
                "namespace": message.payload.get("namespace", "private"),
                "query_type": message.payload.get("query_type", "key"),
                "key": query.get("key"),
                "text": query.get("text"),
                "limit": query.get("limit", 10),
            }
        )

    def _delete_payload(self, message: FrameworkMessage) -> MemoryDelete:
        return MemoryDelete.model_validate(
            {
                "target_agent_id": self._target_agent_id(message),
                "namespace": message.payload.get("namespace", "private"),
                "record_id": message.payload.get("record_id"),
            }
        )

    def _target_agent_id(self, message: FrameworkMessage) -> str:
        return str(
            message.payload.get("target_agent_id")
            or message.payload.get("target_agent")
            or message.source.agent_id
        )

    async def _validate_target_namespace(
        self,
        message: FrameworkMessage,
        *,
        target_agent_id: str,
        namespace: str,
        operation: str,
        grant_id: str | None,
    ) -> MemoryOperationResult | None:
        agent = await self.db.get_agent(target_agent_id)
        if agent is None:
            return await self._failure(
                message,
                target_agent_id=target_agent_id,
                namespace=namespace,
                operation=operation,
                code="MEMORY_TARGET_AGENT_NOT_FOUND",
                reason="target agent not found",
                grant_id=grant_id,
            )
        if namespace not in self.catalog.memory_namespaces:
            return await self._failure(
                message,
                target_agent_id=target_agent_id,
                namespace=namespace,
                operation=operation,
                code="MEMORY_NAMESPACE_INVALID",
                reason="namespace is not in the server-owned memory namespace catalog",
                grant_id=grant_id,
            )
        engine4 = agent["manifest"].get("engines", {}).get("engine4", {})
        assigned = set(engine4.get("namespaces", []))
        if namespace not in assigned:
            return await self._failure(
                message,
                target_agent_id=target_agent_id,
                namespace=namespace,
                operation=operation,
                code="MEMORY_NAMESPACE_NOT_ASSIGNED",
                reason="namespace is not assigned to target agent manifest",
                grant_id=grant_id,
            )
        if target_agent_id != message.source.agent_id and not grant_id:
            return await self._failure(
                message,
                target_agent_id=target_agent_id,
                namespace=namespace,
                operation=operation,
                code="SERVER_GRANT_DENIED",
                reason="cross-agent memory operation requires a valid grant",
                grant_id=grant_id,
            )
        return None

    def _decrypt_row(self, row: dict) -> dict:
        metadata = row.get("metadata") or {}
        if not metadata.get("encrypted"):
            return row
        if not self.master_key:
            raise ValueError("encrypted memory record requires CORVUS_MASTER_KEY")
        decrypted = dict(row)
        decrypted["content"] = decrypt_content(
            master_key=self.master_key,
            agent_id=str(row["agent_id"]),
            encoded=str(row["content"]),
        )
        return decrypted

    async def _namespace_quota(self, agent_id: str, namespace: str) -> dict[str, int | None]:
        override = await self.db.get_namespace_quota(agent_id=agent_id, namespace=namespace)
        if override:
            return {
                "max_records": override["max_records"],
                "max_record_bytes": override["max_record_bytes"],
                "default_ttl_seconds": override["default_ttl_seconds"],
            }
        template = self.catalog.memory_namespaces[namespace]
        return template.quota.model_dump(mode="json")

    async def _failure(
        self,
        message: FrameworkMessage,
        *,
        target_agent_id: str,
        namespace: str,
        operation: str,
        code: str,
        reason: str,
        grant_id: str | None,
        record_id: str | None = None,
    ) -> MemoryOperationResult:
        await self._log(
            message,
            operation=operation,
            target_agent_id=target_agent_id,
            namespace=namespace,
            record_id=record_id,
            grant_id=grant_id,
            result="deny",
            reason=reason,
        )
        return MemoryOperationResult(
            success=False,
            error=reason,
            error_code=code,
            grant_evaluated=grant_id,
        )

    async def _log(
        self,
        message: FrameworkMessage,
        *,
        operation: str,
        target_agent_id: str,
        namespace: str,
        record_id: str | None,
        grant_id: str | None,
        result: str,
        reason: str,
    ) -> None:
        await self.audit.log_memory_operation(
            message,
            operation=operation,
            target_agent_id=target_agent_id,
            namespace=namespace,
            record_id=record_id,
            grant_id=grant_id,
            result=result,
            reason=reason,
        )

    @staticmethod
    def _operation_for_type(message_type: str) -> str:
        if message_type.startswith("memory:"):
            return message_type.split(":", 1)[1]
        return "unknown"
