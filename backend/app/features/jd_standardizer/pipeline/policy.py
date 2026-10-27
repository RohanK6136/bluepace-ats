"""Loads policy/*.yaml and data/* once. Every tunable lives in those files or config.py."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import yaml

from app.features.jd_standardizer.promptlib import FEATURE_DIR

POLICY_DIR = FEATURE_DIR / "policy"
DATA_DIR = FEATURE_DIR / "data"


def _yaml(name: str) -> Any:
    return yaml.safe_load((POLICY_DIR / name).read_text(encoding="utf-8"))


def alias_key(text: str) -> str:
    """casefold, hyphens/underscores/slashes → space, collapse spaces."""
    t = re.sub(r"[-_/]+", " ", text.casefold())
    return re.sub(r"\s+", " ", t).strip()


@dataclass(frozen=True)
class BannedPattern:
    name: str
    regex: re.Pattern[str]
    allowed_if_in_source: bool


@dataclass(frozen=True)
class Policy:
    gap: dict[str, Any]
    alias_to_section: dict[str, str]
    company_about_re: re.Pattern[str]
    kv_keys: dict[str, str]
    chrome_res: tuple[re.Pattern[str], ...]
    cta_res: tuple[re.Pattern[str], ...]
    banned_words: dict[str, tuple[str, ...]]
    case_sensitive_words: dict[str, str]
    banned_patterns: tuple[BannedPattern, ...]
    allowed_acronyms: frozenset[str]
    legal_default: str
    legal_regions: dict[str, str]
    role_types: tuple[str, ...]
    role_type_aliases: dict[str, str]
    work_mode_aliases: dict[str, str]
    verbs: frozenset[str]
    standard_blocks: dict[str, str]

    def section_policy(self, section: str) -> dict[str, Any]:
        return self.gap["sections"].get(section, {})


@lru_cache
def load_policy() -> Policy:
    gap = _yaml("gap_policy.yaml")

    aliases = _yaml("section_aliases.yaml")
    alias_to_section: dict[str, str] = {}
    for section, names in aliases["sections"].items():
        for name in names:
            alias_to_section[re.sub(r"\s+", " ", name.casefold().replace(",", " ")).strip()] = section

    kv_raw = _yaml("kv_keys.yaml")
    kv_keys = {k.casefold(): kind for kind, keys in kv_raw.items() for k in keys}

    chrome = _yaml("chrome_patterns.yaml")
    banned = _yaml("banned_patterns.yaml")
    legal = _yaml("legal_regions.yaml")

    role_data = json.loads((DATA_DIR / "lookups" / "role_types.json").read_text(encoding="utf-8"))
    role_aliases = {alias_key(c): c for c in role_data["canonical"]}
    role_aliases.update({alias_key(a): c for a, c in role_data["aliases"].items()})
    mode_data = json.loads((DATA_DIR / "lookups" / "work_modes.json").read_text(encoding="utf-8"))
    mode_aliases = {alias_key(a): c for a, c in mode_data["aliases"].items()}

    verbs = frozenset(
        w.strip().casefold()
        for w in (DATA_DIR / "style" / "responsibility_verbs.txt").read_text(encoding="utf-8").splitlines()
        if w.strip()
    )
    blocks = {p.stem: p.read_text(encoding="utf-8").strip() for p in (DATA_DIR / "standard_blocks").glob("*.md")}

    return Policy(
        gap=gap,
        alias_to_section=alias_to_section,
        company_about_re=re.compile(aliases["patterns"]["company_about_regex"]),
        kv_keys=kv_keys,
        chrome_res=tuple(re.compile(p, re.I) for p in chrome["line_patterns"]),
        cta_res=tuple(re.compile(p, re.I) for p in chrome["cta_sentence_patterns"]),
        banned_words={cat: tuple(words) for cat, words in banned["banned_words"].items()},
        case_sensitive_words={w.casefold(): w for w in banned.get("case_sensitive_words", [])},
        banned_patterns=tuple(
            BannedPattern(p["name"], re.compile(p["regex"], re.I), bool(p.get("allowed_if_in_source")))
            for p in banned["patterns"]
        ),
        allowed_acronyms=frozenset(a.casefold() for a in banned.get("allowed_acronyms", [])),
        legal_default=legal["default"],
        legal_regions={k.upper(): v for k, v in (legal.get("regions") or {}).items()},
        role_types=tuple(role_data["canonical"]),
        role_type_aliases=role_aliases,
        work_mode_aliases=mode_aliases,
        verbs=verbs,
        standard_blocks=blocks,
    )
