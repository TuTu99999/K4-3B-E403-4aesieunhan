from __future__ import annotations

from collections import Counter

from app.eval.cp3_runner import _load_cases, _repo_root


def test_cp3_golden_set_meets_required_coverage() -> None:
    cases = _load_cases(_repo_root() / "eval" / "cp3_golden_set.json")
    buckets = Counter(case.bucket for case in cases)

    assert len(cases) >= 20
    assert buckets["hard_source_truth"] >= 2
    assert buckets["hard_ambiguous"] >= 2
    assert buckets["hard_out_of_scope"] >= 2
    assert buckets["hard_domain_specific"] >= 2
    assert 8 <= buckets["common"] <= 10
    assert 2 <= buckets["rare"] <= 4
    assert sum(case.origin == "real_chatlog_paraphrase" for case in cases) >= 10


def test_cp3_real_derived_cases_use_hashed_source_references() -> None:
    cases = _load_cases(_repo_root() / "eval" / "cp3_golden_set.json")

    for case in cases:
        source_hash = case.metadata.get("source_ref_hash")
        if case.origin == "real_chatlog_paraphrase":
            assert isinstance(source_hash, str)
            assert len(source_hash) == 64
            assert all(character in "0123456789abcdef" for character in source_hash)
        else:
            assert source_hash is None
