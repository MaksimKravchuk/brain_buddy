"""Language-faithful title invariant for Voice Brain Dump (FR-006).

This is deliberately distinct from FR-008 *grounding* tolerance. Grounding
(``reconciler._assert_semantic_support``) proves a title's *meaning* is
supported by cited transcript evidence and intentionally tolerates
morphological variation of the source language (Russian imperative ↔
infinitive, case endings, etc.). This module enforces the separate FR-006
*generation* rule: a proposal title must stay in its source utterance's
language and must never be translated into another language. A fully
translated title can satisfy grounding (its meaning is supported) yet still
violate FR-006 — so this invariant is layered on top of grounding, never
folded into it.

The check is script-based, which is the language-neutral signal available
without a language model and is consistent with the rest of the pipeline
(``_named_entities`` already keys off script/capitalization). It compares the
dominant script of the *language-carrying* content on each side after removing
the proper nouns / code-switch terms shared verbatim between the title and its
source. That removal is what makes an embedded foreign proper noun legitimate:
a Cyrillic title naming "BrainBuddy" or "Google Meet", or a Latin-only
utterance yielding a Latin title, both stay faithful, while a wholesale rewrite
of the spoken words into another script is flagged as a translation. The rule
is about the title's dominant script matching its source's, not script purity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


class ScriptLabel(str, Enum):
    """Coarse, privacy-safe script/language label for a span of text."""

    CYRILLIC = "cyrillic"
    LATIN = "latin"
    MIXED = "mixed"
    NEUTRAL = "neutral"


class FidelityVerdict(str, Enum):
    FAITHFUL = "faithful"
    TRANSLATED = "translated"
    UNDETERMINED = "undetermined"


@dataclass(frozen=True)
class FidelityResult:
    """Privacy-safe outcome of a title/source fidelity comparison.

    Carries only coarse script labels and a verdict — never the raw title or
    transcript text — so it can be persisted into an evidence artifact under
    constitution Principle I.
    """

    verdict: FidelityVerdict
    source_script: ScriptLabel
    title_script: ScriptLabel


def _char_script(character: str) -> ScriptLabel | None:
    if not character.isalpha():
        return None
    code = ord(character)
    if 0x0400 <= code <= 0x052F:  # Cyrillic + Cyrillic Supplement
        return ScriptLabel.CYRILLIC
    if (
        0x41 <= code <= 0x5A
        or 0x61 <= code <= 0x7A
        or 0xC0 <= code <= 0x24F  # Latin-1 Supplement + Extended-A/B letters
    ):
        return ScriptLabel.LATIN
    return None


def dominant_script(text: str) -> ScriptLabel:
    """Return the script holding the majority of ``text``'s alphabetic content.

    ``MIXED`` is reserved for the exact tie where both scripts are present in
    equal measure; ``NEUTRAL`` means no alphabetic content at all (digits,
    punctuation, whitespace). A handful of embedded foreign letters never flips
    the majority, which is what lets an embedded proper noun ride along inside
    an otherwise single-language span.
    """

    cyrillic = latin = 0
    for character in text:
        script = _char_script(character)
        if script is ScriptLabel.CYRILLIC:
            cyrillic += 1
        elif script is ScriptLabel.LATIN:
            latin += 1
    if cyrillic == 0 and latin == 0:
        return ScriptLabel.NEUTRAL
    if cyrillic > latin:
        return ScriptLabel.CYRILLIC
    if latin > cyrillic:
        return ScriptLabel.LATIN
    return ScriptLabel.MIXED


# Only content-length tokens carry a language signal. One- and two-character
# particles (Russian «на»/«в»/«и», English "to"/"in"/"of") are grammatical glue,
# not translated content: a lone particle swapped across scripts must not flip a
# title from faithful to translated, while a translated verb or noun (≥3
# characters) must.
_CONTENT_MIN_LENGTH = 3


def _proper_noun_folds(text: str) -> set[str]:
    """Casefolds of capitalized, non-sentence-initial tokens (proper-noun proxy).

    A name's script says nothing about the sentence's language — a Russian
    utterance routinely names a Latin-script product or person ("BrainBuddy",
    "Alice"). Excluding names from the language comparison is what separates a
    *translation* (the ordinary words changed script) from a mere *identity*
    difference (a different name), which is grounding's concern, not FR-006's.
    Sentence-initial capitalization is a punctuation convention, so the first
    word is never treated as a name. Language-neutral across scripts, matching
    ``reconciler._named_entities``.
    """

    folds: set[str] = set()
    stripped = text.strip()
    for match in _WORD_RE.finditer(stripped):
        token = match.group()
        preceding = stripped[: match.start()].rstrip()
        if not preceding or preceding[-1] in ".!?":
            continue
        if token[:1].isupper() and len(token) >= 2:
            folds.add(token.casefold())
    return folds


def _damerau_levenshtein(first: str, second: str) -> int:
    """Optimal string-alignment distance (insert/delete/substitute/transpose)."""

    len_first, len_second = len(first), len(second)
    if not len_first:
        return len_second
    if not len_second:
        return len_first
    previous_two = [0] * (len_second + 1)
    previous = list(range(len_second + 1))
    for i in range(1, len_first + 1):
        current = [i] + [0] * len_second
        for j in range(1, len_second + 1):
            cost = 0 if first[i - 1] == second[j - 1] else 1
            current[j] = min(
                current[j - 1] + 1, previous[j] + 1, previous[j - 1] + cost
            )
            if (
                i > 1
                and j > 1
                and first[i - 1] == second[j - 2]
                and first[i - 2] == second[j - 1]
            ):
                current[j] = min(current[j], previous_two[j - 2] + 1)
        previous_two, previous = previous, current
    return previous[len_second]


def _garble_equivalent(first: str, second: str) -> bool:
    """Same code-switch/proper-noun term up to a small STT garble.

    Mirrors ``reconciler._entities_equivalent``: only *long* tokens (≥5 chars)
    within edit distance 2 and a quarter of the longer token qualify, so a
    garbled product name ("grainbuddy"/"BrainBuddy") counts as the same
    preserved term on both sides while genuinely distinct words never do. A
    cross-script translation never matches (its distance is large), so this can
    only remove shared terms, never mask a translation.
    """

    if first == second:
        return True
    if len(first) < 5 or len(second) < 5:
        return False
    distance = _damerau_levenshtein(first, second)
    return distance <= 2 and distance * 4 <= max(len(first), len(second))


def _language_content_script(text: str, other: str) -> ScriptLabel:
    """Dominant script of ``text``'s own language-carrying content.

    Drops (a) grammatical particles below the content-length floor, (b) proper
    nouns, and (c) the vocabulary shared with ``other`` — the code-switch terms
    and names both sides preserve, matched up to a small STT garble so a name
    corrected in the title still cancels its garbled source form. What remains
    is the ordinary words that carry ``text``'s language, so their dominant
    script is the language signal. Shared removal is conservative: an inflected
    pair left unremoved is same-script on both sides and can never manufacture a
    false translation verdict.
    """

    other_tokens = [token.casefold() for token in _WORD_RE.findall(other)]
    other_folded = set(other_tokens)
    names = _proper_noun_folds(text)
    content = " ".join(
        token
        for token in _WORD_RE.findall(text)
        if len(token) >= _CONTENT_MIN_LENGTH
        and token.casefold() not in names
        and token.casefold() not in other_folded
        and not any(
            _garble_equivalent(token.casefold(), candidate)
            for candidate in other_tokens
        )
    )
    return dominant_script(content)


def classify_title_fidelity(title: str, source_text: str) -> FidelityResult:
    """Classify whether ``title`` stays in the language of ``source_text``.

    ``TRANSLATED`` is returned only when each side's own language-carrying
    content (particles, proper nouns, and shared code-switch terms removed) has
    a determinate and differing dominant script — i.e. the ordinary spoken words
    were rewritten into another language. Titles that reuse or inflect the
    source's words, add or keep an embedded foreign proper noun, or merely
    differ by a translated particle stay ``FAITHFUL``; indeterminate/mixed
    content resolves to ``FAITHFUL`` so a genuinely code-switched title never
    fails closed. The check is script-based, so it detects Cyrillic↔Latin
    translation (the RU/EN axis of the reference corpus) and intentionally does
    not adjudicate same-script language pairs (e.g. Dutch↔English).
    """

    return FidelityResult(
        verdict=_compare(
            _language_content_script(title, source_text),
            _language_content_script(source_text, title),
        ),
        source_script=dominant_script(source_text),
        title_script=dominant_script(title),
    )


def _compare(title_script: ScriptLabel, source_script: ScriptLabel) -> FidelityVerdict:
    determinate = {ScriptLabel.CYRILLIC, ScriptLabel.LATIN}
    if title_script in determinate and source_script in determinate:
        return (
            FidelityVerdict.TRANSLATED
            if title_script is not source_script
            else FidelityVerdict.FAITHFUL
        )
    return FidelityVerdict.FAITHFUL


def title_is_language_faithful(title: str, source_text: str) -> bool:
    """Convenience boolean for the reconciler generation invariant (FR-006)."""

    return (
        classify_title_fidelity(title, source_text).verdict
        is not FidelityVerdict.TRANSLATED
    )
