"""Application bootstrap and shared runtime context."""

from __future__ import annotations

from corvus.audit.store import AuditStore
from corvus.llm import LlmGatewayService
from corvus.llm.registry import LlmProviderRegistry
from corvus.memory import MemoryService
from corvus.memory.elevation_replay import ElevationReplayService
from corvus.memory.sweeper import MemoryRetentionSweeper
from corvus.policy.behavioral import BehavioralMonitor
from corvus.policy.combiner import DecisionCombiner
from corvus.policy.engine import PolicyEngine
from corvus.policy.facts import FactGatherer
from corvus.policy.grants import GrantEngine
from corvus.policy.identity import IdentityResolver
from corvus.policy.quota import QuotaService
from corvus.policy.rules import RuleStore
from corvus.server.catalog_store import CatalogStore
from corvus.server.config import ServerConfig, load_config
from corvus.server.correlation import CorrelationStore
from corvus.server.db import Database, hash_secret
from corvus.server.elevation_sweeper import ElevationSweeper
from corvus.server.handshake import HandshakeHandler
from corvus.server.manifest import (
    canonical_manifest,
    default_chat_manifest,
    full_capability_manifest,
    manifest_hash,
)
from corvus.server.pending_replay import PendingReplayQueue
from corvus.server.router import MessageRouter
from corvus.server.session import SessionManager
from corvus.server.settings_store import (
    apply_settings_to_context,
    ensure_settings_seeded,
    load_settings_into_config,
)
from corvus.server.transport import AgentTransport
from corvus.tools.service import ToolGatewayService

TEST_AGENT_ID = "test-agent-01"
TEST_MANIFEST = canonical_manifest(default_chat_manifest())
TEST_MANIFEST_HASH = manifest_hash(TEST_MANIFEST)
FULL_TEST_MANIFEST = canonical_manifest(full_capability_manifest())
FULL_TEST_MANIFEST_HASH = manifest_hash(FULL_TEST_MANIFEST)


class AppContext:
    def __init__(self, config: ServerConfig | None = None) -> None:
        self.config = config or load_config()
        self.transport = AgentTransport()
        self.db = Database(self.config.db_path)
        self.catalog_store = CatalogStore(self.db)
        self.sessions = SessionManager(self.db, self.config)
        self.correlation = CorrelationStore(self.db, self.config)
        self.rules = RuleStore(self.db)
        self.identity = IdentityResolver(self.db)
        self.grants = GrantEngine(self.db)
        self.quotas = QuotaService(
            self.db,
            memory_writes_daily_limit=self.config.memory_writes_daily_limit,
        )
        self.llm_registry = LlmProviderRegistry.load(self.config.llm_providers_path)
        self.behavioral = BehavioralMonitor(self.db, self.config)
        self.facts = FactGatherer(
            self.db,
            self.correlation,
            identity=self.identity,
            grants=self.grants,
            quotas=self.quotas,
            behavioral=self.behavioral,
        )
        self.combiner = DecisionCombiner()
        self.policy = PolicyEngine(self.facts, self.rules, self.combiner)
        self.audit = AuditStore(self.db)
        self.llm = LlmGatewayService(
            self.db,
            self.audit,
            self.llm_registry,
            default_provider=self.config.llm_default_provider,
            request_timeout_seconds=self.config.llm_request_timeout_seconds,
        )
        self.tools = ToolGatewayService(self.db, self.audit)
        self.memory = MemoryService(
            self.db,
            self.audit,
            encryption_enabled=self.config.memory_encryption_enabled,
            master_key=self.config.memory_master_key,
        )
        self.pending_replay = PendingReplayQueue(self.db, self.transport, self.audit)
        self.elevation_replay = ElevationReplayService(
            self.db, self.memory, self.transport, self.audit, self.pending_replay
        )
        self.memory_sweeper = MemoryRetentionSweeper(
            self.db,
            interval_seconds=self.config.memory_sweep_interval_seconds,
            soft_delete_retention_hours=self.config.memory_soft_delete_retention_hours,
        )
        self.elevation_sweeper = ElevationSweeper(
            self.db,
            interval_seconds=self.config.elevation_sweep_interval_seconds,
        )
        self.handshake = HandshakeHandler(
            self.db,
            self.sessions,
            self.rules,
            transport=self.transport,
            pending_replay=self.pending_replay,
        )
        self.router = MessageRouter(
            self.sessions,
            self.handshake,
            self.correlation,
            self.policy,
            self.audit,
            memory=self.memory,
            llm=self.llm,
            tools=self.tools,
            behavioral=self.behavioral,
            quotas=self.quotas,
            llm_tokens_daily_limit=self.config.llm_tokens_daily_limit,
            elevation_ttl_hours=self.config.elevation_ttl_hours,
            elevation_webhook_url=self.config.elevation_webhook_url,
            elevation_webhook_secret=self.config.elevation_webhook_secret,
            transport=self.transport,
        )

    async def startup(self) -> None:
        await self.db.connect()
        await self.catalog_store.ensure_seeded()
        await self.catalog_store.seed_llm_providers_from_registry(self.llm_registry)
        rebuilt = self.catalog_store.rebuild_llm_registry()
        if rebuilt is not None:
            self.llm_registry = rebuilt
            self.llm.registry = rebuilt
        self.memory.bind_catalog(self.catalog_store.catalog)
        await ensure_settings_seeded(self.db, self.config)
        merged = await load_settings_into_config(self.db, self.config)
        apply_settings_to_context(self, merged)
        await self.rules.load_from_file(self.config.rules_path)
        await self.db.upsert_agent(TEST_AGENT_ID, TEST_MANIFEST_HASH, TEST_MANIFEST)
        await self.db.upsert_user(
            "test-user",
            "researcher",
            {
                "groups": ["research"],
                "privileges": [],
                "allowed_agents": [TEST_AGENT_ID],
                "credential_hash": hash_secret("1234"),
                "aliases": [
                    {
                        "platform": "whatsapp",
                        "value": "+15550101001",
                        "verified": True,
                        "auth_method": "phone_number",
                        "display_name": "Test User",
                    },
                    {
                        "platform": "cli",
                        "value": "test-user",
                        "verified": True,
                        "auth_method": "pin",
                    },
                ],
            },
        )
        await self.db.upsert_user(
            "admin-user",
            "admin",
            {
                "groups": ["admins"],
                "privileges": ["approve_elevation", "manage_rules"],
                "allowed_agents": ["*"],
                "credential_hash": hash_secret("0000"),
                "aliases": [
                    {
                        "platform": "cli",
                        "value": "admin-user",
                        "verified": True,
                        "auth_method": "pin",
                    }
                ],
            },
        )

        await self.memory_sweeper.start()
        await self.elevation_sweeper.start()
        await self.correlation.startup()
        await self.behavioral.startup()

    async def shutdown(self) -> None:
        await self.memory_sweeper.stop()
        await self.elevation_sweeper.stop()
        await self.db.close()

    async def handle_message(self, message, connection_id: int):
        return await self.router.handle(message, connection_id)
