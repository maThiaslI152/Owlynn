import json
from pathlib import Path


def test_verify_report_fixture_matches_v1_schema_basics():
    fixture_path = Path("docs/examples/verify-report-sample.json")
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "owlynn.audit.verify-report.v1"
    assert payload["status"] in {"pass", "fail"}

    assert isinstance(payload["ts"], int)
    assert isinstance(payload["reason"], str)
    assert isinstance(payload["records_checked"], int)

    if "root_hash" in payload:
        assert isinstance(payload["root_hash"], str)
        assert len(payload["root_hash"]) == 64

    if "manifest_file" in payload:
        assert isinstance(payload["manifest_file"], str)
    if "bundle_file" in payload:
        assert isinstance(payload["bundle_file"], str)

    if "trace" in payload:
        assert isinstance(payload["trace"], list)
        assert all(isinstance(item, str) for item in payload["trace"])
