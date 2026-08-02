"""Server configuration from environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Linux VMADDR_CID_HOST — host-side vsock listener / guest connect target
VSOCK_HOST_CID = 2


@dataclass(frozen=True)
class ServerConfig:
    db_path: Path
    use_tcp: bool
    tcp_host: str
    tcp_port: int
    vsock_host_cid: int
    vsock_port: int
    mgmt_host: str
    mgmt_port: int
    api_key: str
    rules_path: Path
    turn_timeout_seconds: int
    max_chain_depth: int
    session_ttl_hours: int
    vm_state_dir: Path
    memory_sweep_interval_seconds: float
    memory_soft_delete_retention_hours: int
    elevation_sweep_interval_seconds: float
    elevation_ttl_hours: int
    elevation_webhook_url: str | None
    behavioral_grant_denial_window_minutes: int
    behavioral_grant_denial_threshold: int
    behavioral_cross_agent_window_minutes: int
    behavioral_cross_agent_threshold: int
    behavioral_rate_baseline_minutes: int
    behavioral_rate_zscore_threshold: float
    behavioral_tool_zscore_threshold: float
    behavioral_counter_retention_hours: int
    memory_encryption_enabled: bool
    memory_master_key: str | None
    memory_writes_daily_limit: int
    llm_providers_path: Path
    llm_default_provider: str
    llm_request_timeout_seconds: float
    llm_tokens_daily_limit: int
    ui_enabled: bool = True
    ui_session_secret: str = ""
    ui_path_prefix: str = "/ui"
    api_rate_limit_per_minute: int = 100
    elevation_webhook_secret: str | None = None

    @property
    def vsock_cid(self) -> int:
        """Backward-compatible alias for host listen CID."""
        return self.vsock_host_cid


def load_config() -> ServerConfig:
    root = Path(os.environ.get("CORVUS_ROOT", Path.cwd()))
    return ServerConfig(
        db_path=Path(os.environ.get("CORVUS_DB_PATH", root / "corvus.db")),
        use_tcp=os.environ.get("CORVUS_USE_TCP", "0") == "1",
        tcp_host=os.environ.get("CORVUS_TCP_HOST", "127.0.0.1"),
        tcp_port=int(os.environ.get("CORVUS_TCP_PORT", "4040")),
        vsock_host_cid=int(os.environ.get("CORVUS_VSOCK_HOST_CID", str(VSOCK_HOST_CID))),
        vsock_port=int(os.environ.get("CORVUS_VSOCK_PORT", "4040")),
        mgmt_host=os.environ.get("CORVUS_MGMT_HOST", "127.0.0.1"),
        mgmt_port=int(os.environ.get("CORVUS_MGMT_PORT", "8080")),
        api_key=os.environ.get("CORVUS_API_KEY", "dev-api-key"),
        rules_path=Path(
            os.environ.get("CORVUS_RULES_PATH", root / "config" / "default_rules.yaml")
        ),
        turn_timeout_seconds=int(os.environ.get("CORVUS_TURN_TIMEOUT", "300")),
        max_chain_depth=int(os.environ.get("CORVUS_MAX_CHAIN_DEPTH", "16")),
        session_ttl_hours=int(os.environ.get("CORVUS_SESSION_TTL_HOURS", "24")),
        vm_state_dir=Path(os.environ.get("CORVUS_VM_STATE_DIR", "/tmp/corvus-vms")),
        memory_sweep_interval_seconds=float(
            os.environ.get("CORVUS_MEMORY_SWEEP_INTERVAL_SECONDS", "900")
        ),
        memory_soft_delete_retention_hours=int(
            os.environ.get("CORVUS_MEMORY_SOFT_DELETE_RETENTION_HOURS", "24")
        ),
        elevation_sweep_interval_seconds=float(
            os.environ.get("CORVUS_ELEVATION_SWEEP_INTERVAL_SECONDS", "300")
        ),
        elevation_ttl_hours=int(os.environ.get("CORVUS_ELEVATION_TTL_HOURS", "1")),
        elevation_webhook_url=os.environ.get("CORVUS_ELEVATION_WEBHOOK_URL") or None,
        behavioral_grant_denial_window_minutes=int(
            os.environ.get("CORVUS_BEHAVIORAL_GRANT_DENIAL_WINDOW_MINUTES", "10")
        ),
        behavioral_grant_denial_threshold=int(
            os.environ.get("CORVUS_BEHAVIORAL_GRANT_DENIAL_THRESHOLD", "3")
        ),
        behavioral_cross_agent_window_minutes=int(
            os.environ.get("CORVUS_BEHAVIORAL_CROSS_AGENT_WINDOW_MINUTES", "1")
        ),
        behavioral_cross_agent_threshold=int(
            os.environ.get("CORVUS_BEHAVIORAL_CROSS_AGENT_THRESHOLD", "10")
        ),
        behavioral_rate_baseline_minutes=int(
            os.environ.get("CORVUS_BEHAVIORAL_RATE_BASELINE_MINUTES", "60")
        ),
        behavioral_rate_zscore_threshold=float(
            os.environ.get("CORVUS_BEHAVIORAL_RATE_ZSCORE_THRESHOLD", "3.0")
        ),
        behavioral_tool_zscore_threshold=float(
            os.environ.get("CORVUS_BEHAVIORAL_TOOL_ZSCORE_THRESHOLD", "3.0")
        ),
        behavioral_counter_retention_hours=int(
            os.environ.get("CORVUS_BEHAVIORAL_COUNTER_RETENTION_HOURS", "24")
        ),
        memory_encryption_enabled=os.environ.get("CORVUS_MEMORY_ENCRYPTION", "0") == "1",
        memory_master_key=os.environ.get("CORVUS_MASTER_KEY") or None,
        memory_writes_daily_limit=int(
            os.environ.get("CORVUS_MEMORY_WRITES_DAILY_LIMIT", "10000")
        ),
        llm_providers_path=Path(
            os.environ.get("CORVUS_LLM_PROVIDERS_PATH", root / "config" / "llm_providers.yaml")
        ),
        llm_default_provider=os.environ.get("CORVUS_LLM_DEFAULT_PROVIDER", "stub"),
        llm_request_timeout_seconds=float(
            os.environ.get("CORVUS_LLM_REQUEST_TIMEOUT_SECONDS", "60")
        ),
        llm_tokens_daily_limit=int(os.environ.get("CORVUS_LLM_TOKENS_DAILY_LIMIT", "100000")),
        ui_enabled=os.environ.get("CORVUS_UI_ENABLED", "1") == "1",
        ui_session_secret=os.environ.get("CORVUS_UI_SESSION_SECRET", ""),
        ui_path_prefix=os.environ.get("CORVUS_UI_PATH_PREFIX", "/ui"),
        api_rate_limit_per_minute=int(
            os.environ.get("CORVUS_API_RATE_LIMIT_PER_MINUTE", "100")
        ),
        elevation_webhook_secret=os.environ.get("CORVUS_ELEVATION_WEBHOOK_SECRET")
        or None,
    )
