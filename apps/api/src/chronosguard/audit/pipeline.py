"""The audit pipeline: split → embed → retrieve → judge → ground → roll up.

Retrieval runs sequentially (one AsyncSession is not concurrency-safe); LLM
judging fans out under a semaphore (no session involvement). A clause whose
LLM call fails is an ``error`` outcome — never silently compliant.
"""

import asyncio
import datetime as dt
from dataclasses import dataclass, field

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from chronosguard.audit.grounding import quote_is_grounded
from chronosguard.audit.prompt import SYSTEM_PROMPT, build_user_payload
from chronosguard.audit.schema import ClauseVerdict, Verdict
from chronosguard.models import RegulatoryDocument, RunStatus, RunVerdict
from chronosguard.providers.base import ChatProvider, EmbeddingProvider, TokenUsage
from chronosguard.retrieval.candidates import (
    Candidate,
    citation_lookup,
    merge_candidates,
    vector_search,
)
from chronosguard.retrieval.policy_split import PolicyClause, split_policy

logger = structlog.get_logger(__name__)

CLAUSE_CONCURRENCY = 5
TOP_K_PER_CLAUSE = 8
LOW_CONFIDENCE_THRESHOLD = 0.6


@dataclass(frozen=True)
class ResolvedFinding:
    clause_index: int
    offending_policy_text: str
    legal_rule_text: str
    citation: str
    source_chunk_id: int | None
    source_document_id: int | None
    source_url: str
    risk_level: str
    grounding_quote: str
    rationale: str
    suggested_fix: str
    confidence: float
    needs_review: bool


@dataclass
class ClauseOutcome:
    clause: PolicyClause
    verdict: Verdict | None  # None == LLM call errored
    findings: list[ResolvedFinding] = field(default_factory=list)
    error: str | None = None
    dropped_ungrounded: int = 0
    retrieved_chunk_ids: list[int] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)


@dataclass(frozen=True)
class PipelineResult:
    clauses: list[PolicyClause]
    outcomes: list[ClauseOutcome]
    status: RunStatus
    verdict: RunVerdict | None
    coverage: dict[str, int]
    total_prompt_tokens: int
    total_completion_tokens: int
    retrieved_chunk_ids: list[int]


async def _retrieve_for_clause(
    session: AsyncSession,
    clause: PolicyClause,
    clause_vector: list[float],
    *,
    jurisdiction: str,
    as_of: dt.date,
) -> list[Candidate]:
    vector_hits = await vector_search(
        session, clause_vector, jurisdiction=jurisdiction, as_of=as_of, top_k=TOP_K_PER_CLAUSE
    )
    citation_hits = await citation_lookup(
        session, clause.text, jurisdiction=jurisdiction, as_of=as_of
    )
    return merge_candidates(vector_hits, citation_hits, top_k=TOP_K_PER_CLAUSE)


async def _judge_clause(
    chat: ChatProvider,
    clause: PolicyClause,
    candidates: list[Candidate],
    *,
    jurisdiction: str,
    as_of: dt.date,
    source_urls: dict[int, tuple[int, str]],  # document_id -> (document_id, source_url)
    semaphore: asyncio.Semaphore,
) -> ClauseOutcome:
    outcome = ClauseOutcome(
        clause=clause,
        verdict=None,
        retrieved_chunk_ids=[c.chunk.id for c in candidates if c.chunk.id is not None],
    )
    if not candidates:
        outcome.verdict = Verdict.INSUFFICIENT_EVIDENCE
        return outcome

    user_payload, ref_map = build_user_payload(
        clause_text=clause.text, jurisdiction=jurisdiction, as_of=as_of, candidates=candidates
    )
    try:
        async with semaphore:
            raw_verdict, usage = await chat.complete_structured(
                system=SYSTEM_PROMPT, user=user_payload, response_model=ClauseVerdict
            )
        outcome.usage = usage
    except Exception as exc:
        logger.exception("clause_audit_failed", clause_index=clause.index)
        outcome.error = type(exc).__name__
        return outcome

    weak_retrieval = any(candidate.weak_match for candidate in candidates)
    for finding in raw_verdict.findings:
        candidate = ref_map.get(finding.ref_id)
        if candidate is None or candidate.chunk.id is None:
            outcome.dropped_ungrounded += 1
            continue
        if not quote_is_grounded(finding.grounding_quote, candidate.chunk.content):
            outcome.dropped_ungrounded += 1
            continue
        document = source_urls.get(candidate.chunk.document_id)
        outcome.findings.append(
            ResolvedFinding(
                clause_index=clause.index,
                offending_policy_text=clause.text,
                legal_rule_text=candidate.chunk.content,  # from DB
                citation=candidate.chunk.legal_citation,  # from DB
                source_chunk_id=candidate.chunk.id,
                source_document_id=document[0] if document else None,
                source_url=document[1] if document else "",
                risk_level=finding.risk_level.value,
                grounding_quote=finding.grounding_quote,
                rationale=finding.rationale,
                suggested_fix=finding.suggested_fix,
                confidence=raw_verdict.confidence,
                needs_review=weak_retrieval or raw_verdict.confidence < LOW_CONFIDENCE_THRESHOLD,
            )
        )

    if raw_verdict.verdict is Verdict.VIOLATION and not outcome.findings:
        # Everything the model claimed failed grounding — hallucination caught.
        outcome.verdict = Verdict.INSUFFICIENT_EVIDENCE
    else:
        outcome.verdict = raw_verdict.verdict
    return outcome


def rollup(outcomes: list[ClauseOutcome]) -> tuple[RunStatus, RunVerdict | None, dict[str, int]]:
    coverage = {"violation": 0, "compliant": 0, "insufficient_evidence": 0, "error": 0}
    for outcome in outcomes:
        if outcome.error is not None:
            coverage["error"] += 1
        elif outcome.verdict is Verdict.VIOLATION:
            coverage["violation"] += 1
        elif outcome.verdict is Verdict.COMPLIANT:
            coverage["compliant"] += 1
        else:
            coverage["insufficient_evidence"] += 1

    status = RunStatus.PARTIAL if coverage["error"] else RunStatus.SUCCEEDED
    verdict: RunVerdict | None
    if coverage["violation"]:
        verdict = RunVerdict.VIOLATIONS_FOUND
    elif coverage["error"]:
        verdict = None  # never COMPLIANT when clauses errored
    elif coverage["compliant"]:
        verdict = RunVerdict.COMPLIANT
    elif coverage["insufficient_evidence"]:
        verdict = RunVerdict.INSUFFICIENT_EVIDENCE
    else:
        verdict = None
    return status, verdict, coverage


async def run_audit_pipeline(
    session: AsyncSession,
    embedder: EmbeddingProvider,
    chat: ChatProvider,
    *,
    policy_text: str,
    jurisdiction: str,
    as_of: dt.date,
) -> PipelineResult:
    clauses = split_policy(policy_text)
    vectors = await embedder.embed([clause.text for clause in clauses])

    candidates_per_clause: list[list[Candidate]] = []
    for clause, vector in zip(clauses, vectors, strict=True):
        candidates_per_clause.append(
            await _retrieve_for_clause(
                session, clause, vector, jurisdiction=jurisdiction, as_of=as_of
            )
        )

    document_ids = {
        candidate.chunk.document_id
        for candidates in candidates_per_clause
        for candidate in candidates
    }
    source_urls: dict[int, tuple[int, str]] = {}
    if document_ids:
        rows = await session.execute(
            select(col(RegulatoryDocument.id), col(RegulatoryDocument.source_url)).where(
                col(RegulatoryDocument.id).in_(document_ids)
            )
        )
        source_urls = {row[0]: (row[0], row[1]) for row in rows.fetchall()}

    semaphore = asyncio.Semaphore(CLAUSE_CONCURRENCY)
    outcomes = list(
        await asyncio.gather(
            *(
                _judge_clause(
                    chat,
                    clause,
                    candidates,
                    jurisdiction=jurisdiction,
                    as_of=as_of,
                    source_urls=source_urls,
                    semaphore=semaphore,
                )
                for clause, candidates in zip(clauses, candidates_per_clause, strict=True)
            )
        )
    )

    status, verdict, coverage = rollup(outcomes)
    all_chunk_ids = sorted(
        {chunk_id for outcome in outcomes for chunk_id in outcome.retrieved_chunk_ids}
    )
    return PipelineResult(
        clauses=clauses,
        outcomes=outcomes,
        status=status,
        verdict=verdict,
        coverage=coverage,
        total_prompt_tokens=sum(outcome.usage.prompt_tokens for outcome in outcomes),
        total_completion_tokens=sum(outcome.usage.completion_tokens for outcome in outcomes),
        retrieved_chunk_ids=all_chunk_ids,
    )
