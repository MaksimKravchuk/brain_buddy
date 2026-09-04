"""The single-start extension identifier is a URL, and it has to resolve.

A2A identifies an extension by a URI and expects the specification to be hosted
*at* that URI (`docs/topics/extensions.md`). BrainBuddy's identifier is a GitHub
`blob/main` URL, which means the repository path it names is not decoration: it
is the published document a third-party agent author reads to decide whether to
declare support, and the one BrainBuddy links from the best-effort disclosure a
user is asked to acknowledge.

Two ways that breaks silently, both covered here:

* the file is moved, renamed or deleted in a later refactor — the identifier
  then 404s, every agent that declared it is pointing at nothing, and the
  disclosure link the user is shown is dead;
* the constant in the code and the path on disk drift apart — the tier is then
  computed from one string while the user is sent to another.

014-FR-011, 014-FR-003. AC-005, AC-026.
"""

from __future__ import annotations

from pathlib import Path

from app.modules.agents.a2a.card import SINGLE_START_EXTENSION_URI

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Frozen by repository policy: never moved, renamed or deleted. A behavioural
#: change gets a new URI (`.../v2.md`), never an edit to this path.
FROZEN_SPEC_PATH = REPO_ROOT / "docs" / "a2a-extensions" / "single-start" / "v1.md"

FROZEN_IDENTIFIER = (
    "https://github.com/MaksimKravchuk/brain_buddy/blob/main/"
    "docs/a2a-extensions/single-start/v1.md"
)


def test_014_FR_011_the_extension_specification_exists_at_the_frozen_path() -> None:
    """AC-005: the identifier is a URL an agent author will actually open.

    If this file moves, the URI stops resolving — and the tier BrainBuddy
    computes from it becomes a promise pointing at a 404.
    """

    assert FROZEN_SPEC_PATH.is_file(), (
        f"{FROZEN_SPEC_PATH} is the published specification named by "
        f"{FROZEN_IDENTIFIER}; the path is frozen by repository policy."
    )
    text = FROZEN_SPEC_PATH.read_text(encoding="utf-8")
    assert FROZEN_IDENTIFIER in text, (
        "the published specification must state its own identifier, so an "
        "agent author copying the URI out of it cannot get a different one."
    )


def test_014_FR_011_the_served_identifier_is_the_frozen_uri() -> None:
    """AC-005, AC-026: one constant decides the tier and the disclosure link.

    ``SINGLE_START_EXTENSION_URI`` is what the card parser matches against and
    what the connection and hand-off responses serve as
    ``tier_disclosure_url``. Asserting it here pins the value that both uses
    read, so the tier can never be computed from one string while the user is
    sent to another.

    T045 extends this to the connection response itself once that schema
    exists; the constant is the same value either way.
    """

    assert SINGLE_START_EXTENSION_URI == FROZEN_IDENTIFIER


def test_014_FR_011_the_identifier_names_the_path_the_file_lives_at() -> None:
    """The URL and the repository layout are two statements of one fact.

    Deriving the path from the URI rather than restating it means a future move
    fails here instead of passing both halves of a contradiction.
    """

    suffix = SINGLE_START_EXTENSION_URI.split("/blob/main/", 1)[1]
    assert (
        REPO_ROOT / suffix
    ).is_file(), (
        f"the identifier names {suffix}, which does not exist in the repository"
    )
    assert (REPO_ROOT / suffix) == FROZEN_SPEC_PATH


def test_014_FR_003_the_published_specification_carries_its_whole_contract() -> None:
    """AC-026: the disclosure sends a user here to understand a real risk.

    A stub at the identifier would be worse than no link: it would look like
    the promise had been documented. The normative sections are named
    individually so a truncated copy fails rather than merely reading short.
    """

    text = FROZEN_SPEC_PATH.read_text(encoding="utf-8")

    for section in (
        "## 1. Purpose",
        "## 2. Declaration",
        "## 3. Activation",
        "## 4. Required behavior",
        "## 5. Client behavior",
        "## 6. Conformance test",
        "## 7. Security considerations",
        "## 8. Versioning and change control",
    ):
        assert section in text, f"the published specification is missing {section}"

    # The dedup key is the entire promise; a copy without it grants nothing.
    assert "(Message.contextId, Message.messageId)" in text
    assert "A2A-Extensions" in text
