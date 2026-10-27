"""Read-only structural parsing and EZStore-specific bundle validation.

Missing required files and unresolved links are project errors, distinct from
OKF frontmatter errors. No external source URL is fetched or code executed.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import yaml
from markdown_it import MarkdownIt

CONCEPT_FILES = (
    "customer-knowledge.md",
    "quotation-pricing.md",
    "quotation-lifecycle.md",
    "quotation-order-relationship.md",
)
REQUIRED_FILES = ("index.md", *CONCEPT_FILES)


@dataclass(frozen=True)
class Issue:
    scope: str
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class Document:
    path: str
    metadata: dict[str, Any]
    body: str
    links: tuple[str, ...]


@dataclass
class ValidationResult:
    documents: dict[str, Document] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)

    @property
    def format_valid(self) -> bool:
        return not any(issue.scope == "okf" for issue in self.issues)

    @property
    def valid(self) -> bool:
        return not self.issues

    def summary(self) -> dict[str, Any]:
        return {
            "okf_structure_valid": self.format_valid,
            "ezstore_bundle_valid": self.valid,
            "parsed_documents": len(self.documents),
            "parsed_concepts": sum(
                Path(name).name not in {"index.md", "log.md"} for name in self.documents
            ),
            "issues": [asdict(issue) for issue in self.issues],
        }


class DocumentError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _frontmatter(text: str) -> tuple[dict[str, Any], str, bool]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, text, False
    end = next((n for n in range(1, len(lines)) if lines[n].strip() == "---"), None)
    if end is None:
        raise DocumentError("frontmatter_unclosed", "Missing closing frontmatter delimiter.")
    try:
        metadata = yaml.safe_load("".join(lines[1:end]))
    except yaml.YAMLError as exc:
        raise DocumentError("yaml_invalid", "Frontmatter is not safe, parseable YAML.") from exc
    if not isinstance(metadata, dict):
        raise DocumentError("yaml_not_mapping", "Frontmatter must be a YAML mapping.")
    return metadata, "".join(lines[end + 1:]), True


def _hrefs(tokens):
    for token in tokens:
        if token.type == "link_open":
            href = token.attrGet("href")
            if href is not None:
                yield href
        if token.children:
            yield from _hrefs(token.children)


def parse_document(path: Path, bundle_root: Path) -> Document:
    """Parse Markdown/YAML without changing the file or interpreting source URIs."""
    relative = path.relative_to(bundle_root).as_posix()
    metadata, body, has_frontmatter = _frontmatter(path.read_text(encoding="utf-8"))
    if path.name == "index.md":
        if has_frontmatter:
            if relative != "index.md" or set(metadata) != {"okf_version"}:
                raise DocumentError(
                    "index_frontmatter", "Only the root index may declare okf_version frontmatter."
                )
            if not isinstance(metadata["okf_version"], str) or not metadata["okf_version"].strip():
                raise DocumentError("index_version", "okf_version must be a non-empty string.")
    elif path.name == "log.md":
        if has_frontmatter:
            raise DocumentError("log_frontmatter", "Reserved log files have no frontmatter.")
    else:
        if not has_frontmatter:
            raise DocumentError("frontmatter_missing", "Concepts require YAML frontmatter.")
        kind = metadata.get("type")
        if not isinstance(kind, str) or not kind.strip():
            raise DocumentError("type_invalid", "Concept type must be a non-empty string.")
    # CommonMark parsing resolves both inline and reference-style Markdown links.
    tokens = MarkdownIt("commonmark").parse(body)
    return Document(relative, metadata, body, tuple(_hrefs(tokens)))


def _local_target(root: Path, document: str, href: str) -> Path | None:
    url = urlsplit(href)
    if url.scheme or url.netloc:
        return None
    target = unquote(url.path)
    if not target:
        return root / document
    if target.startswith("/"):
        return (root / target.lstrip("/")).resolve()
    return (root / document).parent.joinpath(target).resolve()


def validate_bundle(bundle_root: str | Path) -> ValidationResult:
    """Check required files, parse all Markdown, and resolve internal file targets."""
    root = Path(bundle_root).resolve()
    result = ValidationResult()

    def add(scope: str, code: str, name: str, message: str):
        result.issues.append(Issue(scope, code, name, message))

    for name in REQUIRED_FILES:
        if not (root / name).is_file():
            add("project", "file_missing", name, "Required Markdown file is missing.")
    for path in sorted(root.rglob("*.md")):
        name = path.relative_to(root).as_posix()
        if not path.resolve().is_relative_to(root):
            add("project", "path_outside_bundle", name, "Document resolves outside the bundle.")
            continue
        try:
            result.documents[name] = parse_document(path, root)
        except DocumentError as exc:
            add("okf", exc.code, name, str(exc))
        except (OSError, UnicodeError, ValueError) as exc:
            add("okf", "parse_failed", name, f"Document cannot be parsed ({type(exc).__name__}).")

    index_targets = set()
    for name, document in result.documents.items():
        for href in document.links:
            try:
                target = _local_target(root, name, href)
            except ValueError:
                add("project", "link_invalid", name, "Invalid internal link URI.")
                continue
            if target is None:
                continue
            if not target.is_relative_to(root):
                add("project", "link_outside_bundle", name, f"Internal link leaves bundle: {href}")
            elif not target.exists():
                add("project", "link_missing", name, f"Unresolved internal file target: {href}")
            elif name == "index.md":
                index_targets.add(target)
    if "index.md" in result.documents:
        for name in CONCEPT_FILES:
            if root / name not in index_targets:
                add("project", "index_link_missing", "index.md", f"Index must link to {name}.")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", nargs="?", type=Path,
                        default=Path(__file__).resolve().parents[1] / "bundle")
    parser.add_argument("--json", action="store_true", help="Print structured validation results.")
    args = parser.parse_args(argv)
    result = validate_bundle(args.bundle)
    if args.json:
        print(json.dumps(result.summary(), ensure_ascii=True, indent=2))
    else:
        print(f"OKF structure: {'PASS' if result.format_valid else 'FAIL'}")
        print(f"EZStore bundle: {'PASS' if result.valid else 'FAIL'}")
        print(f"Parsed {len(result.documents)} Markdown documents.")
        for issue in result.issues:
            print(f"{issue.scope}/{issue.code}: {issue.path}: {issue.message}")
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
