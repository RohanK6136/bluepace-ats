"""Applicant Match configuration (config/*.yaml, taxonomy.json) and prompt library, loaded once per process."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from app.core.hashing import canonical_json, sha256_hex
from app.llm.prompt_loader import PromptLibrary, PromptTemplate

FEATURE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = FEATURE_DIR / "config"
PROMPTS = PromptLibrary(FEATURE_DIR / "prompts")
PIPELINE_VERSION = "0.1.0"


@dataclass(frozen=True)
class TaxonomyEntry:
    label: str
    type: str
    aliases: tuple[str, ...]
    group: str | None


@dataclass(frozen=True)
class MatchPolicy:
    settings: dict[str, Any]
    negations: tuple[str, ...]
    protected_terms: tuple[str, ...]
    redaction: dict[str, Any]
    taxonomy: dict[str, TaxonomyEntry]  # folded label or alias → entry
    config_hash: str  # changes whenever any rule file changes; stored on every card

    def lookup(self, label: str) -> TaxonomyEntry | None:
        """Exact label/alias match, else the longest known skill named inside a short label
        ("Java development" → Java, "SQL databases" → SQL). Case-sensitive aliases only match exactly."""
        exact = self.taxonomy.get(fold(label))
        if exact or len(label.split()) > 3:  # "advanced Windows troubleshooting techniques" is not just Windows
            return exact
        from app.features.applicant_match.matcher import alias_pattern

        best: tuple[int, TaxonomyEntry] | None = None
        for entry in dict.fromkeys(self.taxonomy.values()):
            for alias in (entry.label, *entry.aliases):
                if alias.startswith("=") or (best and len(alias) <= best[0]):
                    continue
                if alias_pattern(alias).search(label):
                    best = (len(alias), entry)
        return best[1] if best else None


def fold(text: str) -> str:
    return " ".join(text.casefold().split())


@cache
def education_matchers() -> tuple[tuple[str, tuple[re.Pattern[str], ...]], ...]:
    """(level, patterns) from the highest level down; "=" marks a case-sensitive pattern."""
    pats = load_match_policy().settings["education_patterns"]
    levels: list[str] = load_match_policy().settings["education_levels"]
    out = []
    for lvl in reversed(levels):
        compiled = tuple(re.compile(r"(?<![A-Za-z])(?:" + p.lstrip("=") + r")(?![A-Za-z])",
                                    0 if p.startswith("=") else re.I) for p in pats.get(lvl, []))
        if compiled:
            out.append((lvl, compiled))
    return tuple(out)


@cache
def _generic_degree() -> re.Pattern[str]:
    alts = "|".join(load_match_policy().settings.get("education_generic_degree", []))
    return re.compile(r"(?<![A-Za-z])(?:" + alts + r")(?![A-Za-z])", re.I)


def education_levels_in(text: str) -> list[str]:
    """Every education level a text mentions, highest first. A bare "degree" counts as bachelor."""
    found = [lvl for lvl, pats in education_matchers() if any(p.search(text) for p in pats)]
    if not found and _generic_degree().search(text):
        found = ["bachelor"]
    return found


def _yaml(name: str) -> dict[str, Any]:
    return yaml.safe_load((CONFIG_DIR / name).read_text(encoding="utf-8")) or {}


def _strings(name: str, values: list[Any]) -> tuple[str, ...]:
    bad = [v for v in values if not isinstance(v, str)]
    if bad:  # e.g. an unquoted `no` that YAML read as False
        raise ValueError(f"config/{name}: every entry must be a quoted string; got {bad!r}")
    return tuple(values)


@cache
def load_match_policy() -> MatchPolicy:
    settings = _yaml("settings.yaml")
    negations = _yaml("negations.yaml")
    protected = _yaml("protected_terms.yaml")
    redaction = _yaml("redaction.yaml")
    raw_tax = json.loads((CONFIG_DIR / "taxonomy.json").read_text(encoding="utf-8"))
    taxonomy: dict[str, TaxonomyEntry] = {}
    entries = [TaxonomyEntry(label=e["label"], type=typ, aliases=tuple(e["aliases"]), group=e.get("group"))
               for kind, typ in (("skills", "skill"), ("certifications", "certification"), ("languages", "language"))
               for e in raw_tax.get(kind, [])]
    for entry in entries:  # labels first, so "DNS" is the DNS entry, not Networking (which lists dns as an alias)
        taxonomy.setdefault(fold(entry.label), entry)
    for entry in entries:
        for alias in entry.aliases:
            taxonomy.setdefault(fold(alias.lstrip("=")), entry)
    config_hash = sha256_hex(canonical_json({"settings": settings, "negations": negations, "protected": protected,
                                             "redaction": redaction, "taxonomy": raw_tax}))[:16]
    for key in ("personal_line_labels", "personal_line_starts", "address_labels", "not_a_name"):
        _strings("redaction.yaml", redaction.get(key, []))
    _strings("settings.yaml", settings["summary"]["verdict_words"])
    return MatchPolicy(settings=settings, negations=_strings("negations.yaml", negations.get("cues", [])),
                       protected_terms=_strings("protected_terms.yaml", protected.get("terms", [])),
                       redaction=redaction, taxonomy=taxonomy,
                       config_hash=config_hash)


def load_prompt(name: str) -> PromptTemplate:
    return PROMPTS.load(name)


def prompt_versions() -> dict[str, int]:
    return PROMPTS.versions()
