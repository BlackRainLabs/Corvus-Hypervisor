"""Policy fixture regression tests."""

import pytest

from corvus.tools.policy_fixtures import (
    default_fixtures_dir,
    default_rules_path,
    format_failures,
    load_fixture_cases,
    run_fixture_suite,
)


@pytest.mark.asyncio
async def test_core_policy_fixtures_pass(tmp_path):
    failures = await run_fixture_suite(
        fixtures_dir=default_fixtures_dir(),
        rules_path=default_rules_path(),
        db_path=tmp_path / "fixtures.db",
    )
    assert failures == [], format_failures(failures)


def test_core_fixture_suite_is_non_empty():
    cases = load_fixture_cases(default_fixtures_dir())
    assert len(cases) >= 10
