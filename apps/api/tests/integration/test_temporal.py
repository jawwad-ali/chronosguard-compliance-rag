"""THE temporal truth table — the product's moat, proven case by case.

Every row asserts exactly which rules `in_force_chunks` returns for a
(jurisdiction, as-of date) pair against the seeded six-document corpus.
Citations: R1 7-day settlement [2024-01-01, 2026-06-01) · R2 3-day amendment
[2026-06-01, ∞) · R3 KYC retention [2023-07-15, ∞) · R4 pandemic relief
[2020-01-01, 2022-01-01) · R5 retroactive float rule [2026-01-01, ∞) ·
R6 unconfirmed draft (must NEVER surface).
"""

import datetime as dt

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from chronosguard.retrieval.temporal import in_force_chunks, resolve_as_of

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

R1 = "Regulation 12-B(4)"
R2 = "Regulation 12-B(4) (as amended)"
R3 = "Para 4(a)"
R4 = "Para 2"
R5 = "Regulation 7(2)"
R6 = "Para 1"


async def _in_force(engine: AsyncEngine, jurisdiction: str, as_of: dt.date) -> set[str]:
    async with AsyncSession(engine) as session:
        rows = (await session.execute(in_force_chunks(jurisdiction, as_of))).scalars().all()
    return {chunk.legal_citation for chunk in rows}


TRUTH_TABLE = [
    # (case id, as_of, expected citations)
    ("today_post_amendment", dt.date(2026, 6, 6), {R2, R3, R5}),
    ("before_amendment", dt.date(2025, 6, 1), {R1, R3}),
    ("retroactive_start_inclusive", dt.date(2026, 1, 1), {R1, R3, R5}),
    ("relief_last_day_in_force", dt.date(2021, 12, 31), {R4}),
    ("relief_expiry_day_excluded_halfopen", dt.date(2022, 1, 1), set()),
    ("old_rule_first_day_inclusive", dt.date(2024, 1, 1), {R1, R3}),
    ("amendment_boundary_swaps_rules", dt.date(2026, 6, 1), {R2, R3, R5}),
    ("before_any_rule", dt.date(2019, 6, 1), set()),
]


class TestTemporalTruthTable:
    @pytest.mark.parametrize(
        ("case_id", "as_of", "expected"),
        TRUTH_TABLE,
        ids=[case[0] for case in TRUTH_TABLE],
    )
    async def test_in_force_set_matches_truth_table(
        self,
        seeded_corpus: None,
        app_engine: AsyncEngine,
        case_id: str,
        as_of: dt.date,
        expected: set[str],
    ) -> None:
        assert await _in_force(app_engine, "PK", as_of) == expected

    async def test_unconfirmed_draft_never_surfaces_on_any_date(
        self, seeded_corpus: None, app_engine: AsyncEngine
    ) -> None:
        """The review gate: R6 is in its validity window but unconfirmed."""
        result = await _in_force(app_engine, "PK", dt.date(2026, 6, 6))
        assert R6 not in result

    async def test_unknown_jurisdiction_returns_nothing(
        self, seeded_corpus: None, app_engine: AsyncEngine
    ) -> None:
        assert await _in_force(app_engine, "US-TX", dt.date(2026, 6, 6)) == set()

    async def test_retroactive_rule_found_for_past_date_despite_late_ingestion(
        self, seeded_corpus: None, app_engine: AsyncEngine
    ) -> None:
        """Valid-time vs system-time: R5 was ingested 'now' but is in force from Jan 1."""
        in_march = await _in_force(app_engine, "PK", dt.date(2026, 3, 15))
        assert R5 in in_march

    async def test_superseded_rule_still_visible_for_historical_audits(
        self, seeded_corpus: None, app_engine: AsyncEngine
    ) -> None:
        """Point-in-time correctness: the OLD rule governs audits anchored before
        the amendment — supersession retires, never erases."""
        in_2025 = await _in_force(app_engine, "PK", dt.date(2025, 1, 1))
        assert R1 in in_2025
        assert R2 not in in_2025


class TestResolveAsOf:
    def test_explicit_date_wins(self) -> None:
        assert resolve_as_of(dt.date(2025, 5, 5)) == dt.date(2025, 5, 5)

    def test_defaults_to_today_utc(self) -> None:
        assert resolve_as_of(None) == dt.datetime.now(dt.UTC).date()
