"""Deterministic clause splitter."""

from chronosguard.retrieval.policy_split import (
    MAX_CLAUSE_CHARS,
    PolicyClause,
    split_policy,
)


class TestSplitPolicy:
    def test_blank_lines_delimit_clauses(self) -> None:
        text = ("A" * 150) + "\n\n" + ("B" * 150)
        clauses = split_policy(text)
        assert len(clauses) == 2
        assert clauses[0].index == 0
        assert clauses[1].index == 1

    def test_runts_never_stand_alone(self) -> None:
        text = ("A" * 150) + "\n\nShort note.\n\n" + ("B" * 150)
        clauses = split_policy(text)
        # "Short note." (<120 chars) cannot stand alone — the next segment
        # folds into it, so every emitted clause is substantial.
        assert len(clauses) == 2
        assert "Short note." in clauses[1].text
        assert clauses[1].text.endswith("B" * 150)

    def test_numbered_items_split(self) -> None:
        text = (
            "1. " + ("Employees must comply with all settlement rules. " * 4) + "\n"
            "2. " + ("Funds are held according to the published schedule. " * 4)
        )
        clauses = split_policy(text)
        assert len(clauses) == 2
        assert clauses[1].text.startswith("2.")

    def test_overlong_clause_hard_splits_on_sentences(self) -> None:
        sentence = "This is a fairly long compliance sentence for testing purposes. "
        text = sentence * 40  # ~2600 chars, no blank lines
        clauses = split_policy(text)
        assert len(clauses) >= 2
        assert all(len(clause.text) <= MAX_CLAUSE_CHARS for clause in clauses)

    def test_returns_typed_clauses(self) -> None:
        clauses = split_policy("Hello world policy text.")
        assert all(isinstance(clause, PolicyClause) for clause in clauses)
        assert len(clauses) == 1
