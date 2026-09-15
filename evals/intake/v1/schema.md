# Gold Intake Dataset — v1 case schema

One JSON object per line in `cases.jsonl`. All data is synthetic. **No real
student personal data is used.**

## Authoring rule

Gold expectations are authored **independently of any model output**. The
`scripted` block describes what a (possibly misbehaving) model returns; the
`expected` block describes what the system must produce regardless. Never run a
model, look at its answer, and declare that answer correct — that measures
agreement, not correctness.

## Fields

| Field | Meaning |
|---|---|
| `case_id` | stable identifier, `INTAKE-NNN` |
| `language` | `ar`, `en` or `mixed` — the submission's language |
| `category` | what this case is testing (see below) |
| `submission` | the student's text, verbatim |
| `prior_submission` | optional earlier turn, for multi-turn cases |
| `scripted` | what the fake provider returns (may be adversarial) |
| `expected` | the Gold truth the system must produce |
| `notes` | why this case exists |

### `scripted`

```json
{
  "extraction": { ...ProjectExtraction fields... },
  "prior_extraction": { ... },
  "classification": { ...ProjectClassification... },
  "failure": "REFUSAL" | "PROVIDER_ERROR" | "INCOMPLETE_OUTPUT" | "PARSE_ERROR"
}
```

A `failure` replaces `extraction` and exercises provider-failure handling.

### `expected`

```json
{
  "known_fields":   { "<canonical dotted path>": "<exact canonical value>" },
  "unknown_fields": ["<canonical dotted path>", ...],
  "conflicted_fields": ["<canonical dotted path>", ...],
  "list_fields":    { "<canonical dotted path>": ["value", ...] },
  "claims":         [{"claim": "...", "status": "UNSUPPORTED", "origin": "STUDENT"}],
  "domains":        ["INTERNET_OF_THINGS", ...],
  "project_type":   "ENGINEERING_PROJECT",
  "contradictions": 0,
  "rejected_fields": ["sensors", ...],
  "no_evidence":    true
}
```

Every key is optional; only what a case actually asserts needs to appear.

* `known_fields` — must be `KNOWN` with exactly this value. For a
  `VERBATIM_SPAN` field the value is the **source span**, not a paraphrase
  (ADR-004).
* `unknown_fields` — must remain `UNKNOWN`. This is the Unknown Preservation
  metric and the main defence against fabrication.
* `list_fields` — the exact expected list contents, order-insensitive.
* `rejected_fields` — extraction field paths the verifier must refuse.
* `no_evidence` — asserts intake created no `EvidenceRecord` and no
  `SourceRecord`.

## Categories

```
complete_description      incomplete_description     missing_information
multi_technology          ai_project                 iot_project
software_only             robotics                   embedded
research_style            engineering                hybrid
ambiguous                 performance_claim          novelty_claim
missing_dataset           missing_baseline           conflicting_values
multi_turn                prompt_injection           fabricated_anchor
unsupported_value         repeated_excerpt           unicode_normalization
whitespace_normalization  technical_abbreviation     generic_technology
domain_ambiguity          project_type_ambiguity     provider_failure
verbatim_span             student_contribution       canonical_destination
```
