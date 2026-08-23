"""Scan public surfaces for private corpus facts before they become irreversible.

The repository cannot contain the private names themselves, so this module combines
generic measurement/path rules with an optional local terms file.  Release callers must
require that file; ordinary contributors can still run the generic checks without access
to private infrastructure.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


_TEXT_SUFFIXES = {
    "",
    ".cfg",
    ".csv",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".rst",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
_LOCAL_PATH_PATTERN = re.compile(
    "(?:/" + "Users/[^/\\s]+/|/" + "Volumes/[^/\\s]+/|[A-Za-z]:\\\\Users\\\\[^\\\\\\s]+\\\\)"
)
_CORPUS_CONTEXT_PATTERN = re.compile(
    r"(?:\breal\b|\bproduction\b|\bprivate\b|\bin practice\b|"
    r"真实|生产|私有|语料|实测)",
    re.IGNORECASE,
)
_COUNT_PATTERN = re.compile(
    r"(?:\b\d[\d,]*(?:\.\d+)?\s*(?:of\s+\d[\d,]*\s*)?"
    r"(?:tasks?|statements?|tables?|columns?|edges?|gaps?|reports?|files?|ddls?|"
    r"任务|语句|表|列|边|缺口|报告|文件)\b|"
    r"\b(?:dozens|hundreds|thousands|millions|tens\s+of\s+thousands)\s+(?:of\s+)?"
    r"(?:tasks?|statements?|tables?|columns?|edges?|gaps?|reports?|files?)\b|"
    r"(?:数十|数百|数千|数万)(?:个|条|张|份)?(?:任务|语句|表|列|边|缺口|报告|文件))",
    re.IGNORECASE,
)
_LARGE_COUNT_PATTERN = re.compile(
    r"\b(?:[1-9]\d{2,}|\d{1,3}(?:,\d{3})+)\s*(?:-\s*)?"
    r"(?:tasks?|statements?|tables?|columns?|edges?|gaps?|reports?|files?|ddls?)\b",
    re.IGNORECASE,
)
_RATIO_PATTERN = re.compile(
    r"\b\d[\d,]*\s+(?:of|/)\s+\d[\d,]*\s+"
    r"(?:tasks?|statements?|tables?|columns?|edges?|gaps?|reports?|files?)\b",
    re.IGNORECASE,
)
_PER_ITEM_MEASUREMENT_PATTERN = re.compile(
    r"(?:\b(?:task|statement|artifact|output)\b|任务|语句|产物|输出)"
    r"[\s\S]{0,160}?"
    r"(?:\b\d+(?:\.\d+)?\s*(?:kb|mb|gb|seconds?|minutes?|calls?)\b|"
    r"\b(?:megabytes?|gigabytes?)\b|\d+(?:\.\d+)?\s*(?:秒|分钟|次调用))",
    re.IGNORECASE,
)
_MAGNITUDE_PATTERN = re.compile(
    r"\b(?:dozens|hundreds|thousands|millions|tens\s+of\s+thousands|"
    r"megabytes?|gigabytes?)\b|(?:数十|数百|数千|数万)(?:个|条|张|份)?",
    re.IGNORECASE,
)
_MAGNITUDE_ASSET_PATTERN = re.compile(
    r"\b(?:dozens|hundreds|thousands|millions|tens\s+of\s+thousands)"
    r"(?:\s+of)?(?:\s+[a-z-]+){0,3}\s+"
    r"(?:tasks?|statements?|tables?|columns?|edges?|gaps?|reports?|files?)\b|"
    r"(?:数十|数百|数千|数万)(?:个|条|张|份)?(?:\S{0,8})"
    r"(?:任务|语句|表|列|边|缺口|报告|文件)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Finding:
    source: str
    line: int
    rule: str
    excerpt: str

    def render(self) -> str:
        return f"{self.source}:{self.line}: {self.rule}: {self.excerpt}"


def _paragraphs(text: str) -> Iterable[tuple[int, str]]:
    lines = text.splitlines()
    start = 0
    buffered: list[str] = []
    buffered_length = 0
    for index, line in enumerate(lines, start=1):
        if line.strip():
            # Markdown paragraphs are normally wrapped over a few lines.  Source code can
            # run for hundreds of lines without a blank separator; treating that as prose
            # creates matches by joining unrelated identifiers and regular expressions.
            if buffered and (len(buffered) >= 5 or buffered_length + len(line) > 800):
                yield start, " ".join(buffered)
                buffered = []
                buffered_length = 0
            if not buffered:
                start = index
            buffered.append(line.strip())
            buffered_length += len(line)
            continue
        if buffered:
            yield start, " ".join(buffered)
            buffered = []
            buffered_length = 0
    if buffered:
        yield start, " ".join(buffered)


def _excerpt(value: str, *, limit: int = 180) -> str:
    compact = " ".join(value.split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def scan_text(
    text: str,
    *,
    source: str,
    private_terms: Iterable[str] = (),
) -> list[Finding]:
    findings: list[Finding] = []
    terms = [term.casefold() for term in private_terms if term.strip()]
    for line_number, paragraph in _paragraphs(text):
        folded = paragraph.casefold()
        if _LOCAL_PATH_PATTERN.search(paragraph):
            findings.append(
                Finding(source, line_number, "local-absolute-path", _excerpt(paragraph))
            )
        if any(term in folded for term in terms):
            findings.append(
                Finding(source, line_number, "private-term", _excerpt(paragraph))
            )
        has_context = _CORPUS_CONTEXT_PATTERN.search(paragraph)
        has_quantity = _COUNT_PATTERN.search(paragraph) or _MAGNITUDE_PATTERN.search(
            paragraph
        )
        if has_context and has_quantity:
            findings.append(
                Finding(source, line_number, "private-corpus-measurement", _excerpt(paragraph))
            )
        if _LARGE_COUNT_PATTERN.search(paragraph) or _RATIO_PATTERN.search(paragraph):
            findings.append(
                Finding(source, line_number, "asset-count", _excerpt(paragraph))
            )
        if _MAGNITUDE_ASSET_PATTERN.search(paragraph):
            findings.append(
                Finding(source, line_number, "asset-magnitude", _excerpt(paragraph))
            )
        if _PER_ITEM_MEASUREMENT_PATTERN.search(paragraph):
            findings.append(
                Finding(source, line_number, "per-item-measurement", _excerpt(paragraph))
            )
    return _deduplicate(findings)


def _deduplicate(findings: Iterable[Finding]) -> list[Finding]:
    return list(dict.fromkeys(findings))


def load_private_terms(path: Path | None, *, required: bool = False) -> list[str]:
    if path is None:
        if required:
            raise ValueError("a private terms file is required for release scanning")
        return []
    if not path.is_file():
        raise ValueError(f"private terms file does not exist: {path}")
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _decode_text(data: bytes) -> str | None:
    if b"\x00" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def scan_paths(paths: Iterable[Path], *, private_terms: Iterable[str]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        if not path.is_file() or path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        text = _decode_text(path.read_bytes())
        if text is not None:
            findings.extend(scan_text(text, source=path.as_posix(), private_terms=private_terms))
    return findings


def scan_text_inputs(
    paths: Iterable[Path], *, private_terms: Iterable[str]
) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        if path == Path("-"):
            findings.extend(
                scan_text(sys.stdin.read(), source="<stdin>", private_terms=private_terms)
            )
        else:
            findings.extend(scan_paths([path], private_terms=private_terms))
    return findings


def tracked_and_unignored_files(root: Path) -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [root / value.decode("utf-8") for value in completed.stdout.split(b"\x00") if value]


def scan_tree(root: Path, *, private_terms: Iterable[str]) -> list[Finding]:
    return scan_paths(tracked_and_unignored_files(root), private_terms=private_terms)


def scan_commits(
    root: Path,
    base: str,
    head: str,
    *,
    private_terms: Iterable[str],
) -> list[Finding]:
    completed = subprocess.run(
        ["git", "log", f"{base}..{head}", "--format=%H%n%B%x00"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    findings: list[Finding] = []
    for record in completed.stdout.split(b"\x00"):
        text = _decode_text(record)
        if not text or not text.strip():
            continue
        sha, _, body = text.lstrip().partition("\n")
        findings.extend(
            scan_text(body, source=f"commit:{sha.strip()}", private_terms=private_terms)
        )
    return findings


def _archive_text_members(path: Path) -> Iterable[tuple[str, bytes]]:
    if path.suffix == ".whl" or path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if not name.endswith("/"):
                    yield name, archive.read(name)
        return
    if path.name.endswith(".tar.gz"):
        with tarfile.open(path) as archive:
            for member in archive.getmembers():
                if member.isfile():
                    extracted = archive.extractfile(member)
                    if extracted is not None:
                        yield member.name, extracted.read()
        return
    raise ValueError(f"unsupported archive: {path}")


def scan_archives(
    paths: Iterable[Path], *, private_terms: Iterable[str]
) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        for member_name, data in _archive_text_members(path):
            text = _decode_text(data)
            if text is not None:
                findings.extend(
                    scan_text(
                        text,
                        source=f"{path.as_posix()}!{member_name}",
                        private_terms=private_terms,
                    )
                )
    return findings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-terms-file", type=Path)
    parser.add_argument("--require-private-terms", action="store_true")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    tree = subparsers.add_parser("tree")
    tree.add_argument("root", nargs="?", type=Path, default=Path.cwd())

    commits = subparsers.add_parser("commits")
    commits.add_argument("base")
    commits.add_argument("head", nargs="?", default="HEAD")
    commits.add_argument("--root", type=Path, default=Path.cwd())

    text = subparsers.add_parser("text")
    text.add_argument("paths", nargs="+", type=Path)

    archive = subparsers.add_parser("archive")
    archive.add_argument("paths", nargs="+", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        terms = load_private_terms(
            args.private_terms_file, required=args.require_private_terms
        )
        if args.mode == "tree":
            findings = scan_tree(args.root.resolve(), private_terms=terms)
        elif args.mode == "commits":
            findings = scan_commits(
                args.root.resolve(), args.base, args.head, private_terms=terms
            )
        elif args.mode == "text":
            findings = scan_text_inputs(args.paths, private_terms=terms)
        else:
            findings = scan_archives(args.paths, private_terms=terms)
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        print(f"private surface scan failed: {error}", file=sys.stderr)
        return 2

    for finding in findings:
        print(finding.render(), file=sys.stderr)
    if findings:
        print(f"private surface scan found {len(findings)} issue(s)", file=sys.stderr)
        return 1
    print("private surface scan passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
