"""Deterministic scoring arithmetic -- ``SCORE-ARITHMETIC-V1`` (section 16).

The contract, stated once so every dimension obeys the same rule:

1. **Integer basis points are the source of truth.** A directional index is an
   integer in ``[0, 10000]``; ``10000 bp`` is ``100.00``. Nothing downstream
   stores a float, so nothing downstream can accumulate binary rounding error.
2. **``Decimal`` for intermediates.** A fraction of components times a
   dimension ceiling is computed in ``Decimal`` with a precision wide enough
   that the division is exact to far more places than the result needs.
3. **``ROUND_HALF_EVEN`` to whole basis points.** Chosen over ``ROUND_HALF_UP``
   because it is unbiased: half-way cases do not systematically favour the
   higher score, and a scoring policy should not round in its own favour.
4. **Each dimension is rounded, then summed.** The total is the sum of the
   *stored* dimensions, never a separately rounded whole, so
   ``index_bp == coverage_bp + corroboration_bp + directness_bp`` holds exactly
   and ``DirectionalScore`` can validate it (section 21).

Rule 4 is the one worth spelling out. Rounding the total independently would
produce cards whose scalar is off by one basis point from their own vector, and
a reader who added the dimensions up would find the system disagreeing with
itself about its own arithmetic.

Identical inputs therefore produce byte-identical serialized numbers on any
platform: there is no float anywhere in the path.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal, localcontext

SCORE_DECIMAL_PRECISION = 28
"""Working precision for intermediates. Far wider than the four significant
digits a basis point needs, so the quantize step is the only rounding."""

ROUNDING_MODE = ROUND_HALF_EVEN
"""Banker's rounding: unbiased at the half-way point (see rule 3 above)."""

_WHOLE = Decimal(1)


def scaled_basis_points(numerator: int, denominator: int, ceiling_bp: int) -> int:
    """``numerator / denominator * ceiling_bp``, as whole basis points.

    ``denominator == 0`` yields ``0`` rather than raising: a claim with no
    material component to score has no evidence posture, and ``0`` with an
    explicit ``NO_DIRECT_EVIDENCE``-style disposition beside it is the honest
    representation. Returning a positive number from an empty denominator is
    what the schema refuses outright.
    """
    if denominator <= 0:
        return 0
    if numerator <= 0:
        return 0
    with localcontext() as context:
        context.prec = SCORE_DECIMAL_PRECISION
        exact = (
            Decimal(numerator) / Decimal(denominator) * Decimal(ceiling_bp)
        )
        return int(exact.quantize(_WHOLE, rounding=ROUNDING_MODE))


def weighted_basis_points(
    factor_sum_bp: int, denominator: int, ceiling_bp: int
) -> int:
    """A sum of per-component factors, as whole basis points of a ceiling.

    ``factor_sum_bp`` is the sum of per-component factors each expressed in
    basis points of one component (``10000`` = a full component, ``5000`` =
    half). Dividing by ``denominator * 10000`` turns that into the fraction of
    the complete component inventory earned, which is then scaled to the
    dimension ceiling.

    Factors are carried in basis points rather than as ``0.5`` floats so the
    half-credit rule for partial relations is exact.
    """
    if denominator <= 0 or factor_sum_bp <= 0:
        return 0
    with localcontext() as context:
        context.prec = SCORE_DECIMAL_PRECISION
        exact = (
            Decimal(factor_sum_bp)
            / (Decimal(denominator) * Decimal(10_000))
            * Decimal(ceiling_bp)
        )
        return int(exact.quantize(_WHOLE, rounding=ROUNDING_MODE))


def bounded(value: int, ceiling: int) -> int:
    """Clamp to ``[0, ceiling]``.

    A defensive floor and cap, not a policy device. Every formula here is
    already bounded by construction, so a value arriving outside the range would
    mean an arithmetic bug; clamping keeps that from becoming an unvalidatable
    record, and the schema's own range check still fires on anything the caller
    assembled wrongly.
    """
    return max(0, min(value, ceiling))


__all__ = [
    "ROUNDING_MODE",
    "SCORE_DECIMAL_PRECISION",
    "bounded",
    "scaled_basis_points",
    "weighted_basis_points",
]
