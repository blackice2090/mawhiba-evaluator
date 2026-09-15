# Mawhiba Project Evaluator — Agent System Architecture v1.0
## Blueprint تنفيذي لوكيل تقييم مشاريع إبداع التقنية

**Status:** Proposed Production Architecture  
**Primary objective:** أعلى قدر ممكن من الثقة، القابلية للمراجعة، والامتناع عن الادعاء عند نقص الأدلة.  
**Current scope:** المشاريع التقنية والهندسية.  
**Default operating mode:** `EVALUATOR`  
**Future modes:** `MENTOR`, `JURY`, `RESEARCH`, `NOVELTY`, `METHODOLOGY`, `SCORE`

---

# 1. القرار المعماري الأساسي

هذا النظام **ليس Chatbot ببرومبت طويل**.

هو:

> **Evidence-driven, stateful evaluation workflow**

أي أن النظام يتكون من:
1. Workflow واضح ومحدد.
2. State دائم للمشروع.
3. أدوات بحث متخصصة.
4. سجل مصادر موثق.
5. Claim–Evidence Graph.
6. محرك تقييم deterministic.
7. Trust Gates تمنع إصدار أحكام أقوى من الأدلة.
8. Red Team مستقل.
9. Final Verifier قبل التقرير.
10. Tracing + Evals لاختبار الوكيل نفسه.

---

# 2. المبادئ غير القابلة للتفاوض

## 2.1 Zero Assumption
لا يتم ملء أي معلومة جوهرية من تخمين النموذج.

الحالات المسموحة لأي حقل:
- `KNOWN`
- `INFERRED_NON_CRITICAL`
- `UNKNOWN`
- `CONFLICTED`

الحقل الجوهري المفقود لا يتحول تلقائيًا إلى افتراض.

---

## 2.2 No Evidence → No Strong Claim
كل ادعاء مهم يجب أن يرتبط بـ `evidence_ids`.

إذا لم توجد أدلة كافية:
- `UNSUPPORTED`
- أو `PLAUSIBLE`

ولا يجوز رفعه إلى:
- `SUPPORTED`
- `VERIFIED`

دون دليل.

---

## 2.3 Search Before Novelty
ممنوع إصدار حكم قوي على الجدة قبل اكتمال البحث الملائم.

الجدة التقنية تفحص، حسب نوع المشروع، عبر:
- Academic Search
- Patent Search
- Product Search
- Open-source Search

---

## 2.4 Official Rules Override Internal Knowledge
قواعد المسابقة الحديثة من المصدر الرسمي أعلى من:
- المعرفة الداخلية للنموذج.
- النسخ القديمة من الأدلة.
- المدونات.
- الآراء الثانوية.

كل نسخة من متطلبات المسابقة تخزن مع:
- URL
- Retrieval timestamp
- Version / publication date إن وجدت
- Content hash

---

## 2.5 Evaluation ≠ Development
النسخة المقدمة من الطالب تحفظ كنسخة مستقلة:

`PROJECT_VERSION_N`

ثم يتم تقييمها كما هي.

لا يتم تحسينها قبل تثبيت:
- Score
- Findings
- Weaknesses
- Risks

---

## 2.6 Abstention is a Feature
من حق النظام أن يقول:

`INSUFFICIENT_EVIDENCE`

بدلاً من إعطاء نتيجة وهمية.

---

# 3. الـ Stack المقترح

| Layer | Technology | الدور |
|---|---|---|
| Frontend | Next.js + TypeScript | Dashboard + Chat + Reports |
| UI | Tailwind + shadcn/ui | واجهة مرنة وواضحة |
| Backend | FastAPI + Python | API + business logic |
| Workflow | LangGraph | State machine + checkpoints + parallel nodes |
| LLM API | OpenAI Responses API | reasoning + structured outputs + hosted tools |
| Main reasoning | GPT-5.6 Sol | Novelty, methodology, red team, synthesis |
| Mid-tier tasks | GPT-5.6 Terra | research analysis, ranking, extraction |
| High-volume tasks | GPT-5.6 Luna | classification, metadata, deduplication |
| Escalation verifier | GPT-6 Astra (optional) | arbitration للحالات عالية الحساسية |
| Academic | Consensus API | peer-reviewed academic retrieval |
| Academic graph | OpenAlex | metadata, citations, related works |
| Academic graph 2 | Semantic Scholar API | papers, citations, authors |
| Patents | EPO OPS | patent bibliographic/full-text/legal data |
| General web | OpenAI Web Search / Tavily | products, standards, official pages |
| Open source | GitHub API | repositories and implementations |
| DB | Supabase PostgreSQL | canonical state |
| Vector search | pgvector | semantic retrieval |
| Files | Supabase Storage + OpenAI File Search عند الحاجة | project documents |
| Tracing/Evals | Langfuse | traces, datasets, experiments |
| Deployment | Vercel + Railway/Render/Fly.io | frontend/backend |

---

# 4. لماذا LangGraph هو المنسق الرئيسي

نستخدم **LangGraph كـ workflow owner**.

ولا نجعل أكثر من runtime يدير state في النسخة الأولى.

السبب:
- checkpointing
- resume
- retries
- conditional routing
- parallel branches
- human interrupts
- state inspection
- fault recovery

OpenAI Responses API يستخدم داخل الـ Nodes.

يمكن إدخال OpenAI Agents SDK لاحقًا داخل Specialist مستقل إذا ظهر احتياج حقيقي، لكن **لا نخلط Orchestrators في v1** حتى لا يزيد التعقيد وصعوبة debugging.

---

# 5. High-Level Architecture

```text
                    ┌─────────────────────────┐
                    │      Student UI         │
                    │  Dashboard + Chat       │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │       FastAPI API       │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │      LangGraph Core     │
                    │ PROJECT_STATE + FLOW    │
                    └────────────┬────────────┘
                                 │
          ┌──────────────────────┼────────────────────────┐
          │                      │                        │
          ▼                      ▼                        ▼
 ┌────────────────┐    ┌───────────────────┐    ┌──────────────────┐
 │ Academic Branch│    │ Patent Branch     │    │ Market/OSS Branch│
 └───────┬────────┘    └─────────┬─────────┘    └────────┬─────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 ▼
                    ┌─────────────────────────┐
                    │ Evidence Normalization  │
                    │ + Source Quality        │
                    └────────────┬────────────┘
                                 ▼
                    ┌─────────────────────────┐
                    │ Prior Art + Novelty     │
                    └────────────┬────────────┘
                                 ▼
                    ┌─────────────────────────┐
                    │ Methodology / Experiments│
                    └────────────┬────────────┘
                                 ▼
                    ┌─────────────────────────┐
                    │ Claim–Evidence Engine   │
                    └────────────┬────────────┘
                                 ▼
                    ┌─────────────────────────┐
                    │ Red Team + Contradiction│
                    └────────────┬────────────┘
                                 ▼
                    ┌─────────────────────────┐
                    │ Trust Gate              │
                    └────────────┬────────────┘
                                 ▼
                    ┌─────────────────────────┐
                    │ Deterministic Score     │
                    └────────────┬────────────┘
                                 ▼
                    ┌─────────────────────────┐
                    │ Final Verifier          │
                    └────────────┬────────────┘
                                 ▼
                    ┌─────────────────────────┐
                    │ Evaluation Report       │
                    └─────────────────────────┘
```

---

# 6. Canonical PROJECT_STATE

```json
{
  "project_id": "uuid",
  "project_version_id": "uuid",
  "current_mode": "EVALUATOR",

  "identity": {
    "project_name": null,
    "project_type": "UNKNOWN",
    "domain": [],
    "language": "ar"
  },

  "problem": {
    "statement": null,
    "beneficiaries": [],
    "importance_claims": [],
    "validation_status": "UNKNOWN"
  },

  "solution": {
    "description": null,
    "technical_principle": null,
    "claimed_innovation": []
  },

  "technical": {
    "architecture": null,
    "hardware": [],
    "software": [],
    "sensors": [],
    "algorithms": [],
    "models": [],
    "datasets": []
  },

  "methodology": {
    "research_question": null,
    "hypothesis": null,
    "variables": [],
    "baseline": [],
    "metrics": [],
    "experimental_design": null,
    "statistics": null
  },

  "experiments": [],
  "results": [],
  "claims": [],
  "sources": [],
  "evidence": [],
  "prior_art": [],

  "novelty": {
    "level": null,
    "status": "NOT_EVALUATED",
    "confidence": null
  },

  "gap": {
    "research_gap": null,
    "engineering_gap": null,
    "status": "NOT_EVALUATED"
  },

  "risks": [],
  "scores": [],

  "missing_critical_information": [],
  "contradictions": [],

  "goal": null,
  "student_contribution": null,
  "current_stage": null
}
```

> **Amended in Phase 1C (ADR-004, ADR-005).**
>
> **Canonical intake fields.** `goal`, `student_contribution` and `current_stage`
> are top-level; `technical` additionally carries `technologies`,
> `data_sources` and `prototype_status`. Every field a verified intake
> extraction can produce now has a semantic owner, so no verified fact is
> discarded at merge.
>
> **Generic technologies.** `technical.technologies` is a first-class collection.
> A technology is frequently neither software nor hardware (LoRa, LiDAR, BLE,
> Edge Computing, Kalman Filtering, Digital Twin, ROS, FPGA); filing such items
> under `software` was a lossy misclassification that research routing would
> have inherited.
>
> **One domain taxonomy.** `identity.domain` uses the canonical
> `TechnicalDomain` enum (21 members), shared with the intake classifier. The
> earlier lossy projection between two taxonomies is removed; legacy spellings
> migrate through an explicit, tested table. See ADR-005.
>
> **Verbatim-first trust rule.** For canonical factual narrative fields the
> stored value is the verified source span from the student's submission, not an
> LLM paraphrase. The model locates the span; deterministic code decides whether
> it is accepted. The model's own phrasing is retained only as clearly labelled
> derived metadata. See ADR-004.
>
> **Gold evaluation requirement.** Before the research layer may consume intake
> output, a versioned Gold dataset must measure unsupported-known acceptance,
> invalid-provenance acceptance, student-claim leakage and prompt-injection
> mutation at **zero**, with a regression gate against an approved baseline
> (`evals/intake/`, `docs/phase1c_intake_evals.md`). This operationalizes the
> eval requirement of sections 32-34 for the intake layer.

> **Amended in Phase 1A.1 (ADR-002).**
>
> The original version of this section carried an operational `workflow` block
> (`completed_nodes`, `pending_nodes`, `blocked_reason`) inside `PROJECT_STATE`.
> It has been removed.
>
> Once LangGraph became the workflow owner (section 4), that block duplicated
> state the orchestrator must already track in order to checkpoint and resume,
> creating two mutable sources of truth for the same runtime facts.
>
> Ownership is now split:
>
> * `PROJECT_STATE` owns project and evaluation truth.
> * `EvaluationGraphState` owns workflow execution truth: workflow status,
>   current node, completed and pending nodes, node attempts, interrupt state,
>   workflow errors, run identifiers, and checkpoint/resume metadata.
>
> A UI needing progress information reads it from the workflow state or from a
> dedicated persisted workflow view, never from `PROJECT_STATE`. This keeps a
> versioned project snapshot (section 29) independent of the orchestration
> engine that produced it.
>
> See `docs/adr/ADR-002-workflow-state-ownership.md`.

---

# 7. Core Data Contracts

## 7.1 SourceRecord

```json
{
  "source_id": "SRC-001",
  "source_type": "ACADEMIC_PAPER",
  "title": "...",
  "authors_or_org": [],
  "year": 2026,
  "journal_or_venue": null,
  "doi": null,
  "url": "...",
  "provider": "CONSENSUS",
  "retrieved_at": "ISO-8601",
  "peer_review_status": "UNKNOWN",
  "query_id": "Q-01",
  "content_hash": "...",
  "quality": {
    "authority": 0.0,
    "relevance": 0.0,
    "methodological_strength": 0.0,
    "recency_fit": 0.0,
    "independent_validation": 0.0
  },
  "verification_status": "VERIFIED_METADATA"
}
```

---

## 7.2 EvidenceRecord

```json
{
  "evidence_id": "E-001",
  "source_id": "SRC-001",
  "evidence_type": "PRIOR_ART",
  "statement": "...",
  "support_direction": "SUPPORTS",
  "strength": "MODERATE",
  "location": {
    "page": null,
    "section": null,
    "quote_or_extract": null
  },
  "verified": true
}
```

---

## 7.3 ClaimRecord

```json
{
  "claim_id": "C-001",
  "claim": "النظام أكثر دقة من الحلول الحالية",
  "claim_type": "PERFORMANCE",
  "origin": "STUDENT",
  "status": "UNSUPPORTED",
  "evidence_ids": [],
  "counter_evidence_ids": [],
  "required_evidence": [
    "BASELINE",
    "TEST_DATA",
    "METRIC",
    "REPEATED_MEASUREMENTS"
  ],
  "missing_evidence": [],
  "confidence": 0.0
}
```

الحالات:
- `VERIFIED`
- `SUPPORTED`
- `PLAUSIBLE`
- `UNSUPPORTED`
- `CONTRADICTED`

---

## 7.4 PriorArtRecord

```json
{
  "prior_art_id": "PA-001",
  "source_id": "SRC-001",
  "kind": "ACADEMIC",
  "similarity_dimensions": {
    "problem": 0.0,
    "method": 0.0,
    "architecture": 0.0,
    "hardware": 0.0,
    "algorithm": 0.0,
    "deployment": 0.0,
    "evaluation": 0.0
  },
  "shared_features": [],
  "different_features": [],
  "novelty_threat": "HIGH",
  "review_notes": "..."
}
```

---

## 7.5 FindingRecord

```json
{
  "finding_id": "F-001",
  "category": "METHODOLOGY",
  "severity": "HIGH",
  "finding": "...",
  "reason": "...",
  "evidence_ids": [],
  "affected_claim_ids": [],
  "recommended_action_type": "REQUIRES_FIX",
  "confidence": "HIGH"
}
```

---

## 7.6 ScoreRecord

```json
{
  "score_id": "SC-001",
  "rubric_version": "ADVISORY-V1",
  "official": false,
  "axes": [
    {
      "axis": "novelty",
      "score": 0,
      "max_score": 15,
      "evidence_ids": [],
      "finding_ids": [],
      "completeness": 0.0,
      "confidence": "LOW",
      "provisional": true
    }
  ],
  "total": null,
  "status": "PROVISIONAL"
}
```

---

# 8. الـ Nodes التنفيذية

## N00 — Intake Guard

**الهدف**
- فحص المدخل.
- تحديد هل هو مشروع جديد أم متابعة.
- اكتشاف ملفات وروابط ونصوص.

**Input**
- User message
- Attachments
- Existing Project State

**Output**
- `INTAKE_PACKET`

**LLM**
- Luna

**Stop**
- فقط إذا كان المحتوى غير متعلق بمشروع أو لا يمكن فهم أي شيء منه.

---

## N01 — Project Extractor

يستخرج كل ما قدمه الطالب دون اختراع.

**Output**
- partial `PROJECT_STATE`
- list of missing critical fields
- conflicts

**LLM**
- Terra

**Rule**
كل قيمة مستخرجة تحمل:
- source: user/file
- certainty
- location/reference

---

## N02 — Project Type Classifier

يصنف:
- SCIENTIFIC_RESEARCH
- ENGINEERING_PROJECT
- HYBRID
- UNKNOWN

ويحدد المجال:
- AI/ML
- Software
- Robotics
- IoT
- Embedded
- Electronics
- HCI
- Cybersecurity
- etc.

**LLM**
- Luna/Terra

---

## N03 — Official Requirements Checker

يبحث فقط في المصادر الرسمية ذات العلاقة بالمسابقة.

**Output**
- requirements snapshot
- verified official criteria
- dates
- ethical constraints
- missing official data

**Trust rule**
إذا لم يجد وزنًا رسميًا:
`official_weight = null`

ولا يسمح للنظام باختراعه.

---

## N04 — Problem Validation

يتحقق من:
- حقيقة المشكلة.
- حجمها.
- المتأثرين.
- الحلول الحالية.
- قابلية القياس.

**Outputs**
- `REAL_PROBLEM`
- `ASSUMED_PROBLEM`
- `POORLY_DEFINED_PROBLEM`
- evidence ids

---

## N05 — Research Query Planner

ينتج Query Plan من عدة عائلات:

- Problem
- Existing solutions
- Technology
- Recent advances
- Limitations
- Benchmarks
- Reviews
- Alternatives
- Failure modes
- Patent function
- Patent principle
- Product terms
- Open-source implementation

**مهم**
لا يعتمد على اسم المشروع فقط.

---

# 9. Parallel Research Stage

بعد N05 تعمل الفروع بالتوازي.

```text
                   Research Plan
                        │
       ┌────────────────┼────────────────┐
       ▼                ▼                ▼
   Academic          Patents       Product / OSS
       │                │                │
       └────────────────┼────────────────┘
                        ▼
               Evidence Normalizer
```

---

## N06A — Academic Research

### Providers
1. Consensus
2. OpenAlex
3. Semantic Scholar
4. Official publisher pages عند الحاجة

### Responsibilities
- retrieve candidate papers
- metadata verification
- DOI verification
- find closest methods
- find reviews
- find negative/contradictory studies
- find strong baselines

### Output
`AcademicSource[]`

### Important
نتيجة Search وحدها ليست دليلًا نهائيًا.
يتم Fetch/verify metadata للمصادر المختارة قبل استخدامها.

---

## N06B — Patent Research

### Core
EPO OPS

### Additional search targets
- WIPO Patentscope
- USPTO
- Google Patents via browser/search when needed

### Query construction
- function
- mechanism
- technical principle
- synonyms
- CPC/IPC when identified

### Output
`PatentSource[]`

### Trust rule
لا نستنتج "لا توجد براءة" من صفر نتائج في Query واحدة.

---

## N06C — Product & Industry Research

### Sources
- official company websites
- product documentation
- standards bodies
- technical datasheets
- credible industry documentation

### Tools
- OpenAI Web Search
- Tavily Search
- Tavily Extract
- Tavily Crawl selectively

### Output
`ProductSource[]`

---

## N06D — Open Source Research

### Provider
GitHub API

### Checks
- similar repositories
- implementation age
- architecture similarity
- tutorial origin
- code reuse risk
- library vs contribution distinction

---

# 10. N07 — Source Normalization & Deduplication

يدمج النتائج ويزيل التكرارات بواسطة:

Academic:
- DOI exact match
- normalized title
- OpenAlex/S2 identifiers

Patents:
- family id
- publication number
- priority data

Products:
- canonical URL
- company + product identity

Repos:
- canonical repo id

**LLM**
Luna + deterministic code.

---

# 11. N08 — Source Quality Engine

يفضل أن يكون جزء كبير منه deterministic.

لكل مصدر:

```text
Authority
Relevance
Methodological Strength
Recency Fit
Independence
Verification Status
```

لا توجد معادلة عالمية ثابتة، لذلك لا نتعامل مع الرقم كـ "حقيقة علمية".

هو ranking داخلي.

## Source tiers

### TIER A
- official competition source
- peer-reviewed primary work شديد الصلة
- official standard
- patent record official

### TIER B
- systematic review
- strong conference
- official vendor documentation
- reputable preprint عند الحاجة

### TIER C
- GitHub
- secondary technical content
- credible industry commentary

### TIER D
- unverified blog/social content

**قاعدة**
Tier D لا يكفي وحده لحكم جوهري.

---

# 12. N09 — Closest Prior Art Engine

بدلاً من سؤال:
> هل يوجد نفس المشروع؟

نقارن أبعادًا متعددة:

- Problem
- Technical principle
- Method
- Architecture
- Algorithm
- Dataset
- Sensor configuration
- Hardware design
- Deployment context
- Validation method

ثم نحدد Top-K Closest Prior Art.

**Output**
- Top 3–10 closest works
- shared features
- differentiators
- novelty threats

---

# 13. N10 — Novelty Engine

## Novelty scale
- Level 0 — No Clear Novelty
- Level 1 — Known Application
- Level 2 — Adaptation
- Level 3 — Measurable Improvement
- Level 4 — Novel Combination
- Level 5 — Strong Novel Contribution

## Novelty Trust Gate

### لا يسمح بحكم Final إذا:
- Academic branch required لكنه فشل.
- Patent branch required لكنه فشل.
- closest prior art لم يُحدد.
- توجد critical contradiction غير محسومة.
- Search coverage منخفض.

### Level 4/5 يتطلب:
1. Academic search completed.
2. Patent search completed.
3. Product/OSS search completed عندما يكون ذا صلة.
4. Closest Prior Art identified.
5. Clear differentiator.
6. Evidence explaining why differentiator is technically meaningful.
7. No unresolved critical contradiction.
8. Confidence above configured threshold.

### إذا Patent Search غير مكتمل
أقصى حكم:
`PROVISIONAL NOVELTY`

ولا يقدم "Strong Novel Contribution" كحكم نهائي.

---

# 14. N11 — Gap Engine

لا يقبل:
- لم أجد نفس الاسم.
- لا يوجد تطبيق عربي.
- لم يستخدم أحد AI مثلي.

صيغة الـ Gap المقبولة:

```text
Existing solutions achieve X,
but exhibit limitation Y
under condition Z.
The project proposes A
to test whether Y can be improved,
measured using B.
```

**Output**
- Research Gap
- Engineering Gap
- evidence ids
- strength
- confidence

إذا غير مثبت:
`GAP_NOT_ESTABLISHED`

---

# 15. N12 — Methodology Specialist

Router حسب نوع المشروع.

## Research
- hypothesis
- variables
- controls
- sampling
- replication
- statistics
- bias
- validity

## Engineering
- requirements
- constraints
- design
- prototype
- testing
- measurement
- failure analysis
- iteration
- validation

## AI/ML specialist checklist
- dataset source
- labels
- splits
- leakage
- duplicates
- imbalance
- preprocessing
- baseline
- hyperparameters
- overfitting
- external validation
- metrics
- error analysis
- reproducibility

## Hardware/IoT
- sensor accuracy
- range
- resolution
- calibration
- noise
- sampling
- power
- latency
- repeatability
- fail-safe
- reference instrument

---

# 16. N13 — Experiment Reviewer

لكل تجربة:

```json
{
  "objective": "",
  "hypothesis": "",
  "setup": "",
  "inputs": [],
  "outputs": [],
  "variables": [],
  "controls": [],
  "baseline": [],
  "sample_size": null,
  "repetitions": null,
  "measurement_method": "",
  "metrics": [],
  "statistics": [],
  "error_sources": [],
  "success_criteria": [],
  "reproducibility": null
}
```

الوكيل يسأل:
> هل التجربة تثبت الادعاء أم فقط تثبت أن الجهاز يعمل؟

---

# 17. N14 — Claim–Evidence Engine

يستخرج كل claim مهم من:
- student description
- report
- poster
- results
- previous agent analysis

ثم يبني graph:

```text
CLAIM C1
 ├─ Evidence E4
 ├─ Evidence E8
 └─ Counter-Evidence E12
```

### مثال

Claim:
`النظام أدق`

Required:
- suitable baseline
- same evaluation setting
- test set
- suitable metric
- result

إذا لم توجد:
`UNSUPPORTED`

---

# 18. N15 — Contradiction Detector

يفحص التناقض بين:

- أقوال الطالب.
- ملفات الطالب.
- النتائج.
- المصادر الخارجية.
- أجزاء التقرير.
- نسخ المشروع.

أمثلة:
- Dataset size مختلف في موضعين.
- accuracy مختلفة.
- claim says external validation لكن التجربة داخلية.
- student says built algorithm بينما الكود يستخدم pretrained pipeline بلا تعديل.

كل contradiction:
- severity
- affected claims
- requires student clarification?

---

# 19. N16 — Red Team

Agent منفصل لا يرى الهدف على أنه "تحسين المشروع".

مهمته:
> حاول إثبات أن التقييم متفائل أكثر من اللازم.

يفحص:
- novelty threat
- stronger baseline
- simpler alternative
- hidden failure
- leakage
- unfair comparison
- insufficient sample
- unverifiable result
- tutorial-like project
- integration-only project
- inflated claims
- unclear student contribution

Output:
`TOP_3_RISKS`

مع:
- finding
- severity
- evidence
- impact
- remediation type

---

# 20. N17 — Deterministic Scoring Engine

**مهم جدًا:**
الـ LLM لا يجمع الدرجة النهائية.

الـLLM يعطي structured assessments.

Python يحسب Score.

## Rubric priority

### الحالة A
معايير رسمية حديثة ومتحقق منها:
`OFFICIAL_RUBRIC`

### الحالة B
لا توجد أوزان رسمية قابلة للتحقق:
`ADVISORY_RUBRIC`

Advisory v1:
- Problem & importance: 10
- Scientific/technical base: 10
- Literature: 10
- Novelty: 15
- Gap: 10
- Methodology: 15
- Experiments: 15
- Results: 10
- Jury defensibility: 5

## Scoring Gate

كل axis يحتوي:
- score
- evidence
- completeness
- confidence
- provisional flag

إذا critical inputs مفقودة:
- لا يصدر Full Final Score.
- يصدر `PROVISIONAL SCORE`.

---

# 21. N18 — Trust Gate

هذه أهم طبقة في النظام.

```json
{
  "search_coverage": 0.0,
  "source_quality": 0.0,
  "claim_traceability": 0.0,
  "contradictions_resolved": false,
  "critical_missing_count": 0,
  "novelty_search_complete": false,
  "methodology_review_complete": false,
  "score_status": "PROVISIONAL",
  "finalization_allowed": false
}
```

## Hard blockers

لا يتم Finalize إذا:
- Citation invented or unverified.
- DOI unverified and used as confirmed.
- critical contradiction unresolved.
- novelty search required but incomplete.
- required evidence is missing for a high-confidence claim.
- official rule is asserted without official evidence.

---

# 22. N19 — Final Verifier

Final Verifier لا يعيد تقييم المشروع من الصفر.

يقوم بمراجعة التقرير مقابل البيانات المنظمة.

Checks:
1. كل claim مهم له Evidence.
2. citations موجودة.
3. source metadata consistent.
4. no unsupported absolute claims.
5. score arithmetic correct.
6. official/advisory labels correct.
7. novelty wording matches confidence.
8. no contradiction between report sections.

### Model
GPT-5.6 Sol.

### Escalation
في الحالات شديدة الحساسية أو اختلاف المحللين:
GPT-6 Astra optional adjudicator.

---

# 23. N20 — Report Generator

التقرير لا يولد معلومات جديدة.

هو Presentation Layer فقط.

الأقسام:
1. Executive Summary
2. Project Understanding
3. Problem Validation
4. Literature & Similar Solutions
5. Closest Prior Art
6. Novelty
7. Gap
8. Methodology
9. Architecture
10. Data
11. Experiments
12. Results
13. Claim–Evidence Analysis
14. Red Team
15. Top 3 Risks
16. Strengths
17. Weaknesses
18. Score
19. Readiness
20. Improvement Priorities
21. Sources
22. Confidence / limitations of evaluation

---

# 24. متى يسأل الطالب؟

الوكيل لا يسأل عن كل missing field.

يسأل فقط عندما يكون:

`MISSING + CRITICAL + NOT_RETRIEVABLE_EXTERNALLY`

## Ask Examples
- كم عينة استخدمت؟
- ما Baseline الذي قارنت به؟
- هل Test Set مستقل؟
- ماذا نفذت بنفسك؟

## Do Not Ask
- ما شروط المسابقة؟ → يبحث رسميًا.
- ما أحدث الأبحاث؟ → يبحث.
- هل توجد منتجات مشابهة؟ → يبحث.

---

# 25. Human Interrupt Conditions

يستخدم LangGraph interrupt عندما:

### H1 — Critical missing student information
يمنع استمرار تقييم محور جوهري.

### H2 — Contradictory student evidence
يجب تحديد الصحيح.

### H3 — Ambiguous project interpretation
يوجد احتمال مرتفع لسوء فهم جوهر المشروع.

### H4 — Unsafe/ethical experimentation
يحتاج clarification قبل تقديم توصية.

### H5 — High-stakes finalization
اختياري في النسخة المؤسسية: مراجعة بشرية قبل اعتماد تقرير نهائي.

---

# 26. Model Routing

## Luna
- input classification
- simple extraction
- metadata cleaning
- dedupe candidate generation
- routing

## Terra
- paper summaries
- source relevance
- query expansion
- structured extraction
- preliminary methodology checks

## Sol
- closest prior art reasoning
- novelty
- gap
- methodology final review
- red team
- contradiction adjudication
- final verifier

## Astra — Optional
فقط:
- disputed novelty
- high-value final adjudication
- regression benchmark
- expert-level ambiguous cases

---

# 27. Research Coverage Policy

لكل Search Plan نسجل:

```json
{
  "query_id": "Q-001",
  "branch": "ACADEMIC",
  "query": "...",
  "provider": "CONSENSUS",
  "started_at": "...",
  "completed_at": "...",
  "result_count": 25,
  "selected_count": 7,
  "status": "COMPLETED"
}
```

ولا يعتبر الفرع "مكتملًا" بمجرد Query واحدة.

## Coverage completion
يجب أن يغطي:
- problem terms
- technology terms
- synonyms
- limitations/alternatives
- closest concept
- competing methods

Patent branch يضيف:
- function
- mechanism
- principle
- classification when available

---

# 28. Database Design

## Core
- `users`
- `projects`
- `project_versions`
- `project_state_snapshots`
- `project_files`

## Research
- `research_runs`
- `research_queries`
- `sources`
- `source_excerpts`
- `evidence`

## Evaluation
- `claims`
- `claim_evidence_links`
- `prior_art`
- `findings`
- `contradictions`
- `risks`
- `scores`
- `trust_gate_runs`
- `evaluation_runs`

## Outputs
- `reports`
- `report_versions`

## Jury
- `jury_sessions`
- `jury_questions`
- `jury_answers`
- `jury_scores`

## System
- `workflow_runs`
- `node_runs`
- `model_calls`
- `tool_calls`
- `audit_events`

---

# 29. Versioning

أي تعديل جوهري من الطالب ينشئ:

`PROJECT_VERSION`

ولا يمسح التقييم السابق.

مثال:

```text
Project
├─ v1 → Score 61
├─ v2 → Score 73
└─ v3 → Score 84
```

يمكن مقارنة:
- novelty
- methodology
- evidence
- risks
- score
- readiness

---

# 30. API Surface المقترح

```text
POST   /projects
GET    /projects/{id}

POST   /projects/{id}/files
POST   /projects/{id}/messages

POST   /projects/{id}/evaluate
GET    /projects/{id}/evaluation/{run_id}

GET    /projects/{id}/state
GET    /projects/{id}/sources
GET    /projects/{id}/claims
GET    /projects/{id}/prior-art
GET    /projects/{id}/risks
GET    /projects/{id}/score

POST   /projects/{id}/resume
POST   /projects/{id}/jury

GET    /projects/{id}/report
POST   /projects/{id}/versions
GET    /projects/{id}/compare
```

---

# 31. Repo Structure

```text
mawhiba-evaluator/
│
├─ apps/
│  ├─ web/
│  └─ api/
│
├─ src/
│  ├─ graph/
│  │  ├─ state.py
│  │  ├─ router.py
│  │  ├─ graph.py
│  │  └─ nodes/
│  │
│  ├─ agents/
│  │  ├─ academic.py
│  │  ├─ patents.py
│  │  ├─ methodology.py
│  │  ├─ novelty.py
│  │  ├─ red_team.py
│  │  └─ verifier.py
│  │
│  ├─ tools/
│  │  ├─ consensus.py
│  │  ├─ openalex.py
│  │  ├─ semantic_scholar.py
│  │  ├─ epo_ops.py
│  │  ├─ web_search.py
│  │  ├─ tavily.py
│  │  └─ github.py
│  │
│  ├─ schemas/
│  │  ├─ project.py
│  │  ├─ source.py
│  │  ├─ evidence.py
│  │  ├─ claim.py
│  │  ├─ prior_art.py
│  │  ├─ finding.py
│  │  └─ score.py
│  │
│  ├─ scoring/
│  ├─ trust/
│  ├─ reports/
│  └─ db/
│
├─ evals/
│  ├─ datasets/
│  ├─ evaluators/
│  └─ experiments/
│
└─ tests/
```

---

# 32. Evals — كيف نقيس ثقة الوكيل نفسه؟

لن نعتمد على الانطباع.

ننشئ Gold Dataset بمراجعة بشرية.

## Initial benchmark
50–100 مشروع/حالة موزعة على:
- AI
- IoT
- Robotics
- Software
- Embedded
- Electronics

تشمل intentionally:
- known idea
- strong novelty
- tutorial implementation
- data leakage
- weak baseline
- fake/invalid citation attempt
- patent conflict
- inflated claim
- missing data
- conflicting numbers
- inappropriate metric
- tiny sample size

---

# 33. Metrics للوكيل

## Citation integrity
- Hallucinated citation rate
- Broken DOI rate
- Source traceability

**Target:**
Hallucinated confirmed citations = 0

## Novelty safety
- False strong-novelty rate
- Closest-prior-art recall
- patent-threat detection

## Methodology
- critical issue recall
- false issue rate
- leakage detection
- baseline detection

## Claims
- unsupported claim detection
- evidence linking accuracy

## Scoring
- arithmetic correctness = 100%
- same-evidence repeatability
- human evaluator agreement

## Behavior
- unnecessary question rate
- missed critical question rate
- abstention correctness

---

# 34. Regression Testing

أي تعديل في:
- prompt
- model
- tool
- search provider
- scoring rubric
- routing

يعمل على نفس Eval Dataset.

نسجل:
- git commit
- prompt version
- model version
- dataset version
- evaluator version

ولا ننشر التعديل إذا تسبب في regression على Metrics الحرجة.

---

# 35. Observability

كل Evaluation Run له Trace.

نسجل:
- node
- model
- prompt version
- inputs hash
- outputs
- tools
- sources
- latency
- tokens
- cost
- retries
- errors

لكن لا نظهر Chain-of-Thought الداخلي للمستخدم.

نعرض بدلاً منه:
- evidence
- rationale مختصر
- decision factors
- source links

---

# 36. Security & Privacy

## Principles
- أقل قدر من PII.
- فصل ملفات الطلاب منطقيًا.
- Row Level Security.
- signed storage URLs.
- secrets في server env فقط.
- API keys لا تصل للfrontend.
- audit logs.
- rate limits.
- file type/size validation.

## Research privacy
عند إرسال query لمحرك خارجي:
لا نرسل اسم الطالب أو معلومات شخصية إذا لم تكن لازمة للبحث.

---

# 37. ما لا نستخدمه كـ Core

## n8n
مفيد للأتمتة والإشعارات، وليس العقل الأساسي للتقييم.

## Dify
ممتاز لـ prototype، لكن لا أجعله canonical state + trust engine للمنتج النهائي.

## Flowise
مفيد للتجارب البصرية، لكن الـ production core يبقى code-first.

## Custom GPT
مفيد لاختبار تجربة الحوار فقط، وليس محرك التقييم الرسمي.

---

# 38. مراحل التنفيذ

## Phase 0 — Contracts First
نبني:
- schemas
- state
- trust policy
- scoring policy
- test fixtures

**لا واجهة بعد.**

### Definition of Done
كل Node له:
- input schema
- output schema
- failure mode
- test

---

## Phase 1 — Headless Evaluation Core

يقبل JSON لمشروع واحد.

ينفذ:
- intake
- project understanding
- problem validation
- research
- prior art
- novelty
- methodology
- claim-evidence
- red team
- score
- final verifier

ويخرج:
`evaluation.json`

### Definition of Done
تقييم كامل قابل للتتبع إلى مصادره.

---

## Phase 2 — Research Connectors

ربط:
- Consensus
- OpenAlex
- Semantic Scholar
- EPO OPS
- Web Search/Tavily
- GitHub

### Definition of Done
كل source له canonical metadata + provenance.

---

## Phase 3 — Trust Engine + Evals

- Trust Gate
- contradiction detector
- citation verifier
- regression dataset
- Langfuse experiments

### Definition of Done
لا يوجد تقرير Final إذا فشل Trust Gate.

---

## Phase 4 — Platform UI

- auth
- dashboard
- project files
- chat
- research tab
- evidence tab
- score tab
- report

---

## Phase 5 — Jury Mode

- adaptive questions
- 3 levels
- answer scoring
- weaknesses-driven questions
- final jury report

---

## Phase 6 — Mentor Mode

بعد ثبات Evaluator.

لا يغير تاريخ التقييم.

يولد:
- improvement options
- decision matrix
- architecture suggestions
- experiment plan
- re-evaluation

---

# 39. Acceptance Criteria للنسخة الأولى

لن أعتبر v1 ناجحة إلا إذا:

1. كل حكم Novelty له مصادر.
2. كل مصدر مؤكد قابل للتحقق.
3. لا يتم اختراع DOI.
4. كل Claim أساسي له status.
5. أي Claim بلا دليل يظهر بوضوح.
6. أقرب Prior Art يظهر قبل الحكم على Novelty.
7. Patent Search status ظاهر.
8. المنهجية تفحص حسب نوع المشروع.
9. Red Team مستقل.
10. score يحسب بالكود.
11. official vs advisory واضح.
12. confidence ظاهر.
13. unresolved contradictions تمنع Finalization.
14. Search log محفوظ.
15. كل Report يمكن إعادة بناء سببه من البيانات المنظمة.
16. كل تغيير في Prompt يختبر على Eval Dataset.

---

# 40. Definition of Trusted Result

نعتبر النتيجة `TRUSTED_FINAL` فقط عندما:

```text
Official requirements checked
AND
Required research branches completed
AND
Sources verified
AND
Closest prior art identified
AND
Claims mapped to evidence
AND
Critical contradictions resolved
AND
Methodology review complete
AND
Red team complete
AND
Score deterministic
AND
Final verifier passed
```

وإلا:

`PROVISIONAL`

أو:

`INSUFFICIENT_EVIDENCE`

---

# 41. الخلاصة التنفيذية

أفضل بنية للمشروع ليست Multi-Agent مفتوحة بلا قيود.

الأفضل:

> **Workflow deterministic في الخارج + LLM intelligence داخل Nodes + evidence-first data model + Trust Gates + Evals.**

المنسق:
**LangGraph**

العقل:
**OpenAI Responses API**

البحث العلمي:
**Consensus + OpenAlex + Semantic Scholar**

البراءات:
**EPO OPS + targeted patent search**

السوق:
**Web Search / Tavily**

Open Source:
**GitHub**

قاعدة البيانات:
**Supabase PostgreSQL + pgvector**

الجودة:
**Langfuse + Gold Eval Dataset**

---

# 42. أول خطوة برمجية مباشرة

ابدأ بهذا الترتيب فقط:

```text
01 schemas/
02 project_state
03 graph skeleton
04 intake node
05 project extractor
06 research planner
07 academic connector
08 source normalization
09 claim-evidence engine
10 trust gate
11 deterministic scorer
12 evaluation tests
```

ثم نضيف Patent/Product/Open-source branches.

السبب:
نثبت **Contracts + Evidence model + State** أولاً، لأن إعادة تصميمها لاحقاً هي أكثر شيء يسبب فوضى في أنظمة الـAgents.

---

# 43. القرار النهائي

**Architecture Recommendation: APPROVED FOR IMPLEMENTATION**

مع مبدأ رئيسي:

> جودة هذا المنتج لن تقاس بمدى جمال رد الـAI، بل بمدى قدرة أي شخص على السؤال:
> **"لماذا أعطيت هذا الحكم؟"**
> ثم يحصل على الأدلة، المصادر، درجة الثقة، وما الذي كان ناقصًا، خطوة بخطوة.

هذا هو معيار الثقة الذي يجب أن نبني عليه النظام.
