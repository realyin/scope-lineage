"""``domain-profile check``: hold a ``domain-profile/1`` draft to its evidence.

Every entry of the draft -- each suffix, each word -- must be grounded, and must have a
line in the reasons file's 「已写入」 section:

* a suffix is grounded by the evidence's ``incremental`` suggestion, or by a person's
  ``accept`` in a ``domain-profile-confirmations/1`` file; ``full`` only by the latter,
  because the evidence never suggests it;
* a word is grounded when the rule its downstream command matches it with hits at
  least one entry of the evidence's material: check 12's word rule for a qualifier
  (:func:`.checks_documented.qualifier_hits`), the concept layer's vote for an
  ``event`` / ``entity`` / ``summary`` word (:func:`..render.concepts.word_hint_hits`),
  ``endswith`` for a measure suffix and a substring for a filter word. A word that
  passes here is one the downstream command can use. An ``accept`` never grounds a word.

The format is read by :func:`..domain_profile.parse_domain_profile`, the reader every
command's ``--domain-profile`` goes through; its first error is the only one reported.
Grounding errors are all listed. Hints (a suggested suffix left out, a word that adds no
hit, a repeated word, stale evidence) never fail the check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..domain_profile import (
    CONCEPT_WORD_KINDS,
    CONVENTION_KINDS,
    DomainProfileError,
    parse_domain_profile,
)
from ..render.concepts import builtin_concept_words, word_hint_hits
from .checks_documented import QUALIFIER_TERMS, qualifier_hits
from .profile_evidence import EVIDENCE_FORMAT, SUGGEST_INCREMENTAL, material_texts

CONFIRMATIONS_FORMAT = "domain-profile-confirmations/1"
_CONFIRMATION_KEYS = ("doc_format", "confirmed_by", "confirmed_at", "entries")
_ENTRY_KEYS = ("key", "value", "decision", "note")
_DECISIONS = ("accept", "reject")
QUALIFIER_KEY = "qualifier_terms"
KEY_PATHS = (
    *(f"table_name_convention.{kind}" for kind in CONVENTION_KINDS),
    QUALIFIER_KEY,
    *(f"concept_words.{kind}" for kind in CONCEPT_WORD_KINDS),
)
_VOTE_KINDS = ("event", "entity", "summary")

_REASON_LINE = re.compile(r"^\s*[-*+]\s*`([^`]+)`\s*`([^`]+)`\s*[:：]")
_HEADING = re.compile(r"^\s*#+\s*(.*)$")


class EvidenceError(ValueError):
    """An evidence file that is not ``domain-profile-evidence/1``."""


@dataclass
class CheckResult:
    errors: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    entries: int = 0


@dataclass
class Reasons:
    written: set[tuple[str, str]] = field(default_factory=set)
    pending: set[tuple[str, str]] = field(default_factory=set)


def current_version() -> str:
    try:
        from importlib.metadata import version

        return version("scope-lineage")
    except Exception:  # noqa: BLE001 - a source checkout without metadata has no version
        return "unknown (source checkout)"


def _entry(key: str, value: str) -> tuple[str, str]:
    """A ``(key path, value)`` pair as compared: a suffix lower-cased, a word stripped."""
    value = str(value).strip()
    return key, value.lower() if key.startswith("table_name_convention.") else value


def parse_reasons(text: str) -> Reasons:
    """The ``(key path, value)`` of every reason line, by section (「已写入」 / 「待确认」)."""
    reasons, section = Reasons(), None
    for line in str(text or "").splitlines():
        heading = _HEADING.match(line)
        if heading:
            title = heading.group(1)
            section = ("written" if "已写入" in title else "pending" if "待确认" in title
                       else None)
            continue
        match = _REASON_LINE.match(line)
        if match and section:
            getattr(reasons, section).add(_entry(match.group(1).strip(), match.group(2)))
    return reasons


def draft_entries(document: dict) -> list[tuple[str, str]]:
    """Every ``(key path, value)`` of a profile that parses, in file order, repeats kept."""
    found = [(QUALIFIER_KEY, word) for word in document.get(QUALIFIER_KEY) or []]
    for section, kinds in (("table_name_convention", CONVENTION_KINDS),
                           ("concept_words", CONCEPT_WORD_KINDS)):
        values = document.get(section) or {}
        found += [(f"{section}.{kind}", value) for kind in kinds for value in values.get(kind) or []]
    return [_entry(key, value) for key, value in found]


def confirmation_errors(document) -> list[str]:
    """What makes a confirmations document unusable; empty when it is well-formed."""
    if not isinstance(document, dict):
        return ["confirmed: top level is not an object"]
    errors = []
    if document.get("doc_format") != CONFIRMATIONS_FORMAT:
        errors.append(f"confirmed: doc_format must be {CONFIRMATIONS_FORMAT!r}")
    unknown = sorted(set(document) - set(_CONFIRMATION_KEYS))
    if unknown:
        errors.append(f"confirmed: unknown key(s): {', '.join(unknown)}")
    for name in ("confirmed_by", "confirmed_at"):
        if not (isinstance(document.get(name), str) and document[name].strip()):
            errors.append(f"confirmed: {name} must be a non-empty string")
    entries = document.get("entries")
    if not isinstance(entries, list):
        return errors + ["confirmed: entries must be a list"]
    for index, entry in enumerate(entries):
        errors += _confirmation_entry_errors(index, entry)
    return errors


def _confirmation_entry_errors(index: int, entry) -> list[str]:
    where = f"confirmed: entries[{index}]"
    if not isinstance(entry, dict):
        return [f"{where} is not an object"]
    errors = []
    unknown = sorted(set(entry) - set(_ENTRY_KEYS))
    if unknown:
        errors.append(f"{where}: unknown key(s): {', '.join(unknown)}")
    if entry.get("key") not in KEY_PATHS:
        errors.append(f"{where}: key must be one of {', '.join(KEY_PATHS)}")
    if not (isinstance(entry.get("value"), str) and entry["value"].strip()):
        errors.append(f"{where}: value must be a non-empty string")
    if entry.get("decision") not in _DECISIONS:
        errors.append(f"{where}: decision must be accept or reject")
    if "note" in entry and not isinstance(entry["note"], str):
        errors.append(f"{where}: note must be a string")
    return errors


def check_format(document) -> list[str]:
    try:
        parse_domain_profile(document)
    except DomainProfileError as error:
        return [str(error)]
    return []


def check_profile(document, reasons_text: str, evidence: dict, confirmed=None) -> CheckResult:
    """Errors and hints of one draft against its evidence, reasons and confirmations."""
    if not isinstance(evidence, dict) or evidence.get("doc_format") != EVIDENCE_FORMAT:
        raise EvidenceError(f"--evidence is not a {EVIDENCE_FORMAT} document")
    result = CheckResult(errors=check_format(document))
    if result.errors:
        return result
    raw = draft_entries(document)
    entries = list(dict.fromkeys(raw))
    result.entries = len(entries)
    accepted, rejected = set(), set()
    if confirmed is not None:
        problems = confirmation_errors(confirmed)
        if problems:
            result.errors += problems
            return result
        for item in confirmed["entries"]:
            pair = _entry(item["key"], item["value"])
            (accepted if item["decision"] == "accept" else rejected).add(pair)
    texts = material_texts(evidence)
    suggested = {str(item.get("suffix")).lower() for item in evidence.get("suffixes") or []
                 if item.get("suggestion") == SUGGEST_INCREMENTAL}
    for key, value in entries:
        problem = _ground(key, value, texts, suggested, accepted)
        if problem:
            result.errors.append(problem)
    result.errors += _reason_errors(entries, parse_reasons(reasons_text))
    result.errors += _confirmation_match_errors(entries, accepted, rejected)
    result.hints += _hints(raw, entries, texts, suggested, evidence)
    return result


def _ground(key, value, texts, suggested, accepted) -> str | None:
    """Why one entry has no ground, or None."""
    where = f"`{key}` `{value}`"
    if key.startswith("table_name_convention."):
        if (key, value) in accepted:
            return None
        if key.endswith(".incremental"):
            return None if value in suggested else (
                f"没有依据：{where}——证据没有建议这个后缀为 incremental，confirmed.json 里也没有"
                f"这一条的 accept")
        return (f"没有依据：{where}——工具从不直接建议 full，需要 confirmed.json 里有这一条的 "
                f"accept")
    if _grounded_word(key, value, texts):
        return None
    tail = "（confirmed.json 的 accept 不放行词）" if (key, value) in accepted else ""
    return f"没有依据：{where}——按下游的匹配规则，在证据材料里一条也命中不了，这个词下游匹配不到{tail}"


def _matches(key: str, word: str, text: str) -> bool:
    kind = key.split(".", 1)[-1]
    if key == QUALIFIER_KEY:
        return bool(qualifier_hits(text, (word,)))
    if kind in _VOTE_KINDS:
        return word_hint_hits(word, text)
    if kind == "measure_suffixes":
        return text.endswith(word)
    return word in text


def _texts_for(key: str, texts: dict) -> list[str]:
    return texts["qualifier"] if key == QUALIFIER_KEY else texts["concept"]


def _grounded_word(key: str, word: str, texts: dict) -> bool:
    return any(_matches(key, word, text) for text in _texts_for(key, texts))


def _reason_errors(entries, reasons: Reasons) -> list[str]:
    return [
        f"缺理由：`{key}` `{value}` 在草稿里，理由文件「已写入」一节没有对应的行"
        for key, value in entries if (key, value) not in reasons.written
    ]


def _confirmation_match_errors(entries, accepted, rejected) -> list[str]:
    present = set(entries)
    errors = [f"confirmed.json 里 accept 的 `{key}` `{value}` 不在草稿里"
              for key, value in sorted(accepted - present)]
    errors += [f"confirmed.json 里 reject 的 `{key}` `{value}` 出现在草稿里"
               for key, value in sorted(rejected & present)]
    return errors


def _hints(raw, entries, texts, suggested, evidence) -> list[str]:
    hints = []
    present = set(entries)
    for suffix in sorted(suggested):
        if ("table_name_convention.incremental", suffix) not in present:
            hints.append(f"证据建议 `{suffix}` 为 incremental，草稿里没写")
    seen: set = set()
    for pair in raw:
        if pair in seen:
            hints.append(f"重复：`{pair[0]}` `{pair[1]}` 在草稿里写了不止一次")
        seen.add(pair)
    builtin = _builtin_words()
    for key, value in entries:
        if key.startswith("table_name_convention.") or not _grounded_word(key, value, texts):
            continue
        if _adds_no_hit(key, value, texts, builtin.get(key, ())):
            hints.append(f"不生效：`{key}` `{value}` 命中的注释，内置词已经全部命中（等于重复）")
    inputs = evidence.get("inputs") or {}
    version = current_version()
    if inputs.get("tool_version") and inputs["tool_version"] != version:
        hints.append(f"证据由工具 {inputs['tool_version']} 生成，当前是 {version}：可能过期，"
                     f"考虑重新生成")
    return hints


def _builtin_words() -> dict[str, tuple[str, ...]]:
    words = {f"concept_words.{kind}": tuple(found) for kind, found in builtin_concept_words().items()}
    words[QUALIFIER_KEY] = QUALIFIER_TERMS
    return words


def _adds_no_hit(key: str, word: str, texts: dict, builtin: tuple[str, ...]) -> bool:
    """Whether the texts hit with the word added are exactly those the built-in words hit."""
    pool = _texts_for(key, texts)
    if key == QUALIFIER_KEY:
        before = {text for text in pool if qualifier_hits(text, builtin)}
        after = {text for text in pool if qualifier_hits(text, (*builtin, word))}
        return before == after
    before = {text for text in pool if any(_matches(key, other, text) for other in builtin)}
    return all(text in before for text in pool if _matches(key, word, text))


def stale_hint(evidence: dict, digest: str) -> str | None:
    recorded = (evidence.get("inputs") or {}).get("lineage_digest")
    if recorded and recorded != digest:
        return "证据过期：--lineage 的内容摘要与证据记下的不同，重新运行 domain-profile evidence"
    return None
