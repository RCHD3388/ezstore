"""Deterministic question routing and text extraction from validated OKF files."""

import re
from dataclasses import dataclass
from pathlib import Path

from markdown_it import MarkdownIt

from .validator import CONCEPT_FILES, Document, validate_bundle

DEFAULT_BUNDLE = Path(__file__).resolve().parents[1] / "bundle"


class InvalidBundle(ValueError):
    pass


@dataclass(frozen=True)
class KnowledgeAnswer:
    question: str
    supported: bool
    markdown: str
    document: str | None = None
    title: str | None = None
    section: str | None = None
    sources: tuple = ()


def _section(document: Document, title: str) -> str:
    lines = document.body.splitlines()
    headings = []
    tokens = MarkdownIt("commonmark").parse(document.body)
    for index, token in enumerate(tokens):
        if token.type == "heading_open" and token.tag in {"h1", "h2"}:
            headings.append((tokens[index + 1].content, token.map[0]))
    for index, (name, start) in enumerate(headings):
        if name == title:
            end = headings[index + 1][1] if index + 1 < len(headings) else len(lines)
            return "\n".join(lines[start + 1:end]).strip()
    raise InvalidBundle(f"Required knowledge section is missing: {document.path} / {title}")


def _table_row(section: str, key: str) -> str:
    """Keep the original header, selected row, and explanatory text after a table."""
    lines = section.splitlines()
    table = [i for i, line in enumerate(lines) if line.lstrip().startswith("|")]
    selected = [i for i in table[2:]
                if lines[i].split("|")[1].strip().strip("`").casefold() == key]
    if len(table) < 3 or len(selected) != 1:
        raise InvalidBundle("The requested knowledge table row is missing or ambiguous.")
    return "\n".join([lines[table[0]], lines[table[1]], lines[selected[0]],
                      *lines[table[-1] + 1:]]).strip()


class KnowledgeConsumer:
    def __init__(self, bundle_root=DEFAULT_BUNDLE):
        self.bundle_root = Path(bundle_root)
        self._load()

    def _load(self):
        parsed = validate_bundle(self.bundle_root)
        if not parsed.valid:
            raise InvalidBundle("The local OKF bundle failed validation; no answer was generated.")
        return parsed.documents

    def concepts(self):
        documents = self._load()
        return [{"document": name, "title": documents[name].metadata.get("title", name),
                 "description": documents[name].metadata.get("description", "")}
                for name in CONCEPT_FILES]

    def document(self, name):
        if name not in CONCEPT_FILES:
            raise KeyError("Unknown bundle concept")
        return self._load()[name]

    def answer(self, question: str) -> KnowledgeAnswer:
        question = question.strip()
        documents = self._load()
        lowered = question.casefold()
        if re.search(r"^(?:please\s+)?(?:create|update|modify|delete|duplicate|convert|publish|remove)\b",
                     lowered):
            return KnowledgeAnswer(question, False,
                                   "This application is read-only. Ask a knowledge question instead.")
        if re.search(r"\b(?:current|today|latest|how many)\b|目前|今天|現在", lowered):
            return KnowledgeAnswer(question, False,
                                   "Live customer and transaction values are outside this static knowledge bundle.")

        target = None
        row = None
        if re.search(r"(?:pricing\s+factor|default\s+factor|報價因子)", lowered):
            target = ("quotation-pricing.md", "Default pricing factors")
            level = re.search(r"\b(vip|standard|new)\b", lowered)
            row = level.group(1) if level else None
        elif ("quotation" in lowered and "order" in lowered
              and re.search(r"relat|link|standalone|quotation_id", lowered)):
            target = ("quotation-order-relationship.md", None)
        elif "published" in lowered and ("draft" in lowered or re.search(r"modif|edit|delet", lowered)):
            target = ("quotation-lifecycle.md", "Draft and published")
            if "draft" not in lowered:
                row = "published"
        elif re.search(r"publish|publication", lowered) and re.search(r"revers|unpublish", lowered):
            target = ("quotation-lifecycle.md", "Publishing")
        elif re.search(r"customer (?:levels?|attributes?|fields)|credit score range", lowered):
            target = ("customer-knowledge.md", "Attributes and levels")
        if target is None:
            return KnowledgeAnswer(question, False,
                                   "This question is outside the loaded OKF knowledge. Choose a suggested question or read a concept.")

        name, heading = target
        document = documents[name]
        text = _section(document, heading) if heading else document.body.strip()
        if row:
            text = _table_row(text, row)
        return KnowledgeAnswer(
            question, True, text, name,
            document.metadata.get("title", name), heading,
            tuple(document.metadata.get("sources", [])),
        )
