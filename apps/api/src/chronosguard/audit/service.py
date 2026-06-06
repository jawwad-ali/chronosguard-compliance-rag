"""Audit run lifecycle: creation (request path) and execution (worker path)."""

import datetime as dt

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from chronosguard.audit.pipeline import run_audit_pipeline
from chronosguard.core.errors import NotFoundError, UnprocessableError
from chronosguard.models import (
    AuditFinding,
    AuditRun,
    Job,
    JobKind,
    Jurisdiction,
    RunStatus,
)
from chronosguard.providers.base import ChatProvider, EmbeddingProvider
from chronosguard.providers.pricing import chat_cost_usd
from chronosguard.retrieval.temporal import resolve_as_of
from chronosguard.schemas.audit import AuditCreate
from chronosguard.services import policies

logger = structlog.get_logger(__name__)


async def create_audit_run(session: AsyncSession, *, tenant_id: int, body: AuditCreate) -> AuditRun:
    jurisdiction = (
        await session.execute(
            select(Jurisdiction).where(col(Jurisdiction.code) == body.jurisdiction)
        )
    ).scalar_one_or_none()
    if jurisdiction is None:
        raise UnprocessableError(f"Unknown jurisdiction: {body.jurisdiction}")

    policy_id: int | None = None
    policy_version_id: int | None = None
    if body.policy_id is not None:
        found = await policies.get_policy(session, body.policy_id)  # RLS-scoped
        if found is None:
            raise NotFoundError("Policy", body.policy_id)
        policy, version = found
        policy_id, policy_version_id = policy.id, version.id
        policy_text = version.body
    else:
        assert body.policy_text is not None  # noqa: S101 — schema validator guarantees
        policy_text = body.policy_text

    run = AuditRun(
        tenant_id=tenant_id,
        policy_id=policy_id,
        policy_version_id=policy_version_id,
        policy_text_snapshot=policy_text,
        jurisdiction=body.jurisdiction,
        as_of_date=resolve_as_of(body.as_of_date),
        status=RunStatus.QUEUED.value,
    )
    session.add(run)
    await session.flush()
    assert run.id is not None  # noqa: S101

    session.add(Job(kind=JobKind.AUDIT.value, ref_id=run.id, tenant_id=tenant_id))
    await session.flush()
    logger.info("audit_run_queued", run_id=run.id, jurisdiction=run.jurisdiction)
    return run


async def execute_audit_run(
    session: AsyncSession,
    run_id: int,
    *,
    embedder: EmbeddingProvider,
    chat: ChatProvider,
) -> None:
    """Worker path. ``session`` must already carry the run's tenant context."""
    run = await session.get(AuditRun, run_id)
    if run is None:  # tenant context missing would also land here — loud, not silent
        raise NotFoundError("AuditRun", run_id)

    run.status = RunStatus.RUNNING.value
    run.model = chat.model
    session.add(run)
    await session.flush()

    try:
        result = await run_audit_pipeline(
            session,
            embedder,
            chat,
            policy_text=run.policy_text_snapshot,
            jurisdiction=run.jurisdiction,
            as_of=run.as_of_date,
        )
    except Exception as exc:
        logger.exception("audit_run_failed", run_id=run_id)
        run.status = RunStatus.FAILED.value
        run.error = type(exc).__name__
        run.finished_at = dt.datetime.now(dt.UTC)
        session.add(run)
        await session.flush()
        raise

    for outcome in result.outcomes:
        for finding in outcome.findings:
            session.add(
                AuditFinding(
                    tenant_id=run.tenant_id,
                    run_id=run_id,
                    clause_index=finding.clause_index,
                    offending_policy_text=finding.offending_policy_text,
                    legal_rule_text=finding.legal_rule_text,
                    citation=finding.citation,
                    source_chunk_id=finding.source_chunk_id,
                    source_document_id=finding.source_document_id,
                    source_url=finding.source_url,
                    risk_level=finding.risk_level,
                    grounding_quote=finding.grounding_quote,
                    rationale=finding.rationale,
                    suggested_fix=finding.suggested_fix,
                    confidence=finding.confidence,
                    needs_review=finding.needs_review,
                )
            )

    run.status = result.status.value
    run.verdict = result.verdict.value if result.verdict else None
    run.coverage = result.coverage
    run.clauses_snapshot = [
        {"index": clause.index, "text": clause.text} for clause in result.clauses
    ]
    run.retrieved_chunk_ids = result.retrieved_chunk_ids
    run.total_tokens = result.total_prompt_tokens + result.total_completion_tokens
    run.cost_usd = chat_cost_usd(
        chat.model, result.total_prompt_tokens, result.total_completion_tokens
    )
    run.finished_at = dt.datetime.now(dt.UTC)
    session.add(run)
    await session.flush()
    dropped = sum(outcome.dropped_ungrounded for outcome in result.outcomes)
    logger.info(
        "audit_run_completed",
        run_id=run_id,
        status=run.status,
        verdict=run.verdict,
        coverage=result.coverage,
        dropped_ungrounded=dropped,  # the hallucination canary
        total_tokens=run.total_tokens,
        cost_usd=run.cost_usd,
    )
