import json

from app.triage.validate import validate_report
from tests.fakes import DEMO_EVIDENCE, valid_report

IDS = {e.chunk_id for e in DEMO_EVIDENCE}


def types_of(violations):
    return [v.type for v in violations]


def test_valid_report_passes():
    report, violations = validate_report(valid_report(), IDS, require_citations=True)
    assert violations == []
    assert report is not None and report.severity is not None


def test_json_string_input_is_accepted():
    _, violations = validate_report(json.dumps(valid_report()), IDS, require_citations=True)
    assert violations == []


def test_unknown_citation_is_reported_per_id():
    raw = valid_report()
    raw["likely_causes"][0]["citations"] = ["RB-FAKE-999#s1"]
    raw["next_steps"][0]["citations"] = ["RB-DB-001#s3", "RB-DB-001#s99"]
    raw["severity_citations"] = ["POL-SEV-002#s1"]
    report, violations = validate_report(raw, IDS, require_citations=True)
    assert report is not None  # still parsed: shape was fine, grounding was not
    assert types_of(violations) == ["unknown_citation"] * 3
    assert any("RB-FAKE-999#s1" in v.detail for v in violations)


def test_empty_citations_are_missing_citation():
    raw = valid_report(severity_citations=[])
    raw["likely_causes"][0]["citations"] = []
    raw["next_steps"][0]["citations"] = []
    _, violations = validate_report(raw, IDS, require_citations=True)
    assert types_of(violations) == ["missing_citation"] * 3


def test_severity_none_without_abstaining_is_inconsistent():
    raw = valid_report(severity=None, severity_citations=[])
    _, violations = validate_report(raw, IDS, require_citations=True)
    assert types_of(violations) == ["inconsistent_abstention"]


def test_no_causes_without_abstaining_is_inconsistent():
    raw = valid_report(likely_causes=[])
    _, violations = validate_report(raw, IDS, require_citations=True)
    assert types_of(violations) == ["inconsistent_abstention"]


def test_honest_abstention_is_valid():
    raw = valid_report(severity=None, severity_citations=[], likely_causes=[], next_steps=[],
                       insufficient_evidence=True, missing_information=["error rate"])
    assert validate_report(raw, IDS, require_citations=True)[1] == []


def test_no_retrieval_mode_allows_empty_citations():
    raw = valid_report(severity_citations=[])
    raw["likely_causes"][0]["citations"] = []
    raw["next_steps"][0]["citations"] = []
    assert validate_report(raw, set(), require_citations=False)[1] == []


def test_no_retrieval_mode_penalises_hallucinated_ids():
    # The baseline saw no documents, so any id it writes is invented.
    _, violations = validate_report(valid_report(), set(), require_citations=False)
    assert set(types_of(violations)) == {"unknown_citation"}
    assert len(violations) == 4


def test_garbage_string_is_schema_error():
    report, violations = validate_report("Sure! Here's the report: {", IDS,
                                         require_citations=True)
    assert report is None
    assert types_of(violations) == ["schema_error"]


def test_none_is_schema_error():
    assert types_of(validate_report(None, IDS, require_citations=True)[1]) == ["schema_error"]


def test_wrong_shape_includes_pydantic_message():
    raw = valid_report(severity="CRITICAL")
    report, violations = validate_report(raw, IDS, require_citations=True)
    assert report is None and violations[0].type == "schema_error"
    assert "severity" in violations[0].detail


def test_json_array_is_schema_error():
    assert types_of(validate_report("[]", IDS, require_citations=True)[1]) == ["schema_error"]
