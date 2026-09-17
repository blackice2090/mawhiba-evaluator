"""Claim-component completeness contract -- Phase 2E.1 (ADR-016).

Phase 2E originally took its material component set from the union of the exact
anchors Phase 2D happened to produce. That left a false-sufficiency path: a
compound claim could reach ``SUFFICIENT_SUPPORT`` on the components Phase 2D
identified while another material part of the same claim was never examined at
all, because a part nobody anchored simply did not appear in the denominator.

This module closes that path with a contract rather than a convention. A
``ClaimComponentInventory`` is a **complete covering partition of the original
claim's own text**:

* every component carries an exact anchor, ``claim.claim[start:end] == text``,
  character for character;
* components are pairwise disjoint;
* every character of the claim belongs either to a component or to an explicitly
  recorded immaterial span (whitespace and punctuation between components);
* ``completeness`` is ``COMPLETE`` only when that partition is verified against
  the canonical claim text itself.

The completeness guarantee is therefore *character-coverage arithmetic over the
original claim*, not a semantic guess and not a restatement of what Phase 2D
found. A part of the claim no alignment ever anchored becomes a first-class
component with ``NO_EVIDENCE`` coverage, so it stays in the denominator and
stays visible in the report.

``UNKNOWN`` is a real state and is never read as ``COMPLETE``: when the
inventory could not be derived against the canonical claim -- a missing claim, a
claim whose text does not match the recorded hash -- the assessment says so, and
the schema refuses a full-support or full-contradiction outcome on top of it.
"""

from __future__ import annotations

import unicodedata
from enum import StrEnum
from hashlib import sha256

from pydantic import Field, model_validator

from src.schemas.claim_alignment import CLAIM_ID_PATTERN
from src.schemas.common import MawhibaModel

CLAIM_COMPONENT_INVENTORY_CONTRACT_VERSION = "CLAIM-COMPONENT-INVENTORY-V1"
"""The schema version of the records in this module."""

COMPONENT_PARTITION_STRATEGY_VERSION = "COMPONENT-PARTITION-STRATEGY-V1"
"""The deterministic strategy that chooses component boundaries. A semantic
change requires a bump here so an archived inventory stays readable against the
exact strategy that produced it."""

MAX_CLAIM_COMPONENTS = 64
"""An upper bound, so a pathological claim cannot produce an unbounded
inventory. Exceeding it is recorded as ``INCOMPLETE``, never truncated
silently."""


def claim_text_digest(text: str) -> str:
    """Bind an inventory to the exact claim text it was derived from.

    The raw claim text is never normalized here: a normalized digest would let a
    changed claim keep a matching hash, which is the one thing this field
    exists to prevent.
    """
    return sha256(text.encode("utf-8")).hexdigest()


def is_material_text(text: str) -> bool:
    """Whether a claim span carries material content.

    Material means "contains at least one character that is not whitespace and
    not punctuation or a symbol". The rule is deliberately conservative in the
    only direction that matters: it can only ever call a span *material* that a
    human might consider filler, which leaves an extra component in the
    denominator and makes sufficiency harder to reach. It can never call a span
    immaterial because a stopword list said so, because there is no stopword
    list -- a word-level materiality judgement is exactly the semantic decision
    this phase refuses to fake, and it would be language-dependent in a system
    that must handle Arabic, English and mixed claim text identically.
    """
    return any(
        not character.isspace() and not unicodedata.category(character).startswith(("P", "S"))
        for character in text
    )


class ComponentInventoryCompleteness(StrEnum):
    """Whether the material content of the original claim is fully accounted for.

    ``UNKNOWN`` is never a synonym for ``COMPLETE``. A full-support or
    full-contradiction outcome is structurally invalid unless this is
    ``COMPLETE`` (enforced in ``ClaimSufficiencyAssessment``, not only in policy
    code).
    """

    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    UNKNOWN = "UNKNOWN"


class ComponentOrigin(StrEnum):
    """How this component's boundaries came to exist.

    Recorded per component so a reader can tell a part of the claim evidence was
    aimed at from a part that only exists because the claim contains it. The
    distinction is audit information; it never changes how coverage is computed,
    because a component nobody aimed at must count in the denominator exactly
    like one somebody did.
    """

    ALIGNMENT_ANCHORED = "ALIGNMENT_ANCHORED"
    UNANCHORED_CLAIM_REMAINDER = "UNANCHORED_CLAIM_REMAINDER"


class ComponentInventoryIssue(StrEnum):
    """Why an inventory is not ``COMPLETE``. Finite and machine-readable."""

    CLAIM_NOT_RESOLVABLE = "CLAIM_NOT_RESOLVABLE"
    CLAIM_TEXT_HASH_MISMATCH = "CLAIM_TEXT_HASH_MISMATCH"
    ANCHOR_TEXT_MISMATCH = "ANCHOR_TEXT_MISMATCH"
    ANCHOR_OUT_OF_RANGE = "ANCHOR_OUT_OF_RANGE"
    FOREIGN_CLAIM_ANCHOR = "FOREIGN_CLAIM_ANCHOR"
    UNCOVERED_MATERIAL_TEXT = "UNCOVERED_MATERIAL_TEXT"
    COMPONENT_LIMIT_EXCEEDED = "COMPONENT_LIMIT_EXCEEDED"
    EMPTY_CLAIM_TEXT = "EMPTY_CLAIM_TEXT"


class ClaimTextSpan(MawhibaModel):
    """A half-open span of the claim's own text, recorded by offset only.

    Deliberately offset-only. These spans cover the whitespace and punctuation
    between components, and this project's base model strips surrounding
    whitespace from every string field -- so a stored ``text`` for a run of
    spaces could not round-trip, and a field that cannot hold its own value
    honestly should not exist. The claim text is the source of truth; the
    offsets index into it.
    """

    start: int = Field(ge=0)
    end: int = Field(ge=1)

    @model_validator(mode="after")
    def _span_holds(self) -> ClaimTextSpan:
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self

    @property
    def span(self) -> tuple[int, int]:
        return (self.start, self.end)


class InventoryComponent(MawhibaModel):
    """One material component of the original claim, at an exact anchor.

    ``claim.claim[start:end] == text`` holds by verification, never by trust:
    ``src.research.sufficiency.inventory.verify_inventory`` re-slices the
    canonical claim and compares character for character. Invented claim text
    cannot survive that check.
    """

    claim_id: str = Field(pattern=CLAIM_ID_PATTERN)
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    text: str = Field(min_length=1)
    origin: ComponentOrigin
    alignment_anchor_count: int = Field(
        default=0,
        ge=0,
        description="How many Phase 2D anchors cover this component. Audit "
        "information; zero is the normal state for an unanchored remainder and "
        "never removes the component from the denominator.",
    )

    @model_validator(mode="after")
    def _span_holds(self) -> InventoryComponent:
        if self.end <= self.start:
            raise ValueError("end must be after start")
        if len(self.text) != self.end - self.start:
            raise ValueError("component anchor text length must match the span")
        if self.text != self.text.strip():
            raise ValueError(
                "a component anchor must not carry surrounding whitespace; "
                "leading and trailing whitespace belongs in immaterial_spans"
            )
        if not is_material_text(self.text):
            raise ValueError(
                "an inventory component must carry material claim text; "
                "whitespace and punctuation belong in immaterial_spans"
            )
        if self.origin is ComponentOrigin.UNANCHORED_CLAIM_REMAINDER and (
            self.alignment_anchor_count != 0
        ):
            raise ValueError(
                "an UNANCHORED_CLAIM_REMAINDER component cannot report covering "
                "Phase 2D anchors"
            )
        if self.origin is ComponentOrigin.ALIGNMENT_ANCHORED and (
            self.alignment_anchor_count < 1
        ):
            raise ValueError(
                "an ALIGNMENT_ANCHORED component must report at least one "
                "covering Phase 2D anchor"
            )
        return self

    @property
    def component_key(self) -> tuple[int, int, str]:
        return (self.start, self.end, self.text)

    @property
    def span(self) -> tuple[int, int]:
        return (self.start, self.end)


class ClaimComponentInventory(MawhibaModel):
    """The complete material component set of ONE original claim.

    Derived from the canonical claim's own text and **not** from the union of
    Phase 2D alignment anchors: every part of the claim no anchor reached is
    present here as an ``UNANCHORED_CLAIM_REMAINDER`` component, which is
    precisely what keeps unexamined material claim content inside the
    sufficiency denominator.

    Lives on the ``ResearchRun`` via ``ClaimSufficiencyAssessment``, never in
    ``ProjectState``, and never mutates the ``ClaimRecord`` it describes
    (ADR-010, ADR-016).
    """

    claim_id: str = Field(pattern=CLAIM_ID_PATTERN)
    claim_text_hash: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description="sha256 of the exact canonical claim text this inventory "
        "was derived from. A changed claim cannot keep a matching hash.",
    )
    claim_text_length: int = Field(ge=0)
    components: list[InventoryComponent] = Field(default_factory=list)
    immaterial_spans: list[ClaimTextSpan] = Field(
        default_factory=list,
        description="Whitespace and punctuation between components, recorded "
        "explicitly so the partition can be proven to cover the whole claim "
        "rather than asserted to.",
    )
    completeness: ComponentInventoryCompleteness
    issues: list[ComponentInventoryIssue] = Field(default_factory=list)
    contract_version: str = CLAIM_COMPONENT_INVENTORY_CONTRACT_VERSION
    strategy_version: str = COMPONENT_PARTITION_STRATEGY_VERSION

    @model_validator(mode="after")
    def _partition_holds(self) -> ClaimComponentInventory:
        if any(component.claim_id != self.claim_id for component in self.components):
            raise ValueError(
                "an inventory component belongs to a different claim; "
                "cross-claim inventory contamination is refused"
            )

        spans = [component.span for component in self.components] + [
            span.span for span in self.immaterial_spans
        ]
        ordered = sorted(spans)
        for (_, previous_end), (next_start, _) in zip(ordered, ordered[1:]):
            if next_start < previous_end:
                raise ValueError(
                    "inventory spans must be pairwise disjoint; overlapping "
                    "components would double-count claim text"
                )
        for start, end in spans:
            if end > self.claim_text_length:
                raise ValueError("an inventory span runs past the end of the claim")

        if len(self.components) > MAX_CLAIM_COMPONENTS:
            raise ValueError(
                f"an inventory may hold at most {MAX_CLAIM_COMPONENTS} components"
            )

        covered = sum(end - start for start, end in spans)
        fully_partitions = covered == self.claim_text_length and (
            not ordered or ordered[0][0] == 0
        )

        if self.completeness is ComponentInventoryCompleteness.COMPLETE:
            if self.issues:
                raise ValueError(
                    "a COMPLETE inventory cannot carry issues: "
                    f"{[i.value for i in self.issues]}"
                )
            if not self.components:
                raise ValueError(
                    "a COMPLETE inventory must hold at least one material component"
                )
            if not fully_partitions:
                raise ValueError(
                    "a COMPLETE inventory must partition the whole claim text; "
                    f"{self.claim_text_length - covered} character(s) are unaccounted for"
                )
        elif not self.issues:
            raise ValueError(
                f"completeness={self.completeness.value} must state at least one issue"
            )
        return self

    @property
    def is_complete(self) -> bool:
        """True only for ``COMPLETE``. ``UNKNOWN`` is never complete."""
        return self.completeness is ComponentInventoryCompleteness.COMPLETE

    @property
    def component_keys(self) -> list[tuple[int, int, str]]:
        return sorted(component.component_key for component in self.components)

    @property
    def unanchored_components(self) -> list[InventoryComponent]:
        """Material claim parts no Phase 2D anchor reached."""
        return [
            component
            for component in self.components
            if component.origin is ComponentOrigin.UNANCHORED_CLAIM_REMAINDER
        ]


__all__ = [
    "CLAIM_COMPONENT_INVENTORY_CONTRACT_VERSION",
    "COMPONENT_PARTITION_STRATEGY_VERSION",
    "MAX_CLAIM_COMPONENTS",
    "ClaimComponentInventory",
    "ClaimTextSpan",
    "ComponentInventoryCompleteness",
    "ComponentInventoryIssue",
    "ComponentOrigin",
    "InventoryComponent",
    "claim_text_digest",
    "is_material_text",
]
