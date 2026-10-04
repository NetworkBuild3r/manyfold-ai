"""Tag normalisation: one tag shape for every source (code, spark-curate keywords, the LLM, humans).

A tag is lowercase ASCII kebab-case, at most 40 characters, never a stopword or a bare number.
``normalise_tag`` is: slugify -> drop a leading "the-" -> synonym map -> singularise the last
word -> drop trailing generic words (``marvel-files``) -> synonym map again -> stopword / length /
digit checks. ``normalise_tags`` adds order-
preserving dedupe and a cap (12 for the LLM list).

The vocabulary (synonyms such as ``dnd`` -> ``dungeons-and-dragons``, protected plurals,
irregular plurals, stopwords) lives in ``vocab.json`` next to this file. Normalisation shapes
metadata for search; it never decides a route (myaifitness-no-regex-routing is about chat
routing, and nothing here reads chat text).

INIT-032/SPEC-016
"""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

MAX_TAGS = 12  # LLM list and the default cap
MAX_TAG_LEN = 40
MAX_FINAL_TAGS = 40  # merged tags stored on a pack


@dataclass(frozen=True)
class Vocab:
    synonyms: dict[str, str]
    canonical: frozenset[str]
    protect: frozenset[str]
    irregular: dict[str, str]
    ie_plurals: frozenset[str]
    stopwords: frozenset[str]
    trailing_generic: frozenset[str]


@lru_cache(maxsize=1)
def vocab() -> Vocab:
    raw = json.loads(resources.files("forge.tags").joinpath("vocab.json").read_text("utf-8"))
    synonyms = {str(k): str(v) for k, v in raw["synonyms"].items()}
    return Vocab(
        synonyms=synonyms,
        canonical=frozenset(synonyms.values()),
        protect=frozenset(raw["protect_plural"]),
        irregular={str(k): str(v) for k, v in raw["irregular_plurals"].items()},
        ie_plurals=frozenset(raw["ie_plurals"]),
        stopwords=frozenset(raw["stopwords"]),
        trailing_generic=frozenset(raw["trailing_generic"]),
    )


def slugify(raw: str) -> str:
    """Lowercase ASCII kebab-case: accents stripped, ``&`` -> ``and``, apostrophes dropped, every
    other non-alphanumeric run -> one hyphen, no leading / trailing hyphen."""
    out: list[str] = []
    pending_dash = False
    for ch in unicodedata.normalize("NFKD", raw):
        if unicodedata.combining(ch):
            continue
        if ch in "'\u2019\u2018`":
            continue
        piece = "-and-" if ch == "&" else ch.lower()
        for c in piece:
            if c.isascii() and c.isalnum():
                if pending_dash and out:
                    out.append("-")
                pending_dash = False
                out.append(c)
            else:
                pending_dash = True
    return "".join(out)


def singular_word(word: str) -> str:
    """Obvious plural -> singular for one lowercase word; anything doubtful is left alone."""
    v = vocab()
    if word in v.irregular:
        return v.irregular[word]
    if word in v.protect or len(word) < 4 or not word.endswith("s"):
        return word
    if word.endswith(("ss", "us", "is")):
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-1] if word in v.ie_plurals else word[:-3] + "y"
    if word.endswith(("sses", "ches", "shes", "xes", "zzes")):
        return word[:-2]
    return word[:-1]


def singular_slug(slug: str) -> str:
    """Singularise the last word of a kebab slug (``x-men`` / ``star-wars`` stay intact)."""
    if slug in vocab().protect:
        return slug
    head, sep, last = slug.rpartition("-")
    return head + sep + singular_word(last)


def strip_trailing_generic(slug: str) -> str:
    """``marvel-files`` / ``dc-collection`` -> ``marvel`` / ``dc``: a generic last word adds nothing
    to a multi-word tag (a lone generic word is handled as a stopword instead)."""
    generic = vocab().trailing_generic
    words = slug.split("-")
    while len(words) > 1 and words[-1] in generic:
        words.pop()
    return "-".join(words)


def clip(slug: str, limit: int = MAX_TAG_LEN) -> str:
    """At most ``limit`` characters, cut at a word boundary when one exists; '' if too short."""
    if len(slug) <= limit:
        return slug
    cut = slug[:limit]
    if slug[limit] != "-" and "-" in cut:
        cut = cut[: cut.rfind("-")]
    cut = cut.strip("-")
    return cut if len(cut) >= 2 else ""


def normalise_tag(raw: object, *, singular: bool = True) -> str | None:
    """The normalised tag, or ``None`` when the input names nothing (empty, stopword, number).

    ``singular=False`` keeps proper names (creators, sources, categories) and owner-written tags
    as written: no singularising, no trailing-generic-word stripping (synonyms still apply)."""
    if not isinstance(raw, str):
        return None
    v = vocab()
    slug = slugify(raw)
    if slug.startswith("the-") and len(slug) > 4:
        slug = slug[4:]
    if not slug:
        return None
    if slug in v.canonical:
        final = slug
    elif slug in v.synonyms:
        final = v.synonyms[slug]
    else:
        if (
            singular
        ):  # free-text mode (LLM, classify keywords); names and owner tags stay as written
            slug = strip_trailing_generic(singular_slug(slug))
        final = v.synonyms.get(slug, slug)
    final = clip(final)
    if not final or final in v.stopwords or final.replace("-", "").isdigit():
        return None
    return final


def normalise_tags(
    raw: Iterable[object], *, cap: int | None = MAX_TAGS, singular: bool = True
) -> list[str]:
    """Normalise, dedupe (first occurrence wins, order kept) and cap."""
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        tag = normalise_tag(item, singular=singular)
        if tag is None or tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
        if cap is not None and len(out) >= cap:
            break
    return out


def merge_tags(
    *lists: Iterable[str],
    add: Iterable[object] = (),
    remove: Iterable[object] = (),
    replace: Iterable[object] | None = None,
    cap: int = MAX_FINAL_TAGS,
) -> list[str]:
    """Stable set union: earlier lists first (deterministic tags, then LLM, then classify).

    Owner overrides win: ``replace`` (when given) replaces every derived list, ``add`` is appended
    and ``remove`` is dropped from the result. Every input is normalised; ``add`` / ``replace`` are
    never singularised (the owner wrote them on purpose)."""
    if replace is not None:
        base = normalise_tags(replace, cap=None, singular=False)
    else:
        base = []
        for lst in lists:
            base.extend(normalise_tags(lst, cap=None, singular=False))
    extra = normalise_tags(add, cap=None, singular=False)
    gone = set(normalise_tags(remove, cap=None, singular=False))
    out: list[str] = []
    seen: set[str] = set()
    for tag in [*base, *extra]:
        if tag in seen or tag in gone:
            continue
        seen.add(tag)
        out.append(tag)
    return out[:cap]
