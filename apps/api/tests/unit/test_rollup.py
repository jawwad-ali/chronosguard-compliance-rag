"""Run-level rollup truth table — verdict can never lie COMPLIANT."""

from chronosguard.audit.pipeline import ClauseOutcome, rollup
from chronosguard.audit.schema import Verdict
from chronosguard.models import RunStatus, RunVerdict
from chronosguard.retrieval.policy_split import PolicyClause


def _outcome(verdict: Verdict | None, *, error: str | None = None) -> ClauseOutcome:
    return ClauseOutcome(clause=PolicyClause(index=0, text="x"), verdict=verdict, error=error)


class TestRollup:
    def test_any_violation_wins(self) -> None:
        status, verdict, coverage = rollup(
            [_outcome(Verdict.VIOLATION), _outcome(Verdict.COMPLIANT)]
        )
        assert status is RunStatus.SUCCEEDED
        assert verdict is RunVerdict.VIOLATIONS_FOUND
        assert coverage == {
            "violation": 1,
            "compliant": 1,
            "insufficient_evidence": 0,
            "error": 0,
        }

    def test_all_compliant_is_compliant(self) -> None:
        status, verdict, _ = rollup([_outcome(Verdict.COMPLIANT), _outcome(Verdict.COMPLIANT)])
        assert (status, verdict) == (RunStatus.SUCCEEDED, RunVerdict.COMPLIANT)

    def test_all_insufficient_is_insufficient_never_compliant(self) -> None:
        status, verdict, _ = rollup([_outcome(Verdict.INSUFFICIENT_EVIDENCE)])
        assert (status, verdict) == (RunStatus.SUCCEEDED, RunVerdict.INSUFFICIENT_EVIDENCE)

    def test_clause_error_forces_partial_and_blocks_compliant(self) -> None:
        status, verdict, coverage = rollup(
            [_outcome(Verdict.COMPLIANT), _outcome(None, error="APITimeoutError")]
        )
        assert status is RunStatus.PARTIAL
        assert verdict is None  # an OpenAI failure can never produce a green check
        assert coverage["error"] == 1

    def test_violation_with_errors_still_reports_violations_but_partial(self) -> None:
        status, verdict, _ = rollup(
            [_outcome(Verdict.VIOLATION), _outcome(None, error="RateLimitError")]
        )
        assert (status, verdict) == (RunStatus.PARTIAL, RunVerdict.VIOLATIONS_FOUND)
