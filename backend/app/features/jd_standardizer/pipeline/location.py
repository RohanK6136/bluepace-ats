"""Location parsing behind a LocationResolver interface (platform tables can replace pycountry later)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Protocol

import pycountry

from app.features.jd_standardizer.pipeline.policy import Policy
from app.features.jd_standardizer.pipeline.textutil import canonical_work_modes, strip_marker

MODE_WORD_RE = re.compile(r"\b(remote|hybrid|on-?site|in-office|work from home|wfh)\b", re.I)
COUNTRY_ALIASES = {
    "usa": "US", "us": "US", "u.s.": "US", "u.s.a.": "US", "u.s": "US", "united states of america": "US",
    "america": "US", "uk": "GB", "u.k.": "GB", "england": "GB", "great britain": "GB", "britain": "GB",
    "scotland": "GB", "wales": "GB", "uae": "AE", "u.a.e.": "AE", "south korea": "KR", "korea": "KR",
    "russia": "RU", "vietnam": "VN", "czech republic": "CZ", "holland": "NL", "turkey": "TR",
    "taiwan": "TW", "iran": "IR", "bolivia": "BO", "venezuela": "VE", "tanzania": "TZ", "laos": "LA",
}
MAX_CITY_WORDS = 4
REGION_TYPES = {"State", "Province"}


class LocationResolver(Protocol):
    def country(self, text: str) -> tuple[str, str] | None: ...
    def state(self, iso2: str, text: str, region_only: bool = False) -> str | None: ...
    def city(self, iso2: str, text: str) -> str | None: ...


def _country_name(c: object) -> str:
    return getattr(c, "common_name", None) or c.name  # type: ignore[attr-defined]


class PycountryResolver:
    def country(self, text: str) -> tuple[str, str] | None:
        t = text.strip().strip(".").strip()
        if not t:
            return None
        alias = COUNTRY_ALIASES.get(t.casefold())
        if alias:
            c = pycountry.countries.get(alpha_2=alias)
            return (c.alpha_2, _country_name(c)) if c else None
        if len(t) <= 3 and not t.isupper():  # avoid "in", "the", …
            return None
        try:
            c = pycountry.countries.lookup(t)
        except LookupError:
            return None
        return c.alpha_2, _country_name(c)

    def state(self, iso2: str, text: str, region_only: bool = False) -> str | None:
        """`region_only`: accept only states/provinces, not city-level subdivisions (Paris, Tokyo, Delhi, Berlin)."""
        t = _fold(text)
        for sub in _subdivisions(iso2):
            if region_only and sub.type not in REGION_TYPES:
                continue
            code = sub.code.split("-", 1)[-1].casefold()
            if t == _fold(sub.name):
                # keep the recruiter's spelling when ISO uses diacritics ("Maharashtra", not "Mahārāshtra")
                return sub.name if sub.name.isascii() else " ".join(text.split())
            if len(t) <= 3 and t == code:
                return sub.name
        return None

    def city(self, iso2: str, text: str) -> str | None:
        t = " ".join(text.split())
        return t if t and len(t.split()) <= MAX_CITY_WORDS else None


def _fold(text: str) -> str:
    """Case- and accent-insensitive key: "Mahārāshtra" and "Maharashtra" compare equal."""
    decomposed = unicodedata.normalize("NFKD", text.strip())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


@lru_cache(maxsize=64)
def _subdivisions(iso2: str) -> tuple:
    return tuple(pycountry.subdivisions.get(country_code=iso2) or ())


DEFAULT_RESOLVER = PycountryResolver()


@dataclass
class LocationParse:
    country: tuple[str, str] | None = None
    state: str | None = None
    city: str | None = None
    modes: list[str] = field(default_factory=list)


def _parse_place(seg: str, resolver: LocationResolver) -> LocationParse | None:
    parts = [p.strip(" .;|") for p in seg.split(",") if p.strip(" .;|")]
    if not parts:
        return None
    # "City, ST" with a US state code ("San Francisco, CA") — prefer the US state over a country code
    if len(parts) >= 2 and len(parts[-1]) == 2 and parts[-1].isupper():
        us_state = resolver.state("US", parts[-1])
        if us_state:
            us = resolver.country("US")
            return LocationParse(country=us, state=us_state, city=resolver.city("US", parts[-2]))
    country = resolver.country(parts[-1])
    if not country:
        return None
    rest = parts[:-1]
    state = None
    if rest:  # "Pune, Maharashtra, India" is city + state; a lone "Illinois, USA" is a state, "Paris, France" a city
        state = resolver.state(country[0], rest[-1], region_only=len(rest) == 1)
        if state:
            rest = rest[:-1]
    city = resolver.city(country[0], rest[-1]) if rest else None
    return LocationParse(country=country, state=state, city=city)


US_CITY_STATE_RE = re.compile(r"([A-Za-z][A-Za-z .'-]*?)\s*(?:,|\s-\s)\s*([A-Z]{2})\b")
LIST_SEPARATORS = " ,;/|&"


def _us_city_state_list(s: str, resolver: LocationResolver) -> LocationParse | None:
    """One or more "City, ST" / "City - ST" items with US state codes ("Chicago - IL, Peoria - IL").

    Checked before country lookup so a state code is never read as a country (IL = Israel, IN = India).
    Several cities → no single city; the state is kept only when all items share it.
    """
    items = list(US_CITY_STATE_RE.finditer(s))
    if not items:
        return None
    leftover = US_CITY_STATE_RE.sub("", s)
    leftover = re.sub(r"\b(and|or)\b", "", leftover, flags=re.I)
    if leftover.strip(LIST_SEPARATORS + "."):
        return None  # other text around the items: not a plain list, let the general parser decide
    states = [resolver.state("US", m.group(2)) for m in items]
    if not all(states):
        return None
    cities = list(dict.fromkeys(" ".join(m.group(1).split()) for m in items))
    return LocationParse(country=resolver.country("US"), state=states[0] if len(set(states)) == 1 else None,
                         city=resolver.city("US", cities[0]) if len(cities) == 1 else None)


def parse_location(text: str, policy: Policy, resolver: LocationResolver = DEFAULT_RESOLVER) -> LocationParse:
    modes: list[str] = []

    def take(t: str) -> None:
        for m in canonical_work_modes(t, policy):
            if m not in modes:
                modes.append(m)

    s = strip_marker(text)

    # 1. parentheticals containing work-mode words
    def _paren(m: re.Match[str]) -> str:
        if MODE_WORD_RE.search(m.group(1)):
            take(m.group(1))
            return ""
        return m.group(0)

    s = re.sub(r"\(([^)]*)\)", _paren, s)

    # 2. " - <tail with work mode>"
    if " - " in s:
        head, tail = s.split(" - ", 1)
        if MODE_WORD_RE.search(tail):
            take(tail)
            s = head

    # 3. US "City - ST" / "City, ST" lists
    us = _us_city_state_list(s.strip(" .;|"), resolver)
    if us:
        us.modes = modes
        return us

    # 4. dash segments right-to-left, then the whole string
    segments = list(reversed(s.split(" - ")))[: 3] if " - " in s else []
    for seg in [*segments, s]:
        res = _parse_place(seg, resolver)
        if res:
            res.modes = modes
            return res
    return LocationParse(modes=modes)
