"""Golden-set quality evals: retrieval recall/MRR + audit verdict accuracy.

Run modes (provider selection):
- default: deterministic fakes — free, structural validation of the harness
- live:    set CG_EVAL_LIVE=1 + OPENAI_API_KEY — real models, costs cents

Thresholds are STARTING GATES (docs/ROADMAP.md C8), tuned as the golden set
grows. This lane never blocks merge; it is the quality dashboard.
"""

import datetime as dt
import os
from dataclasses import dataclass

import pytest
import structlog
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from chronosguard.audit.pipeline import run_audit_pipeline
from chronosguard.providers import FakeChat, FakeEmbeddings
from chronosguard.providers.base import ChatProvider, EmbeddingProvider
from chronosguard.services.search import search_regulations

pytestmark = [pytest.mark.eval, pytest.mark.anyio]

logger = structlog.get_logger("eval")

RECALL_GATE = 0.8
MRR_GATE = 0.5
VERDICT_ACCURACY_GATE = 0.66


def _providers() -> tuple[EmbeddingProvider, ChatProvider]:
    if os.environ.get("CG_EVAL_LIVE") == "1" and os.environ.get("OPENAI_API_KEY"):
        from chronosguard.providers.openai import OpenAIChat, OpenAIEmbeddings

        api_key = os.environ["OPENAI_API_KEY"]
        return (
            OpenAIEmbeddings(api_key=api_key, model="text-embedding-3-small"),
            OpenAIChat(api_key=api_key, model=os.environ.get("CG_EVAL_MODEL", "gpt-4o-mini")),
        )
    return FakeEmbeddings(), FakeChat()


@dataclass(frozen=True)
class RetrievalCase:
    case_id: str
    query: str
    as_of: dt.date
    expected_citations: set[str]


RETRIEVAL_GOLDEN = [
    RetrievalCase(
        "settlement_post_amendment",
        "retail digital payment accounts settle transit funds maximum window business days",
        dt.date(2026, 6, 6),
        {"Regulation 12-B(4) (as amended)"},
    ),
    RetrievalCase(
        "settlement_pre_amendment",
        "retail digital payment accounts settle transit funds maximum window business days",
        dt.date(2025, 1, 1),
        {"Regulation 12-B(4)"},
    ),
    RetrievalCase(
        "kyc_retention",
        "retain Know Your Customer KYC records due diligence documentation years",
        dt.date(2026, 6, 6),
        {"Para 4(a)"},
    ),
    RetrievalCase(
        "float_income_citation",
        "What does Regulation 7(2) require for customer float income?",
        dt.date(2026, 6, 6),
        {"Regulation 7(2)"},
    ),
    RetrievalCase(
        "expired_relief_window",
        "late filing penalties waived listed entities pandemic",
        dt.date(2021, 6, 1),
        {"Para 2"},
    ),
]


@dataclass(frozen=True)
class AuditCase:
    case_id: str
    policy_text: str
    as_of: dt.date
    expected_verdict: str


AUDIT_GOLDEN = [
    AuditCase(
        "pocketpay_violation_2026",
        "PocketPay will hold user funds for up to 7 business days before clearing.",
        dt.date(2026, 6, 6),
        "VIOLATIONS_FOUND",
    ),
    AuditCase(
        "pocketpay_compliant_2025",
        "PocketPay will hold user funds for up to 7 business days before clearing.",
        dt.date(2025, 1, 1),
        "COMPLIANT",
    ),
    AuditCase(
        "unrelated_clause_insufficient",
        "All staff must wear formal attire during client meetings on Mondays.",
        dt.date(2026, 6, 6),
        "INSUFFICIENT_EVIDENCE",
    ),
]


class TestRetrievalQuality:
    async def test_recall_and_mrr_meet_gates(
        self, seeded_corpus: None, app_engine: AsyncEngine
    ) -> None:
        embedder, _ = _providers()
        recalls: list[float] = []
        reciprocal_ranks: list[float] = []

        async with AsyncSession(app_engine) as session:
            for case in RETRIEVAL_GOLDEN:
                candidates = await search_regulations(
                    session,
                    embedder,
                    query=case.query,
                    jurisdiction="PK",
                    as_of=case.as_of,
                    top_k=8,
                )
                citations = [c.chunk.legal_citation for c in candidates]
                hit = case.expected_citations & set(citations)
                recalls.append(len(hit) / len(case.expected_citations))
                rank = next(
                    (i + 1 for i, cite in enumerate(citations) if cite in case.expected_citations),
                    None,
                )
                reciprocal_ranks.append(1.0 / rank if rank else 0.0)
                logger.info(
                    "eval_retrieval_case",
                    case=case.case_id,
                    recall=recalls[-1],
                    rank=rank,
                    top=citations[:3],
                )

        recall_at_8 = sum(recalls) / len(recalls)
        mrr = sum(reciprocal_ranks) / len(reciprocal_ranks)
        logger.info("eval_retrieval_summary", recall_at_8=recall_at_8, mrr=mrr)
        assert recall_at_8 >= RECALL_GATE, f"recall@8={recall_at_8:.2f} below {RECALL_GATE}"
        assert mrr >= MRR_GATE, f"MRR={mrr:.2f} below {MRR_GATE}"


class TestAuditQuality:
    async def test_verdict_accuracy_and_grounding(
        self, seeded_corpus: None, app_engine: AsyncEngine
    ) -> None:
        embedder, chat = _providers()
        correct = 0
        total_dropped = 0

        async with AsyncSession(app_engine) as session:
            for case in AUDIT_GOLDEN:
                result = await run_audit_pipeline(
                    session,
                    embedder,
                    chat,
                    policy_text=case.policy_text,
                    jurisdiction="PK",
                    as_of=case.as_of,
                )
                verdict = result.verdict.value if result.verdict else "NONE"
                if verdict == case.expected_verdict:
                    correct += 1
                total_dropped += sum(o.dropped_ungrounded for o in result.outcomes)
                logger.info(
                    "eval_audit_case",
                    case=case.case_id,
                    expected=case.expected_verdict,
                    actual=verdict,
                )

        accuracy = correct / len(AUDIT_GOLDEN)
        logger.info(
            "eval_audit_summary",
            verdict_accuracy=accuracy,
            grounding_drops=total_dropped,  # the hallucination canary
        )
        assert accuracy >= VERDICT_ACCURACY_GATE, (
            f"verdict accuracy {accuracy:.2f} below {VERDICT_ACCURACY_GATE}"
        )
