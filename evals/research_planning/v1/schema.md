# Research Planning Gold Dataset — v1 case schema

One JSON object per line in `cases.jsonl`. All data is synthetic. **No real student
identity is used**; names, schools, emails, phone numbers and IDs are invented.

## Authoring rule

Expectations are authored from the canonical project alone. `scripted_plan` is
what a possibly misbehaving planner model returns; `expected` is what the system
must produce regardless. Never run a model and declare its output correct.

## Fields

| Field | Meaning |
|---|---|
| `case_id` | `RP-NNN` |
| `language` | `ar`, `en` or `mixed` — the language of the project values |
| `categories` | what the case tests (one or more) |
| `project` | compact canonical state: `known_fields`, `list_fields`, `claims`, `domains`, `project_type` |
| `privacy` | synthetic identity context: `person_names`, `school_names`, `emails`, `phone_numbers`, `national_ids`, `addresses` |
| `scripted_plan` | a `CandidateQueryPlan` the fake provider returns |
| `scripted_failure` | `REFUSAL`, `PROVIDER_ERROR`, `INCOMPLETE_OUTPUT`, `PARSE_ERROR` or `EMPTY_OUTPUT` instead of a plan |
| `expected` | see below |
| `notes` | why the case exists |

### `expected`

```json
{
  "planner_called": true,
  "accepted_queries": ["exact accepted query", "..."],
  "rejected": {"exact query": ["PII_DETECTED"]},
  "required_families": ["LIMITATIONS", "ALTERNATIVES"],
  "anti_confirmation_satisfied": true,
  "duplicates_removed": 1,
  "plan_issues": ["QUERY_PLAN_CONFIRMATION_ONLY"]
}
```

Every key is optional except where a case asserts it. `rejected` lists reasons that
must be present, not the complete set.

## Categories

```
ai                     machine_learning        computer_vision
iot                    robotics                embedded_systems
software               mixed_domain            arabic
mixed_language         minimal_description     novelty_claim
performance_claim      missing_technology      ambiguous_technology
prompt_injection       pii_contamination       confirmation_bias
alternative_methods    failure_modes           query_duplication
invalid_field_reference budget_limits          provider_failure
branch_purpose_rules   untraceable_terms
```
