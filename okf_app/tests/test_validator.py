"""Stage 2 checks use local fixture copies; no live data, agent, or LLM calls."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from okf_knowledge.validator import CONCEPT_FILES, REQUIRED_FILES, main, validate_bundle

BUNDLE = Path(__file__).resolve().parents[1] / "bundle"


@pytest.fixture
def bundle(tmp_path):
    return Path(shutil.copytree(BUNDLE, tmp_path / "bundle"))


def replace_frontmatter(bundle, text):
    path = bundle / CONCEPT_FILES[0]
    path.write_text(text, encoding="utf-8")


def codes(result):
    return {issue.code for issue in result.issues}


def test_approved_bundle_parses_all_five_documents():
    result = validate_bundle(BUNDLE)
    assert result.valid, result.issues
    assert result.format_valid
    assert set(result.documents) == set(REQUIRED_FILES)
    assert result.summary()["parsed_concepts"] == 4
    for name in CONCEPT_FILES:
        document = result.documents[name]
        assert document.metadata["type"] == "Reference"
        assert document.body.strip()
        assert document.metadata["sources"]
        assert all(source["resource"].startswith("https://github.com/RCHD3388/ezstore/blob/")
                   for source in document.metadata["sources"])
    assert result.documents["index.md"].metadata == {"okf_version": "0.2"}


@pytest.mark.parametrize("name", REQUIRED_FILES)
def test_missing_required_file_is_a_project_error(bundle, name):
    (bundle / name).unlink()
    result = validate_bundle(bundle)
    assert not result.valid
    assert result.format_valid  # OKF itself does not require these exact filenames.
    assert any(issue.code == "file_missing" and issue.path == name for issue in result.issues)


@pytest.mark.parametrize("frontmatter", [
    "title: Missing type", "type:", 'type: ""', 'type: "   "',
    "type: 123", "type: true", "type: []", "type: {}",
])
def test_type_must_be_a_nonempty_string(bundle, frontmatter):
    replace_frontmatter(bundle, f"---\n{frontmatter}\n---\n# Concept\n")
    result = validate_bundle(bundle)
    assert not result.format_valid
    assert "type_invalid" in codes(result)


@pytest.mark.parametrize(("text", "code"), [
    ("# No frontmatter\n", "frontmatter_missing"),
    ("---\ntype: Reference\n", "frontmatter_unclosed"),
    ("---\ntype: [broken\n---\nBody", "yaml_invalid"),
    ("---\n- Reference\n---\nBody", "yaml_not_mapping"),
    ("---\n\n---\nBody", "yaml_not_mapping"),
    ("---\ntype: !!python/object/apply:os.system ['echo unsafe']\n---\nBody", "yaml_invalid"),
])
def test_malformed_or_unsafe_frontmatter_is_rejected(bundle, text, code):
    replace_frontmatter(bundle, text)
    result = validate_bundle(bundle)
    assert not result.format_valid
    assert code in codes(result)


def test_invalid_utf8_is_reported_as_parse_failure(bundle):
    (bundle / CONCEPT_FILES[0]).write_bytes(b"\xff\xfe")
    assert "parse_failed" in codes(validate_bundle(bundle))


def test_unknown_type_and_optional_metadata_are_preserved(bundle):
    replace_frontmatter(bundle, "---\ntype: Custom Knowledge\nextra: {owner: example}\n---\n# Body\n")
    result = validate_bundle(bundle)
    assert result.valid, result.issues
    metadata = result.documents[CONCEPT_FILES[0]].metadata
    assert metadata["type"] == "Custom Knowledge"
    assert metadata["extra"] == {"owner": "example"}


def test_root_index_may_omit_frontmatter(bundle):
    path = bundle / "index.md"
    path.write_text(path.read_text(encoding="utf-8").split("---", 2)[2], encoding="utf-8")
    assert validate_bundle(bundle).valid


@pytest.mark.parametrize("frontmatter", ['type: Reference', 'okf_version: 0.2'])
def test_reserved_root_index_frontmatter_rules(bundle, frontmatter):
    path = bundle / "index.md"
    path.write_text(f"---\n{frontmatter}\n---\n# Index", encoding="utf-8")
    assert not validate_bundle(bundle).format_valid


def test_nested_index_cannot_have_frontmatter(bundle):
    folder = bundle / "nested"
    folder.mkdir()
    (folder / "index.md").write_text('---\nokf_version: "0.2"\n---\n# Index', encoding="utf-8")
    assert "index_frontmatter" in codes(validate_bundle(bundle))


@pytest.mark.parametrize("link", [
    "[Missing](absent.md)",
    "[Missing][ref]\n\n[ref]: absent.md",
])
def test_broken_inline_and_reference_links_fail_project_checks(bundle, link):
    path = bundle / CONCEPT_FILES[0]
    path.write_text(path.read_text(encoding="utf-8") + "\n" + link, encoding="utf-8")
    result = validate_bundle(bundle)
    assert not result.valid
    assert result.format_valid  # Broken links are tolerated by general OKF.
    assert "link_missing" in codes(result)


def test_index_must_link_to_every_approved_concept(bundle):
    path = bundle / "index.md"
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(line for line in lines if "(quotation-pricing.md)" not in line),
                    encoding="utf-8")
    result = validate_bundle(bundle)
    assert result.format_valid and not result.valid
    assert "index_link_missing" in codes(result)


def test_bundle_root_and_percent_encoded_links_resolve(bundle):
    path = bundle / "index.md"
    body = path.read_text(encoding="utf-8")
    for name in CONCEPT_FILES:
        body = body.replace(f"({name})", f"(/{name})")
    (bundle / "extra note.md").write_text("---\ntype: Reference\n---\n# Extra\n", encoding="utf-8")
    path.write_text(body + "\n[Extra](extra%20note.md)\n", encoding="utf-8")
    assert validate_bundle(bundle).valid


def test_code_samples_are_not_treated_as_links(bundle):
    path = bundle / CONCEPT_FILES[0]
    path.write_text(path.read_text(encoding="utf-8") +
                    "\n```markdown\n[Example](absent.md)\n```\n", encoding="utf-8")
    assert validate_bundle(bundle).valid


def test_external_links_are_not_fetched(bundle, monkeypatch):
    import socket

    def no_network(*args, **kwargs):
        pytest.fail("Validator must not access the network")

    monkeypatch.setattr(socket, "socket", no_network)
    path = bundle / CONCEPT_FILES[0]
    path.write_text(path.read_text(encoding="utf-8") +
                    "\n[External](https://example.invalid/not-fetched)\n", encoding="utf-8")
    assert validate_bundle(bundle).valid


def test_internal_link_cannot_escape_the_bundle(bundle):
    (bundle.parent / "outside.md").write_text("outside", encoding="utf-8")
    path = bundle / CONCEPT_FILES[0]
    path.write_text(path.read_text(encoding="utf-8") + "\n[Outside](../outside.md)", encoding="utf-8")
    assert "link_outside_bundle" in codes(validate_bundle(bundle))


def test_validation_does_not_modify_bundle_files(bundle):
    def snapshot():
        return {p.relative_to(bundle).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in bundle.rglob("*") if p.is_file()}

    before = snapshot()
    assert validate_bundle(bundle).valid
    assert snapshot() == before


def test_cli_success_and_failure_exit_codes(bundle, capsys):
    assert main([str(bundle), "--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["ezstore_bundle_valid"] is True
    assert output["parsed_documents"] == 5
    (bundle / "index.md").unlink()
    assert main([str(bundle), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["ezstore_bundle_valid"] is False
