# Distill: Backend Implementation Plan

**Companion to:** `requirements.md`, `implementation.md`
**Author:** Anubhav, with Claude
**Date:** September 3, 2026
**Status:** Plan v2, reviewed. Review findings in section 8 are folded in.
**Scope:** the complete backend slice, so that frontend work can begin against a stable
and typed contract. Frontend work is explicitly out of scope for this plan.

---

## 1. What changed from `implementation.md`, and why

Four decisions were taken after verifying the machine and the package registry. Each has a
corresponding entry in `decisions.md`.

| # | Change | Reason |
| --- | --- | --- |
| D12 | Dependency management is `uv`, not pip or Poetry | The stack needs a locked, reproducible dependency set and `uv` also installs and pins the Python interpreter itself, which removes a class of "works on my machine" failure from the one-command setup story |
| D13 | Large Language Model provider is Gemini, behind a provider protocol, with a **fake provider** as a first-class implementation | No Gemini key exists yet and the provider is explicitly not finalised. A protocol plus a deterministic fake means the entire pipeline is buildable and testable today, and it is also the recorded fixture that requirement in section 9 of `implementation.md` asks for in the end-to-end test |
| D14 | Server-Sent Events are **persisted** to a `workspace_events` table | Section 5.1 of `implementation.md` requires `Last-Event-ID` resume. Resume is impossible without a replayable log, so the event log becomes a table rather than in-memory state. This also makes the processing timeline in the user interface queryable rather than ephemeral |
| D15 | Sample documents are supplied by Anubhav and discovered through a `samples/manifest.json` | Anubhav is providing real documents. The seed endpoint therefore reads a manifest instead of hard-coding filenames, so dropping files into `samples/` is the only step needed |

Everything else in `implementation.md` sections 2.2, 4, 5, and 6 is followed as written:
Python 3.12 with FastAPI, Postgres 16 through async SQLAlchemy 2.0 and Alembic, pdfplumber
plus pypdfium2 for word geometry and page rendering, Tesseract for scanned pages,
`sse-starlette` for streaming, an in-process asyncio worker queue, and structlog with a
correlation identifier on every log line.

---

## 2. The four properties this backend has to guarantee

Everything below is in service of these. If a phase threatens one of them, the phase gets
cut, not the property.

1. **Every value is traceable.** A field value without provenance is a defect, not a
   degraded result. Where grounding fails, the value still carries a reason for the failure
   and its confidence tier is capped at low.
2. **A human correction is never lost.** Enforced at the database layer, not by convention,
   through `WHERE status <> 'human_verified'` on every write path that a model can reach.
3. **A failing document never breaks the collection.** Per-document status and failure
   reason, isolated failure, and the rest of the workspace stays usable.
4. **Generated SQL cannot do damage.** Defence in depth: a parse-level allow-list, a
   per-workspace view as the only readable relation, a Postgres role with `SELECT` only,
   a five second statement timeout, and an injected row limit.

---

## 3. Directory layout

`server/` replaces the `api/` name in `implementation.md` section 3.

```
server/
├── pyproject.toml            deps, tool config (ruff, mypy, pytest)
├── uv.lock                   committed
├── .python-version           3.12
├── alembic.ini
├── Dockerfile
├── app/
│   ├── main.py               app factory, middleware, router mounting
│   ├── config.py             pydantic-settings, one source of env truth
│   ├── logging.py            structlog config + correlation id middleware
│   ├── errors.py             typed error envelope, every response carries request_id
│   ├── deps.py               dependency injection: db session, workspace auth
│   │
│   ├── domain/               pure types, no input or output, no database
│   │   ├── fields.py         FieldType, FieldSpec, FieldValue, Tier, ValueStatus
│   │   ├── document.py       ParsedDocument, ParsedPage, Word, Line, BBox
│   │   ├── provenance.py     Provenance, ProvenanceKind
│   │   └── events.py         the Server-Sent Events vocabulary, one source of truth
│   │
│   ├── db/
│   │   ├── models.py         SQLAlchemy models
│   │   ├── session.py        async engine, session factory, read-only engine
│   │   └── migrations/       alembic versions
│   │
│   ├── storage/
│   │   ├── base.py           Storage protocol
│   │   └── local.py          filesystem implementation
│   │
│   ├── llm/
│   │   ├── base.py           LLMClient protocol, Completion, Usage
│   │   ├── gemini.py         Gemini through Instructor
│   │   ├── fake.py           deterministic, fixture-driven, no network
│   │   ├── registry.py       config -> client
│   │   └── prompts/          versioned prompt templates as files, not string literals
│   │
│   ├── pipeline/
│   │   ├── sniff.py          content type from bytes
│   │   ├── parse/
│   │   │   ├── router.py     mime -> parser
│   │   │   ├── pdf.py        pdfplumber words + pypdfium2 renders + OCR fallback
│   │   │   ├── image.py      Tesseract
│   │   │   ├── docx.py       paragraphs
│   │   │   ├── sheet.py      xlsx and csv, cell ranges
│   │   │   └── text.py       line offsets
│   │   ├── extract.py        open and schema-guided extraction
│   │   ├── ground.py         quote -> bounding box
│   │   ├── score.py          derived confidence tiers
│   │   └── worker.py         asyncio queue, per-document task, retries
│   │
│   ├── schema/               the USER'S FIELD SCHEMA feature. Not request models.
│   │   │                     See review finding 8.10: there is no `schemas/` directory.
│   │   ├── propose.py        initial unified schema proposal
│   │   ├── drift.py          extra field -> map, add, or ignore candidates
│   │   ├── versioning.py     apply, revert, history
│   │   ├── backfill.py
│   │   └── view.py           per-workspace typed view generation
│   │
│   ├── query/
│   │   ├── nl2sql.py
│   │   ├── guard.py          sqlglot allow-list
│   │   ├── execute.py        read-only engine, timeout, row cap
│   │   └── present.py        result shape -> Agent-to-User Interface messages
│   │
│   ├── a2ui/
│   │   ├── builders.py       createSurface, updateComponents, updateDataModel
│   │   ├── catalog.py        component names and property contracts
│   │   └── validate.py       validation of every emitted message
│   │
│   ├── events/
│   │   ├── bus.py            in-process publish and subscribe, plus persistence
│   │   └── sse.py            streaming response, heartbeat, Last-Event-ID replay
│   │
│   └── routers/
│       ├── health.py workspaces.py documents.py records.py schema.py
│       ├── query.py events.py actions.py export.py client_events.py
│
└── tests/
    ├── conftest.py           test database, fake provider, fixture documents
    ├── unit/                 ground, score, guard, sniff, view, drift, a2ui
    └── integration/          upload to rows, corrections survive re-extraction, resume
```

Two rules that keep this clean as it grows:

- **`domain/` imports nothing from `db/`, `routers/`, or `llm/`.** Types flow inward.
  This is what lets the grounding and scoring logic be unit tested with no database.
- **A router never contains logic.** It validates input, calls one function, and shapes
  output. Everything testable lives in `pipeline/`, `schema/`, or `query/`.
- **Request and response models are declared in the router that owns them.** Only types
  shared across features live in `domain/`. There is deliberately no `schemas/` directory,
  because that word already means the user's field schema in this project.

---

## 4. Phases, with a checkpoint at every boundary

Each phase ends in something demonstrable. Nothing moves to the next phase until the
checkpoint passes.

### Phase 0: Verify before building (target: 1 hour)

The day-1 checklist in `implementation.md` section 13, restricted to backend items. This
phase exists because three things in the plan are currently assumptions.

- [ ] Python 3.12, Postgres 16, Tesseract, and `uv` installed and on the path
- [ ] Postgres cluster running, `distill` and `distill_test` databases created, `distill_readonly`
      role created with `SELECT` only
- [ ] **pdfplumber word coordinate origin asserted against a real PDF fixture.** This is
      the single highest-risk assumption in the whole provenance design. Section 8.3 of
      `implementation.md` assumes pdfplumber already flips the bottom-left origin of the
      PDF format. A failing test here changes the overlay mathematics on both sides
- [ ] `pypdfium2` renders a page to PNG at 144 dots per inch, and the pixel dimensions
      relate to the point dimensions by exactly the expected scale factor
- [ ] Instructor's Gemini client signature and the current Gemini model identifiers
      confirmed. **Cannot be fully verified without a key.** The fake provider means this
      does not block anything, and the gap is recorded explicitly

**Checkpoint:** a `tests/unit/test_pdf_geometry.py` that passes and encodes the coordinate
convention as an executable assertion rather than a comment.

### Phase 1: Skeleton and contracts (target: 3 hours)

- Configuration through `pydantic-settings`, one class, every environment variable declared
  with a type and a default. `LLM_PROVIDER`, `LLM_EXTRACT_MODEL`, `LLM_FAST_MODEL`,
  `GEMINI_API_KEY`, `DATABASE_URL`, `DATABASE_URL_READONLY`, `STORAGE_DIR`, `MAX_UPLOAD_MB`
- structlog with a correlation identifier middleware. Every log line and every error
  response body carries `request_id`, which the frontend shows in error toasts
- A single error envelope: `{error: {code, message, detail?, request_id}}`. No route ever
  leaks a raw exception or a database error
- All SQLAlchemy models and the first Alembic migration, matching `implementation.md`
  section 4 plus the `workspace_events` table from decision D14
- The domain types, including the Server-Sent Events vocabulary as Pydantic models so the
  generated OpenAPI document carries them and the frontend client is typed from them
- Workspace creation and bearer token authentication. Token is 32 random bytes, url-safe
  encoded, returned once, stored only as a SHA-256 hash
- `/healthz` reporting database reachability, storage writability, and whether a Large
  Language Model key is present (never its value)

**Checkpoint:** `uv run alembic upgrade head` succeeds against a real Postgres, `/healthz`
returns green, a workspace can be created and authenticated, and
`uv run python -m app.openapi > openapi.json` writes a document the frontend can generate
types from.

### Phase 2: Ingest and parse (target: 4 hours)

- Multipart upload of many files. Content type sniffed from the first bytes and validated
  against the extension, per the security requirement in section 5 of `requirements.md`.
  Size and type rejected before any bytes are stored
- Original bytes to storage, page renders to storage, both behind the `Storage` protocol
- The seven parsers, all producing the same `ParsedDocument`. Provenance kind varies by
  format: a bounding box for PDF and images, a paragraph index for DOCX, a cell range for
  spreadsheets, a line span for plain text
- Byte-range support on the original file route, because pdf.js in the viewer requests
  ranges
- Scanned page detection: fewer than five words on a page triggers Tesseract on the render

**Checkpoint:** one integration test per supported format uploads a fixture and asserts the
shape of the resulting `ParsedDocument`, including that a scanned PDF fixture goes down the
Optical Character Recognition path and still produces word boxes.

### Phase 3: Extract, ground, score (target: 5 hours)

This is the core of the pipeline and where the trust property is won or lost.

- `LLMClient` protocol with `GeminiClient` and `FakeClient`. The fake reads from
  `tests/fixtures/llm/` keyed by a hash of the prompt, so it is deterministic and it
  records new interactions when a real key is present
- Open extraction for the first batch, schema-guided extraction thereafter. The
  schema-guided response model is built at runtime from the stored field specifications
  with `pydantic.create_model`, with an `extra_fields` list that feeds drift detection
- Grounding exactly as specified in section 6.3: normalise, sliding-window fuzzy match with
  RapidFuzz at a threshold of 85, union of matched word boxes, one box per line when a
  quote wraps, neighbouring-page retry, and a null box with a recorded reason on failure
- Scoring exactly as the table in section 6.4. The tier is **derived**, never taken from
  the model
- The asyncio worker queue: bounded concurrency, three attempts with backoff, a per-document
  status machine, and an event published at every stage transition
- Records and field values persisted, one row per record and field pair

**Checkpoint:** the integration test that matters most. Upload the fixture set with the fake
provider, and assert: rows appear, every value has either a bounding box or a recorded
grounding failure, tiers match the table, a deliberately hallucinated value in the fixture
lands in the low tier because its quote cannot be grounded, and a deliberately failing
document is marked failed while every other document completes.

### Phase 4: Schema proposal, drift, versioning, corrections (target: 5 hours)

- Initial proposal from the first batch, validated so that every source key maps to exactly
  one canonical field, emitted as an Agent-to-User Interface surface
- Drift detection on `extra_fields`, scored by label and description similarity together
  with type compatibility, producing map, add, or ignore candidates above and below the
  0.8 threshold
- Applying a decision creates a new schema version, regenerates the per-workspace typed
  view, and enqueues backfill when fields were added
- Backfill runs schema-guided extraction restricted to the new fields and never touches a
  human-verified row
- Human corrections: value or not-present, marked human-verified, published as an event
- Re-extraction honours human-verified values and raises a conflict tier when the model
  now disagrees
- Version history and one-click revert

**Checkpoint:** two integration tests. First, a heterogeneous batch produces a drift
proposal rather than a broken table, and applying a mapping lands the value in the existing
column. Second, and this is the guarantee in principle 4 of `requirements.md`: correct a
value, re-extract the document, and assert the human value survived and a conflict flag was
raised.

### Phase 5: Query (target: 4 hours)

- Natural language to SQL, given the view's column list with types and three sample rows,
  returning SQL, an explanation, and a presentation hint
- The guard: parse with sqlglot, reject anything that is not a single `SELECT`, reject any
  relation other than this workspace's view, inject `LIMIT 500`
- Execution on the read-only engine with a five second statement timeout
- Presentation: Agent-to-User Interface messages, where the presentation hint is overridden
  when the data shape contradicts it, exactly as section 6.4 of `implementation.md` requires
- One repair attempt on invalid SQL, then a message surface explaining what was tried
- Action round-trip endpoint, and export to CSV and JSON respecting filters

**Checkpoint:** guard unit tests reject an `UPDATE`, statement chaining with a semicolon, a
reference to a base table, and a common table expression that reaches outside the view. A
query integration test asserts that a single numeric row produces a metric surface and that
31 rows never produce a bar chart.

### Phase 6: Hardening and setup (target: 3 hours)

- Server-Sent Events resume: events after a given `Last-Event-ID` replay exactly once.
  Heartbeat every 15 seconds. `X-Accel-Buffering: no` and `Cache-Control: no-cache` on
  every streaming response, and streaming routes excluded from compression
- Every emitted Agent-to-User Interface message validated in tests
- `docker-compose.yml`, `Dockerfile`, and `Makefile` with `dev`, `test`, `migrate`, `seed`
- README and `decisions.md` brought current

**Checkpoint:** the full test suite green, and the setup path documented honestly, including
that Docker could not be smoke-tested on this machine.

---

## 5. Honest schedule assessment

Phases 0 through 6 total roughly 25 hours of focused work, which is two and a half days
against a four to five day window where the frontend is the graded surface and needs at
least two and a half days of its own. **This plan does not fit without a cut.**

The cut order, decided now rather than in a panic on day 4:

| Order | Cut | Consequence |
| --- | --- | --- |
| 1 | Backfill (`FR-14`, a Should) | Adding a field leaves existing rows empty until re-extraction is triggered manually |
| 2 | Schema revert (`FR-15`, a Should) | History is visible but read-only |
| 3 | Export (`FR-24`, a Should) | Data portability claim weakens |
| 4 | DOCX and spreadsheet parsers | Heterogeneity story shrinks to PDF, image, and text. **Only if Anubhav's real documents are all PDF** |
| 5 | The repair attempt on invalid SQL | A bad query fails once instead of retrying |

Nothing above the line is cuttable: parse, extract, ground, score, propose, drift,
corrections with the never-lose guarantee, and the guarded query path are the submission.

---

## 6. Test strategy, and what it deliberately does not cover

Following section 9 of `implementation.md`. Tests are chosen for failures we would actually
hit.

**Unit, no database, no network:** grounding across casing, currency formatting, line
wraps, an off-by-one page citation, and an ungroundable quote. Scoring as a parametrised
table. Drift detection on a rename, a type conflict, and a genuinely new field. The SQL
guard on each rejection class. Content sniffing on a file whose extension lies. Per-workspace
view generation. Agent-to-User Interface message validity.

**Integration, real Postgres, fake Large Language Model provider:** upload to rows for every
format, a correction surviving re-extraction, event resume replaying exactly once, and a
failing document leaving the collection usable.

**Not covered, and stated rather than hidden:** real Gemini call quality, because there is no
key yet. Provider behaviour is exercised only through the fake. The moment a key exists, the
fake's record mode captures real interactions and the same tests run against them.

---

## 7. Open questions

Blocking nothing. To be resolved in `decisions.md` as answers arrive.

1. **Gemini model identifiers and the final provider.** Configuration-driven, so this is a
   one-line change. Needs a key before it can be verified.
2. **Confidence method.** `implementation.md` derives the tier from grounding success plus
   model self-report. A second extraction pass would give genuine agreement scoring but
   doubles cost and latency. Currently planned as a per-document "double-check" action
   rather than a default, per seed decision 5.
3. **Whether the sample documents are all PDF.** Determines whether the DOCX and spreadsheet
   parsers are load-bearing for the demo or merely defensive. Affects cut order item 4.
4. **Page image storage versus rendering on demand.** Currently storing renders, because
   the viewer needs them immediately and storage is cheap at this scale. Open question 3 in
   section 10 of `requirements.md`.
5. **Whether Docker gets installed.** The compose path can be authored correctly but not
   smoke-tested on this machine, and acceptance criterion 8 depends on it.

---

## 8. Plan review, and the defects it found

The plan above was reviewed against the requirements before any code was written. Nine
defects were found. Four of them would have produced bugs rather than merely friction, and
they are marked accordingly. All are folded into the plan and are called out here because
each one is a decision worth seeing.

### 8.1 Field keys reaching a `CREATE VIEW` statement, unvalidated (bug)

The per-workspace typed view aliases each field key as a column name. Field keys originate
from a Large Language Model proposal. A proposed key containing a quotation mark or a
semicolon is therefore a data definition language injection, executed with the privileges of
the application role.

**Fix:** a field key is a domain invariant, not a string. It must match
`^[a-z][a-z0-9_]{0,46}$` and must not collide with a reserved word, validated at the moment
a proposal is applied and again in the view generator. Identifiers are additionally quoted
through the dialect's own quoting rather than by string interpolation. A unit test asserts
that a malicious proposed key is rejected at the boundary and never reaches SQL.

### 8.2 The read-only role has no grant on a newly generated view (bug)

Views are regenerated on every schema version change. A new view is owned by the application
role and the read-only role has no privilege on it, so the very first query after any schema
change would fail with a permission error rather than returning rows.

**Fix:** view regeneration and `GRANT SELECT ... TO distill_readonly` are one transaction, and
an integration test changes the schema and then immediately runs a query.

### 8.3 A race between replay and live subscription on reconnect (bug)

Resume was specified as "replay from `Last-Event-ID`, then stream live". Any event published
between the end of the replay read and the start of the live subscription is lost, which is
exactly the failure the resume requirement exists to prevent.

**Fix:** the order is inverted. Subscribe to the live bus first and buffer, then read the
replay range from the table, then emit the replay, then emit the buffer with any sequence
number already emitted discarded. The integration test asserts exactly-once delivery while
publishing concurrently with a reconnect, rather than in a quiet window.

### 8.4 The conflict tier has nowhere to store the value it conflicts with (bug)

Requirement FR-34 says re-extraction may add a "model now disagrees" flag. Section 4 of
`implementation.md` has one `value` column, so recording that the model disagrees loses
*what* the model said, and the frontend cannot show the user the two candidates side by side.

**Fix:** `field_values` gains `model_value jsonb NULL` and `model_value_at timestamptz NULL`.
The human value stays in `value`, and the disagreeing model value is retained beside it.
This is decision D16.

### 8.5 No rule for when the initial schema proposal fires

"Propose from the first batch" is not implementable as written, because a batch is not
defined. Uploading three files and then five more leaves it ambiguous, and the worker would
race to propose a schema from whichever document finished first.

**Fix:** the proposal fires when a workspace has no schema version **and** the count of
documents in a non-terminal state reaches zero, debounced by 500 milliseconds to absorb
staggered uploads. Until it fires, completed documents hold their open-extraction output and
no records are created. This is stated in the plan rather than left to the worker.

### 8.6 The fake provider was keyed by prompt hash, which is brittle

Keying recorded responses on a hash of the prompt means every prompt edit invalidates every
fixture, so the test suite would break on prompt tuning, which is the most frequent kind of
change this project will make.

**Fix:** the fake provider is scenario-keyed by document content hash and call kind, not by
prompt text. Prompt edits leave the suite green, while a change to what a document *is*
correctly forces a fixture update.

### 8.7 Dynamic response models risk exceeding what Gemini's structured output accepts

Building the schema-guided response model with `pydantic.create_model` can generate nested
definitions, references, and unions. Gemini's structured output support is narrower than the
full JSON Schema specification, so a schema that validates locally can be rejected remotely.

**Fix:** generated models are constrained to a flat shape by construction. No unions, one
level of nesting only for the currency object, absence represented as null rather than as an
optional union, and a serialiser test asserts the generated schema stays inside the accepted
subset. This is verifiable only against a real key, so it is a recorded gap.

### 8.8 The upload size limit trusted `Content-Length`

Rejecting oversized files "before any bytes are stored" was specified against the declared
length, which a client controls and can understate.

**Fix:** the limit is enforced by counting bytes while streaming to a temporary file and
aborting the moment the limit is passed, with the declared length used only as a fast
pre-check.

### 8.9 Three routes in the contract appeared in no phase

`POST /workspaces/{id}/seed`, `GET /workspaces/{id}/records` with cursor pagination, and
`POST /api/v1/client-events` were in the API contract but in no phase, so they would have
been discovered as missing during frontend work.

**Fix:** seed and paged records join Phase 2 and Phase 3 respectively, and the client event
sink joins Phase 6.

### 8.10 A naming collision that would have confused every future reader

The plan had `app/schemas/` for the workspace schema feature, while the near-universal
FastAPI convention uses `schemas/` for request and response models. Two different meanings
of the same word in one tree is a permanent tax on comprehension.

**Fix:** the feature directory is `app/schema/` (singular, as `implementation.md` has it) and
means only "the user's field schema". Request and response models are declared at the top of
the router that owns them, and shared types live in `app/domain/`. There is no `schemas/`
directory. This convention is recorded at the top of `app/domain/__init__.py`.

### 8.11 Single-process constraint is now explicit

The in-process event bus and asyncio worker queue mean the API must run with exactly one
worker process. Running two would split the bus and silently deliver each event to only the
subscribers that happen to share a process.

**Fix:** the worker count is pinned to one in the Dockerfile, the compose file, and the
Makefile, with a comment at each site explaining why, and `/healthz` reports the process
identifier so a misconfiguration is visible rather than mysterious.
