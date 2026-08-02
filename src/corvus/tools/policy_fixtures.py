"""YAML policy fixture runner for CI regression gates."""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from corvus.policy.engine import PolicyEngine
from corvus.protocol import (
    DestinationType,
    EngineId,
    FrameworkMessage,
    MessageClass,
    MessageDestination,
    MessageSource,
    MessageTags,
    TriggeredBy,
)
from corvus.server.bootstrap import AppContext
from corvus.server.config import ServerConfig


@dataclass(frozen=True)
class FixtureCase:
    id: str
    source_file: Path
    message: dict[str, Any]
    context: dict[str, Any]
    expect: dict[str, Any]


@dataclass(frozen=True)
class FixtureFailure:
    case_id: str
    source_file: Path
    detail: str


def default_fixtures_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "policy_fixtures"


def default_rules_path() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "default_rules.yaml"


def load_fixture_cases(fixtures_dir: Path) -> list[FixtureCase]:
    cases: list[FixtureCase] = []
    for path in sorted(fixtures_dir.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for index, entry in enumerate(raw.get("fixtures", []), start=1):
            case_id = str(entry.get("id") or f"{path.stem}-{index}")
            cases.append(
                FixtureCase(
                    id=case_id,
                    source_file=path,
                    message=dict(entry["message"]),
                    context=dict(entry.get("context") or {}),
                    expect=dict(entry["expect"]),
                )
            )
    return cases


def message_from_fixture(data: dict[str, Any]) -> FrameworkMessage:
    source = data.get("source") or {}
    tags = data.get("tags") or {}
    triggered_by = tags.get("triggered_by", "agent_initiated")
    return FrameworkMessage(
        source=MessageSource(
            agent_id=str(source.get("agent_id", "test-agent-01")),
            engine=EngineId(str(source.get("engine", "engine1"))),
            vm_id=str(source.get("vm_id", "vm-fixture")),
        ),
        destination=MessageDestination(
            type=DestinationType.CORVUS_SERVER,
            target="corvus_server",
        ),
        message_class=MessageClass.REQUEST,
        type=str(data["type"]),
        tags=MessageTags(
            triggered_by=TriggeredBy(triggered_by),
            scope=tags.get("scope", "local"),
        ),
        payload=dict(data.get("payload") or {}),
    )


def _compare_case(case: FixtureCase, decision) -> FixtureFailure | None:
    expect = case.expect
    if decision.decision != expect.get("decision"):
        return FixtureFailure(
            case_id=case.id,
            source_file=case.source_file,
            detail=f"decision: expected {expect.get('decision')!r}, got {decision.decision!r}",
        )
    expected_code = expect.get("effective_error_code")
    if expected_code is not None and decision.effective_error_code != expected_code:
        return FixtureFailure(
            case_id=case.id,
            source_file=case.source_file,
            detail=(
                "effective_error_code: "
                f"expected {expected_code!r}, got {decision.effective_error_code!r}"
            ),
        )
    expected_rules = expect.get("matched_rule_ids")
    if expected_rules is not None:
        actual = {match.rule_id for match in decision.matched_rules if match.conditions_passed}
        missing = [rule_id for rule_id in expected_rules if rule_id not in actual]
        if missing:
            return FixtureFailure(
                case_id=case.id,
                source_file=case.source_file,
                detail=f"matched_rule_ids missing: {missing} (actual={sorted(actual)})",
            )
    return None


async def run_fixture_cases(
    cases: list[FixtureCase],
    *,
    policy: PolicyEngine,
) -> list[FixtureFailure]:
    failures: list[FixtureFailure] = []
    for case in cases:
        message = message_from_fixture(case.message)
        decision = await policy.simulate(message, case.context)
        failure = _compare_case(case, decision)
        if failure is not None:
            failures.append(failure)
    return failures


def _server_config(db_path: Path, rules_path: Path) -> ServerConfig:
    return ServerConfig(
        db_path=db_path,
        use_tcp=True,
        tcp_host="127.0.0.1",
        tcp_port=0,
        vsock_host_cid=2,
        vsock_port=4040,
        mgmt_host="127.0.0.1",
        mgmt_port=0,
        api_key="fixture-key",
        rules_path=rules_path,
        turn_timeout_seconds=300,
        max_chain_depth=16,
        session_ttl_hours=24,
        vm_state_dir=db_path.parent / "vms",
        memory_sweep_interval_seconds=86400.0,
        memory_soft_delete_retention_hours=24,
        elevation_sweep_interval_seconds=86400.0,
        elevation_ttl_hours=1,
        elevation_webhook_url=None,
        behavioral_grant_denial_window_minutes=10,
        behavioral_grant_denial_threshold=3,
        behavioral_cross_agent_window_minutes=1,
        behavioral_cross_agent_threshold=10,
        behavioral_rate_baseline_minutes=60,
        behavioral_rate_zscore_threshold=3.0,
        behavioral_tool_zscore_threshold=3.0,
        behavioral_counter_retention_hours=24,
        memory_encryption_enabled=False,
        memory_master_key=None,
        memory_writes_daily_limit=10_000,
        llm_providers_path=Path(__file__).resolve().parents[3] / "config" / "llm_providers.yaml",
        llm_default_provider="stub",
        llm_request_timeout_seconds=60.0,
        llm_tokens_daily_limit=100_000,
    )


async def run_fixture_suite(
    *,
    fixtures_dir: Path,
    rules_path: Path,
    db_path: Path,
) -> list[FixtureFailure]:
    cases = load_fixture_cases(fixtures_dir)
    if not cases:
        raise RuntimeError(f"no fixtures found in {fixtures_dir}")
    ctx = AppContext(_server_config(db_path, rules_path))
    await ctx.startup()
    try:
        return await run_fixture_cases(cases, policy=ctx.policy)
    finally:
        await ctx.shutdown()


def format_failures(failures: list[FixtureFailure]) -> str:
    lines = [f"Policy fixture failures ({len(failures)}):"]
    for failure in failures:
        lines.append(f"  - {failure.case_id} ({failure.source_file.name}): {failure.detail}")
    return "\n".join(lines)


async def _async_main(args: argparse.Namespace) -> int:
    fixtures_dir = Path(args.fixtures_dir)
    rules_path = Path(args.rules)
    db_path = Path(args.db_path) if args.db_path else fixtures_dir / ".fixture-run.db"
    failures = await run_fixture_suite(
        fixtures_dir=fixtures_dir,
        rules_path=rules_path,
        db_path=db_path,
    )
    if failures:
        print(format_failures(failures), file=sys.stderr)
        return 1
    case_count = len(load_fixture_cases(fixtures_dir))
    print(f"Policy fixtures passed ({case_count} cases, rules={rules_path.name})")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Corvus RBAC policy YAML fixtures")
    parser.add_argument(
        "--fixtures-dir",
        default=str(default_fixtures_dir()),
        help="Directory containing *.yaml fixture files",
    )
    parser.add_argument(
        "--rules",
        default=str(default_rules_path()),
        help="Rules YAML path (defaults to config/default_rules.yaml)",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Optional SQLite path for fixture evaluation (default: temp under fixtures dir)",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_async_main(args)))


if __name__ == "__main__":
    main()
