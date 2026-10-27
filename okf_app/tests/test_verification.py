import hashlib
import shutil
import socket
from pathlib import Path

import pytest

from okf_knowledge.verification import audit_access, compare_manifest, observe_knowledge

BUNDLE = Path(__file__).resolve().parents[1] / "bundle"


@pytest.fixture
def bundle(tmp_path):
    return Path(shutil.copytree(BUNDLE, tmp_path / "bundle"))


def test_real_observations_cover_all_required_knowledge(bundle):
    result = observe_knowledge(bundle)
    assert result["validation"]["ezstore_bundle_valid"]
    assert len(result["concepts"]) == 4 and all(c["passed"] for c in result["concepts"])
    assert len(result["cases"]) == 4 and all(c["passed"] for c in result["cases"])
    assert len(result["unsupported"]) == 6 and all(c["passed"] for c in result["unsupported"])
    assert result["read_only_passed"]
    assert result["access"]["file_reads"] > 0


def test_changed_knowledge_produces_real_failure_not_fixed_pass(bundle):
    path = bundle / "quotation-pricing.md"
    path.write_text(path.read_text(encoding="utf-8").replace("`0.80`", "`0.73`"), encoding="utf-8")
    result = observe_knowledge(bundle)
    assert result["validation"]["ezstore_bundle_valid"]
    assert result["cases"][0]["grounded_in_source"]
    assert "0.73" in result["cases"][0]["markdown"]
    assert not result["cases"][0]["passed"]


def test_invalid_bundle_is_recorded_as_failure(bundle):
    (bundle / "index.md").unlink()
    result = observe_knowledge(bundle)
    assert not result["validation"]["ezstore_bundle_valid"]
    assert result["error"] and not result["cases"]
    assert not result["read_only_passed"]


def test_write_audit_blocks_actual_file_creation(tmp_path):
    target = tmp_path / "must-not-exist.txt"
    with audit_access() as observed:
        with pytest.raises(AssertionError, match="writing"):
            target.write_text("blocked", encoding="utf-8")
    assert observed["write_attempts"] and not target.exists()


def test_network_audit_blocks_socket_creation():
    with audit_access() as observed:
        with pytest.raises(AssertionError, match="socket"):
            socket.socket()
    assert observed["network_attempts"] == ["socket.socket"]


def test_hash_comparison_detects_changed_and_missing_files(tmp_path):
    path = tmp_path / "original.txt"
    path.write_bytes(b"original")
    manifest = {"original.txt": hashlib.sha256(b"original").hexdigest()}
    assert compare_manifest(tmp_path, manifest)["passed"]
    path.write_bytes(b"changed")
    assert compare_manifest(tmp_path, manifest)["changed"] == ["original.txt"]
    path.unlink()
    assert not compare_manifest(tmp_path, manifest)["passed"]
