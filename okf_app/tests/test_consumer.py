import hashlib
import shutil
from pathlib import Path

import pytest

from okf_knowledge.consumer import InvalidBundle, KnowledgeConsumer

BUNDLE = Path(__file__).resolve().parents[1] / "bundle"
CASES = [
    ("What is the default pricing factor for a VIP customer?", "quotation-pricing.md", "0.80"),
    ("What is the difference between a draft and published quotation?", "quotation-lifecycle.md", "draft"),
    ("Can a published quotation be modified?", "quotation-lifecycle.md", "cannot be modified"),
    ("How can a quotation relate to an order?", "quotation-order-relationship.md", "quotation_id = null"),
]


@pytest.fixture
def bundle(tmp_path):
    return Path(shutil.copytree(BUNDLE, tmp_path / "bundle"))


@pytest.mark.parametrize(("question", "document", "expected"), CASES)
def test_required_questions_return_loaded_knowledge(bundle, question, document, expected):
    consumer = KnowledgeConsumer(bundle)
    answer = consumer.answer(question)
    assert answer.supported
    assert answer.document == document
    assert expected in answer.markdown
    assert answer.sources
    # Every non-empty answer line comes from the actual supplying document.
    original_lines = set(consumer.document(document).body.splitlines())
    assert all(line in original_lines for line in answer.markdown.splitlines() if line)


def test_changed_fixture_value_is_loaded_without_hardcoded_answer(bundle):
    consumer = KnowledgeConsumer(bundle)
    path = bundle / "quotation-pricing.md"
    path.write_text(path.read_text(encoding="utf-8").replace("`0.80`", "`0.73`"), encoding="utf-8")
    answer = consumer.answer(CASES[0][0])
    assert "`0.73`" in answer.markdown
    assert "`0.80`" not in answer.markdown


def test_published_answer_is_extracted_from_fixture_text(bundle):
    consumer = KnowledgeConsumer(bundle)
    path = bundle / "quotation-lifecycle.md"
    path.write_text(path.read_text(encoding="utf-8").replace(
        "it cannot be modified, deleted, or published again.", "fixture-only source marker."
    ), encoding="utf-8")
    answer = consumer.answer(CASES[2][0])
    assert "fixture-only source marker" in answer.markdown
    assert "cannot be modified" not in answer.markdown


@pytest.mark.parametrize("question", [
    "What is the weather?", "What is a VIP customer's credit limit?",
    "How many quotations are there?", "What is the current credit score of customer Stark?",
    "What is customer Stark's credit score?", "What is the tax rate?",
])
def test_unsupported_and_live_questions_are_not_fabricated(bundle, question):
    answer = KnowledgeConsumer(bundle).answer(question)
    assert not answer.supported
    assert answer.document is None and not answer.sources


def test_write_request_is_not_executed(bundle):
    answer = KnowledgeConsumer(bundle).answer("Please modify quotation QT-20260330-001.")
    assert not answer.supported
    assert "read-only" in answer.markdown


def test_four_concepts_discovered_and_read(bundle):
    consumer = KnowledgeConsumer(bundle)
    concepts = consumer.concepts()
    assert len(concepts) == 4
    for concept in concepts:
        assert consumer.document(concept["document"]).metadata["type"] == "Reference"


def test_invalid_bundle_fails_closed_on_next_request(bundle):
    consumer = KnowledgeConsumer(bundle)
    (bundle / "index.md").unlink()
    with pytest.raises(InvalidBundle):
        consumer.answer(CASES[0][0])


def test_consumer_does_not_modify_files_or_access_network(bundle, monkeypatch):
    import socket

    def forbidden(*args, **kwargs):
        pytest.fail("Knowledge lookup must not access the network")

    def snapshot():
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in bundle.glob("*.md")}

    before = snapshot()
    monkeypatch.setattr(socket, "socket", forbidden)
    consumer = KnowledgeConsumer(bundle)
    for question, _, _ in CASES:
        assert consumer.answer(question).supported
    assert snapshot() == before
