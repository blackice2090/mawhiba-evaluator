"""CQL query construction and validation -- Phase 2G sections 10, 11, 26.

EPO OPS bibliographic search takes a CQL expression. A malformed expression is
not a transport fault: the provider rejects it identically on every attempt, so
it must be caught *before* the request is made (section 28). This module is that
gate.

Validation is a deliberate allowlist, not a parser. Phase 2G builds its own
queries from the project's own technical content, so the grammar it needs is
small and completely known:

    <field> = "<phrase>"            ti = "solar tracker"
    <field> = <term>                pn = EP1000000A1
    <expr> and <expr>               ti = "x" and ab = "y"
    <expr> or <expr>
    ( <expr> )

Anything outside that -- an unknown index, an unbalanced quote, a stray
semicolon, a ``not`` this phase never plans -- is refused with a named reason
rather than sent and hoped for. That is what makes "invalid query rejected" a
gate with a denominator instead of a caveat.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.schemas.patent import PatentQueryRejectionReason

CQL_VERSION = "PATENT-CQL-V1"

MAX_CQL_LENGTH = 500
"""Upper bound on an expression Phase 2G will send.

EPO OPS accepts longer, but a query this project generates from a claim has no
legitimate reason to grow past this, and an unbounded expression is how a
prompt-injected claim would try to smuggle operators in (section 11).
"""

MIN_TERM_LENGTH = 2

CQL_INDEXES: frozenset[str] = frozenset(
    {
        "ti",
        "ab",
        "ta",
        "ti_ab",
        "txt",
        "pn",
        "ap",
        "pr",
        "in",
        "pa",
        "ipc",
        "cpc",
        "ic",
        "cl",
        "pd",
        "num",
    }
)
"""The OPS bibliographic search indexes this phase uses or accepts.

Restricted on purpose. An index outside this set is refused as
``UNSUPPORTED_QUERY_FIELD`` rather than forwarded: a typo becomes a rejected
query rather than a third-party request that fails with an opaque provider
fault.
"""

CQL_OPERATORS: frozenset[str] = frozenset({"and", "or"})
"""``not`` is deliberately excluded.

Phase 2G searches for potentially similar earlier disclosures. A negation would
let a plan exclude the very documents it is meant to discover, which is the
confirmation bias section 10 forbids -- so the grammar cannot express one.
"""

_FORBIDDEN_CHARACTERS = frozenset(";\\{}<>$`|\n\r\t\0")
"""Characters no legitimate generated CQL expression contains.

Not an escaping mechanism -- this project never escapes and forwards. A query
containing any of these is refused outright.
"""

_TERM = re.compile(r"^[^\W_](?:[^\W_]|[-/.+*])*$", re.UNICODE)
"""An unquoted term: alphanumeric in any script, with technical punctuation.

Unicode-aware so an Arabic term is a valid term. The leading character may not
be punctuation, so ``*solar`` cannot become a leading wildcard the provider
would treat as a corpus-wide scan.
"""

_PHRASE_BODY = re.compile(r'^[^"\\]*$')
"""A quoted phrase may not contain a quote or a backslash: no escape sequences,
so a phrase cannot break out of its own quoting."""

_CLAUSE = re.compile(r"^([A-Za-z_]+)\s*=\s*(.+)$", re.DOTALL)

_TOKEN = re.compile(r'"[^"]*"|\(|\)|\s+|[^\s()"]+')


@dataclass(frozen=True)
class CqlResult:
    """A validated expression, or the reason it was refused."""

    expression: str = ""
    normalized: str = ""
    reason: PatentQueryRejectionReason | None = None
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.reason is None and bool(self.expression)


def _refuse(reason: PatentQueryRejectionReason, detail: str = "") -> CqlResult:
    return CqlResult(reason=reason, detail=detail)


def quote_phrase(phrase: str) -> str:
    """Wrap a multi-word phrase for CQL. Never escapes -- see ``_PHRASE_BODY``."""
    return f'"{phrase.strip()}"'


def build_clause(index: str, value: str, *, phrase: bool | None = None) -> str:
    """One ``index = value`` clause.

    Quoted when the value contains whitespace, so a two-word technical phrase
    stays one phrase instead of becoming two implicitly-joined terms.
    """
    folded = value.strip()
    use_phrase = (" " in folded) if phrase is None else phrase
    return f"{index} = {quote_phrase(folded) if use_phrase else folded}"


def join_clauses(clauses: list[str], operator: str = "and") -> str:
    """Join clauses with one operator, parenthesizing when there are several."""
    kept = [c.strip() for c in clauses if c.strip()]
    if not kept:
        return ""
    if len(kept) == 1:
        return kept[0]
    if operator not in CQL_OPERATORS:
        raise ValueError(f"{operator!r} is not a CQL operator this phase plans")
    return f"({f' {operator} '.join(kept)})"


def normalize_cql(expression: str) -> str:
    """A folded form for duplicate detection only.

    Case folding and whitespace collapse. Nothing about the expression's meaning
    changes and no two different expressions are merged, so two queries that
    normalize alike really did ask the same thing (section 29).
    """
    return re.sub(r"\s+", " ", expression.strip()).casefold()


def _split_top_level(tokens: list[str]) -> list[list[str]] | None:
    """Split a token list on top-level operators. ``None`` if brackets break."""
    depth = 0
    groups: list[list[str]] = [[]]
    for token in tokens:
        if token == "(":
            depth += 1
        elif token == ")":
            depth -= 1
            if depth < 0:
                return None
        if depth == 0 and token.casefold() in CQL_OPERATORS:
            groups.append([])
            continue
        groups[-1].append(token)
    if depth != 0:
        return None
    return groups


def _validate_group(tokens: list[str]) -> PatentQueryRejectionReason | None:
    """Validate one operand: a bracketed sub-expression or a single clause."""
    if not tokens:
        return PatentQueryRejectionReason.INVALID_QUERY_SYNTAX
    if tokens[0] == "(":
        if tokens[-1] != ")":
            return PatentQueryRejectionReason.UNBALANCED_PARENTHESES
        return _validate_tokens(tokens[1:-1])

    clause = _CLAUSE.match(" ".join(tokens))
    if clause is None:
        return PatentQueryRejectionReason.INVALID_QUERY_SYNTAX

    index, value = clause.group(1).casefold(), clause.group(2).strip()
    if index not in CQL_INDEXES:
        return PatentQueryRejectionReason.UNSUPPORTED_QUERY_FIELD
    if not value:
        return PatentQueryRejectionReason.INVALID_QUERY_SYNTAX

    if value.startswith('"'):
        if not value.endswith('"') or len(value) < 2:
            return PatentQueryRejectionReason.UNBALANCED_QUOTES
        body = value[1:-1].strip()
        if not body or not _PHRASE_BODY.match(body):
            return PatentQueryRejectionReason.INVALID_QUERY_SYNTAX
        if len(body) < MIN_TERM_LENGTH:
            return PatentQueryRejectionReason.INVALID_QUERY_SYNTAX
        return None

    if '"' in value:
        return PatentQueryRejectionReason.UNBALANCED_QUOTES
    if " " in value:
        # Two bare terms with no operator: the provider's implicit join is not
        # something this phase relies on, so it is refused rather than guessed.
        return PatentQueryRejectionReason.INVALID_QUERY_SYNTAX
    if len(value) < MIN_TERM_LENGTH or not _TERM.match(value):
        return PatentQueryRejectionReason.INVALID_QUERY_SYNTAX
    return None


def _validate_tokens(tokens: list[str]) -> PatentQueryRejectionReason | None:
    groups = _split_top_level(tokens)
    if groups is None:
        return PatentQueryRejectionReason.UNBALANCED_PARENTHESES
    if any(not group for group in groups):
        # A dangling or leading operator.
        return PatentQueryRejectionReason.INVALID_QUERY_SYNTAX
    for group in groups:
        reason = _validate_group(group)
        if reason is not None:
            return reason
    return None


def validate_cql(expression: str) -> CqlResult:
    """Validate one CQL expression against the allowlisted grammar.

    Refusal reasons are ordered from the cheapest and most specific outward, so
    the reported reason names the actual defect: an unbalanced quote is reported
    as such rather than as generic invalid syntax.
    """
    raw = (expression or "").strip()
    if not raw:
        return _refuse(PatentQueryRejectionReason.EMPTY_QUERY)
    if len(raw) > MAX_CQL_LENGTH:
        return _refuse(
            PatentQueryRejectionReason.QUERY_TOO_LONG,
            f"{len(raw)} characters exceeds {MAX_CQL_LENGTH}",
        )
    offending = sorted(_FORBIDDEN_CHARACTERS & set(raw))
    if offending:
        return _refuse(
            PatentQueryRejectionReason.FORBIDDEN_QUERY_CHARACTER,
            f"contains {''.join(offending)!r}",
        )
    if raw.count('"') % 2:
        return _refuse(PatentQueryRejectionReason.UNBALANCED_QUOTES)

    tokens = [t for t in _TOKEN.findall(raw) if t.strip()]
    if not tokens:
        return _refuse(PatentQueryRejectionReason.EMPTY_QUERY)

    reason = _validate_tokens(tokens)
    if reason is not None:
        return _refuse(reason)
    return CqlResult(expression=raw, normalized=normalize_cql(raw))


__all__ = [
    "CQL_INDEXES",
    "CQL_OPERATORS",
    "CQL_VERSION",
    "MAX_CQL_LENGTH",
    "MIN_TERM_LENGTH",
    "CqlResult",
    "build_clause",
    "join_clauses",
    "normalize_cql",
    "quote_phrase",
    "validate_cql",
]
