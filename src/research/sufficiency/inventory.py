"""Deterministic claim-component inventory -- Phase 2E.1 (ADR-016).

``COMPONENT-PARTITION-STRATEGY-V1``, stated in full so it can be reviewed as a
strategy rather than reverse-engineered from code.

Given the canonical claim text ``t`` and the set of Phase 2D component anchors
for that claim:

1. **Verify every anchor against ``t`` itself.** An anchor survives only when it
   names this claim, lies inside ``[0, len(t))`` and satisfies
   ``t[start:end] == text`` character for character. No normalization, no
   case folding, no whitespace tolerance. An anchor that fails is recorded as an
   issue and the inventory becomes ``INCOMPLETE`` -- it is never dropped
   quietly, because a fabricated anchor must make full sufficiency impossible
   rather than merely shrink the denominator.
2. **Cut ``t`` at every surviving anchor boundary**, plus ``0`` and ``len(t)``.
   This yields consecutive, pairwise disjoint segments that together cover every
   character of the claim.
3. **Classify each segment.** A segment carrying material content (at least one
   character that is neither whitespace nor punctuation) becomes an
   ``InventoryComponent``. A segment that is only whitespace or punctuation
   becomes a recorded ``immaterial_span``.
4. **Label each component's origin.** ``ALIGNMENT_ANCHORED`` when some surviving
   anchor fully covers it, ``UNANCHORED_CLAIM_REMAINDER`` otherwise. The label is
   audit information only: an unanchored remainder counts in the denominator
   exactly like an anchored component, which is the whole point.
5. **Completeness is arithmetic.** ``COMPLETE`` only when there are no issues, at
   least one material component exists, and the component and immaterial spans
   together cover ``[0, len(t))`` exactly.

Why this is not "the union of Phase 2D anchors". The forbidden construction
takes the anchors as the component set, so a part of the claim nobody anchored
is absent from the denominator and cannot prevent ``SUFFICIENT_SUPPORT``. Here
the denominator is derived from the *claim text*: the anchors only choose where
the cuts fall, and every uncovered character of the claim still has to land in
some component or be provably immaterial. Step 5 is checked against ``t``, not
against the anchor set, so the guarantee survives any anchor set at all --
including the empty one, which yields one ``UNANCHORED_CLAIM_REMAINDER``
component spanning the whole claim.

Why there is still no model call. Choosing cut points is a semantic judgement,
and this strategy deliberately does not make one: it does not split on
conjunctions or punctuation, because "black and white image" is one component
and no deterministic rule can tell it from "is fast and is accurate". Instead it
uses the boundaries Phase 2D already established and proves *coverage* of the
claim independently. The cost is granularity, not soundness: a coarser partition
makes sufficiency harder to reach, never easier. See ADR-016 for the limitation
this leaves and for the rejected alternatives.
"""

from __future__ import annotations

from src.schemas.claim import ClaimRecord
from src.schemas.claim_component_inventory import (
    MAX_CLAIM_COMPONENTS,
    ClaimComponentInventory,
    ClaimTextSpan,
    ComponentInventoryCompleteness,
    ComponentInventoryIssue,
    ComponentOrigin,
    InventoryComponent,
    claim_text_digest,
    is_material_text,
)

Anchor = tuple[int, int, str]
"""A Phase 2D component anchor as ``(start, end, text)``."""

EMPTY_CLAIM_TEXT_HASH = claim_text_digest("")
"""The digest of no claim text, used when the claim cannot be resolved at all."""


def anchor_issues(claim: ClaimRecord, anchor: Anchor) -> list[ComponentInventoryIssue]:
    """Why this anchor does not hold against the canonical claim text.

    Empty means it holds exactly. Checked by re-slicing ``claim.claim``; the
    stored text is never trusted to describe itself.
    """
    start, end, text = anchor
    issues: list[ComponentInventoryIssue] = []
    if start < 0 or end <= start or end > len(claim.claim):
        issues.append(ComponentInventoryIssue.ANCHOR_OUT_OF_RANGE)
        return issues
    if claim.claim[start:end] != text:
        issues.append(ComponentInventoryIssue.ANCHOR_TEXT_MISMATCH)
    return issues


def build_inventory(
    claim: ClaimRecord | None,
    anchors: list[Anchor],
    *,
    claim_id: str,
) -> ClaimComponentInventory:
    """The complete material component inventory for one claim.

    ``claim`` is ``None`` when the alignment names a claim this run cannot
    resolve. That is reported as ``UNKNOWN`` completeness rather than as an
    empty-but-complete inventory, because "we could not read the claim" must
    never be indistinguishable from "the claim has no material content".
    """
    if claim is None:
        return ClaimComponentInventory(
            claim_id=claim_id,
            claim_text_hash=EMPTY_CLAIM_TEXT_HASH,
            claim_text_length=0,
            completeness=ComponentInventoryCompleteness.UNKNOWN,
            issues=[ComponentInventoryIssue.CLAIM_NOT_RESOLVABLE],
        )

    text = claim.claim
    issues: list[ComponentInventoryIssue] = []
    valid: list[Anchor] = []
    for anchor in anchors:
        found = anchor_issues(claim, anchor)
        if found:
            issues.extend(found)
            continue
        valid.append(anchor)

    cuts = {0, len(text)}
    for start, end, _ in valid:
        cuts.add(start)
        cuts.add(end)
    boundaries = sorted(cuts)

    components: list[InventoryComponent] = []
    immaterial: list[ClaimTextSpan] = []
    for start, end in zip(boundaries, boundaries[1:]):
        segment = text[start:end]
        if not segment:
            continue
        if not is_material_text(segment):
            immaterial.append(ClaimTextSpan(start=start, end=end))
            continue
        # Surrounding whitespace is moved out of the component and recorded as
        # immaterial, so the component anchor is exactly the claim text it
        # names and the partition still covers every character.
        lead = len(segment) - len(segment.lstrip())
        trail = len(segment) - len(segment.rstrip())
        if lead:
            immaterial.append(ClaimTextSpan(start=start, end=start + lead))
        if trail:
            immaterial.append(ClaimTextSpan(start=end - trail, end=end))
        start, end = start + lead, end - trail
        segment = text[start:end]
        covering = sum(
            1
            for anchor_start, anchor_end, _ in valid
            if anchor_start <= start and end <= anchor_end
        )
        components.append(
            InventoryComponent(
                claim_id=claim_id,
                start=start,
                end=end,
                text=segment,
                origin=(
                    ComponentOrigin.ALIGNMENT_ANCHORED
                    if covering
                    else ComponentOrigin.UNANCHORED_CLAIM_REMAINDER
                ),
                alignment_anchor_count=covering,
            )
        )

    if len(components) > MAX_CLAIM_COMPONENTS:
        # Refused rather than truncated: a truncated inventory would silently
        # shrink the denominator, which is the exact failure this contract exists
        # to prevent.
        return ClaimComponentInventory(
            claim_id=claim_id,
            claim_text_hash=claim_text_digest(text),
            claim_text_length=len(text),
            completeness=ComponentInventoryCompleteness.INCOMPLETE,
            issues=[ComponentInventoryIssue.COMPONENT_LIMIT_EXCEEDED],
        )

    if not components:
        issues.append(ComponentInventoryIssue.EMPTY_CLAIM_TEXT)

    ordered_issues = [issue for issue in ComponentInventoryIssue if issue in set(issues)]
    completeness = (
        ComponentInventoryCompleteness.COMPLETE
        if not ordered_issues
        else ComponentInventoryCompleteness.INCOMPLETE
    )
    return ClaimComponentInventory(
        claim_id=claim_id,
        claim_text_hash=claim_text_digest(text),
        claim_text_length=len(text),
        components=components,
        immaterial_spans=immaterial,
        completeness=completeness,
        issues=ordered_issues,
    )


def verify_inventory(
    claim: ClaimRecord | None, inventory: ClaimComponentInventory
) -> list[ComponentInventoryIssue]:
    """Re-prove a stored inventory against the canonical claim.

    Independent of ``build_inventory``: this re-slices the claim text and
    re-computes the coverage arithmetic, so a stored inventory that was built
    elsewhere, replayed from a checkpoint, or hand-assembled is held to the same
    standard. Empty means the inventory holds.

    It proves *structural* correctness -- exact anchors, disjointness, full
    coverage of the claim, the right claim. It does not and cannot prove that
    the partition is the scientifically ideal decomposition of the proposition.
    """
    if claim is None:
        return [ComponentInventoryIssue.CLAIM_NOT_RESOLVABLE]

    issues: list[ComponentInventoryIssue] = []
    if inventory.claim_id != claim.claim_id:
        issues.append(ComponentInventoryIssue.FOREIGN_CLAIM_ANCHOR)
    if inventory.claim_text_hash != claim_text_digest(claim.claim):
        issues.append(ComponentInventoryIssue.CLAIM_TEXT_HASH_MISMATCH)
    if inventory.claim_text_length != len(claim.claim):
        issues.append(ComponentInventoryIssue.CLAIM_TEXT_HASH_MISMATCH)

    for component in inventory.components:
        if component.claim_id != claim.claim_id:
            issues.append(ComponentInventoryIssue.FOREIGN_CLAIM_ANCHOR)
            continue
        if component.end > len(claim.claim):
            issues.append(ComponentInventoryIssue.ANCHOR_OUT_OF_RANGE)
            continue
        if claim.claim[component.start : component.end] != component.text:
            issues.append(ComponentInventoryIssue.ANCHOR_TEXT_MISMATCH)

    covered = sum(
        end - start
        for start, end in [c.span for c in inventory.components]
        + [s.span for s in inventory.immaterial_spans]
    )
    if covered != len(claim.claim):
        issues.append(ComponentInventoryIssue.UNCOVERED_MATERIAL_TEXT)

    return [issue for issue in ComponentInventoryIssue if issue in set(issues)]


def inventory_holds(claim: ClaimRecord | None, inventory: ClaimComponentInventory) -> bool:
    """True when the inventory is ``COMPLETE`` *and* re-proves against the claim."""
    return inventory.is_complete and not verify_inventory(claim, inventory)


__all__ = [
    "EMPTY_CLAIM_TEXT_HASH",
    "Anchor",
    "anchor_issues",
    "build_inventory",
    "inventory_holds",
    "verify_inventory",
]
