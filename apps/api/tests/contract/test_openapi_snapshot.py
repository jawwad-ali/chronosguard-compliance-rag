"""OpenAPI snapshot drift — the frozen contract for the Next.js UI and n8n.

A schema change without a deliberate re-export fails CI here. To accept an
intentional change: ``uv run chronos export-openapi`` and commit the diff —
the PR then SHOWS the contract change to reviewers.
"""

import json
from pathlib import Path

import pytest

from chronosguard.core.config import Settings
from chronosguard.main import create_app

pytestmark = pytest.mark.contract

SNAPSHOT = Path(__file__).parents[3] / ".." / "packages" / "contracts" / "openapi.json"


class TestContractFreeze:
    def test_live_schema_matches_committed_snapshot(self) -> None:
        live = create_app(Settings(worker_enabled=False, log_level="WARNING")).openapi()
        snapshot_path = SNAPSHOT.resolve()
        assert snapshot_path.exists(), (
            f"Missing contract snapshot at {snapshot_path} — "
            "run `uv run chronos export-openapi` and commit it."
        )
        committed = json.loads(snapshot_path.read_text(encoding="utf-8"))
        assert live == committed, (
            "OpenAPI contract drifted from packages/contracts/openapi.json. "
            "If intentional: `uv run chronos export-openapi`, review the diff, commit."
        )

    def test_core_operations_present(self) -> None:
        """The endpoints the Phase-2 consumers are being built against."""
        schema = create_app(Settings(worker_enabled=False, log_level="WARNING")).openapi()
        operation_ids = {
            operation.get("operationId")
            for methods in schema["paths"].values()
            for operation in methods.values()
            if isinstance(operation, dict)
        }
        assert {
            "create_audit",
            "get_audit",
            "list_audit_findings",
            "search_regulatory",
            "trigger_ingest",
            "get_ingest_job",
            "create_policy",
        } <= operation_ids
