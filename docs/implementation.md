# Distill: Implementation Document (First Draft)

**Companion to:** `requirements.md`**Author:** Anubhav
**Date:** September 2, 2026
**Status:** Draft v1. Code sketches are illustrative and must be verified against the installed package versions on day 1.

---

## 1. Architecture overview

```
┌─────────────────────────────────────────────────────────────────────┐
│  Browser (React 19 + TypeScript, Vite)                              │
│                                                                     │
│  Upload ─► Progress ─► Data Table ─► Cell ─► Source Viewer          │
│                          │                    (pdf.js + highlights) │
│  Schema Panel ◄─ Proposal Card (A2UI surface)                       │
│  Query Box ─► Result Surface (A2UI surface, custom catalog)         │
│                                                                     │
│  ── one module: /web/src/a2ui ── MessageProcessor + catalog + SSE   │
└───────────────┬───────────────────────────────────┬─────────────────┘
                │ REST (typed client from OpenAPI)   │ SSE streams
┌───────────────▼───────────────────────────────────▼─────────────────┐
│  API (Python 3.12, FastAPI)                                         │
│                                                                     │
│  /documents ─► Ingest worker ─► Parse ─► Extract ─► Ground ─► Score │
│  /schema     ─► Unify / Drift detector ─► Proposal (A2UI JSON)      │
│  /query      ─► NL→SQL agent ─► read-only exec ─► Result (A2UI JSON)│
│  /events, /query (SSE) ─► progress, rows, surfaces                  │
└───────────────┬───────────────────────────┬─────────────────────────┘
                │                           │
        ┌───────▼────────┐        ┌─────────▼─────────┐     ┌──────────┐
        │ Postgres 16    │        │ Object storage    │     │ LLM API  │
        │ records, field │        │ originals, page   │     │ (hosted) │
        │ values, schema │        │ renders           │     │          │
        │ versions       │        │ (local volume)    │     │          │
        └────────────────┘        └───────────────────┘     └──────────┘
```

Two things matter most in this diagram:

1. **All A2UI knowledge lives in one frontend module** (`/web/src/a2ui`). The rest of the app consumes plain React components and a `useSurface(streamUrl)` hook. If the protocol changes, one folder changes.
2. **The backend is a pipeline with explicit stages**, each of which emits an SSE event. The frontend progress list is a direct rendering of those events, so observability and UX are the same feature.

---

## 2. Technology choices

### 2.1 Frontend (given: React + TypeScript)

| Concern | Choice | Version (verified Sept 2, 2026) | Why |
| --- | --- | --- | --- |
| Build | Vite | 8.x | Fast, standard, first-class TS. |
| Framework | React | 19.2.x | Required by the `@a2ui/react` peer range (`^19.2.7`). |
| Language | TypeScript | pin to what `create-vite` scaffolds; enable `strict` | Avoid surprises from the TS 7 line unless the scaffold already uses it. |
| Styling | styled-components + Radix Primitives (unstyled, accessible) | styled-components 6.5.x, `radix-ui` 1.6.x | Author fluency is the deciding factor for a 5-day build. Radix supplies the accessibility and behavior (dialogs, menus, tooltips, selects, focus management) that shadcn/ui would have, without the Tailwind dependency. A2UI catalog components use the same styled primitives so agent-generated UI is indistinguishable from hand-built UI. See section 2.3 for the constraints this choice carries. |
| Server state | TanStack Query | 5.x | Caching, invalidation after SSE events, retries. |
| Table | TanStack Table + TanStack Virtual | Table 9.x | Headless, virtualized, fully controllable cell rendering (needed for confidence tiers and provenance cells). |
| UI state | Zustand | current | Small stores for selection, review cursor, viewer state. |
| Document viewer | react-pdf (pdf.js) | 10.x | Renders PDF pages to canvas; we draw highlight overlays in page coordinates. Non-PDF sources are shown as backend-rendered page images with the same overlay layer. |
| Charts | Recharts | current | Used only inside the A2UI `BarChart` catalog component. |
| A2UI | `@a2ui/react` + `@a2ui/web_core` | 0.11.0 / 0.10.7, import from `/v0_9` | Official React renderer; v0.9 is the recommended protocol per the package README. |
| Schema validation | Zod | **pin 3.25.x** | `@a2ui/react` peer-depends on Zod 3.x. Zod 4 is current on npm and must not be installed. |
| API client | `openapi-typescript` + `openapi-fetch` | current | Types generated from FastAPI's OpenAPI document; no hand-written request types. |
| Tests | Vitest + Testing Library, MSW, Playwright | 4.x / 2.x / 1.62 | Unit and component tests with mocked network; one end-to-end test that runs the demo script. |

### 2.2 Backend (open choice): Python 3.12 + FastAPI

Alternatives seriously considered:

- **Node + TypeScript.** Shared types with the frontend are attractive. Rejected because document parsing (PDF word geometry, OCR, DOCX, XLSX) and LLM structured-output tooling are noticeably more mature in Python, and the A2UI reference agents are Python, which makes their prompt patterns easy to borrow.
- **Go.** Excellent for the API layer, weak for parsing and LLM tooling. Rejected for a 5-day build.

| Concern | Choice | Version | Why |
| --- | --- | --- | --- |
| Web framework | FastAPI | 0.141.x | Async, Pydantic-native, OpenAPI for the typed frontend client. |
| Validation and LLM structured output | Pydantic + Instructor | 2.13.x / 1.16.x | Extraction results are Pydantic models; Instructor handles retries when the model returns malformed output and is provider-agnostic. |
| Database | Postgres 16 via SQLAlchemy 2.0 (async) + Alembic | 2.0.x | Relational query patterns; JSONB for flexible field values; one datastore. |
| PDF parsing | pdfplumber + pypdfium2 | 0.11.x | Word-level bounding boxes (needed for provenance) and fast page rendering to PNG. |
| OCR | Tesseract via pytesseract | system package | For scanned pages with no text layer. Handwriting out of scope. |
| Office formats | python-docx, openpyxl | current | DOCX paragraphs and XLSX cell ranges as provenance units. |
| Streaming | sse-starlette | current | SSE with event IDs for resume. |
| Jobs | In-process asyncio worker queue | n/a | Sufficient for a single-instance 5-day deployment; upgrade path to Redis + arq documented in `decisions.md`. |
| Logging | structlog + correlation ID middleware | current | Every log line and every error response carries a request ID that the frontend shows in error toasts. |
| LLM | Hosted Claude Sonnet-class model through Instructor's Anthropic client | confirm current model ID on day 1 | Strong structured output and long context for multi-page documents. Provider is swappable through Instructor. |

### 2.3 Styling decision: styled-components over Tailwind + shadcn/ui

shadcn/ui is a Tailwind-only library (its components are copied into the repository as Tailwind-classed JSX), so it is not usable without Tailwind. The real choice is therefore Tailwind + shadcn/ui versus a styled API on top of Radix Primitives.

**Decision:** styled-components 6 + Radix Primitives.

**Reasoning:** Tailwind's advantages for this project come down to one thing, shadcn/ui giving a finished component set on day 1. That is a velocity win but not a decisive one, because Radix Primitives supply the same behavior and accessibility, and the visual layer is a few hours of styled primitives that the author can write faster than learning a utility vocabulary under time pressure. The judges explicitly do not score visual polish; they score whether the UX was thought through. Fluency wins.

**Known constraints and how they are handled:**

| Constraint | Mitigation |
| --- | --- |
| styled-components entered maintenance mode on March 17, 2025, and its maintainer advises against adopting it for new projects. It still receives releases (6.5.3, August 2026), and its concerns are React Server Components and runtime cost. This project is a Vite single-page app with no server components, so the main stated reason does not apply. | State this openly in `decisions.md`. Keep every styled definition in `web/src/ui/` so a migration to Linaria (same `styled` API, zero runtime, `@wyw-in-js/vite`) is mechanical if ever needed. |
| Runtime CSS-in-JS in a virtualized table with 5,000 rows: dynamic props inside template literals generate a class per distinct value and re-inject styles on scroll. | Table cells use **static** styled components with variants driven by `data-tier` and `data-type` attributes and CSS variables, never by interpolated props. Tier colors and spacing are theme tokens on `:root`. A Playwright performance check asserts smooth scrolling on the seeded 5,000-row fixture. |
| No off-the-shelf component set. | A small `web/src/ui/` kit built on Radix: Button, Input, Select, Dialog, DropdownMenu, Tooltip, Tabs, Badge, Toast. Estimated half a day on day 1, budgeted in the plan. |
| Theming for the A2UI catalog. | The catalog components import the same `ThemeProvider` tokens, so agent-generated surfaces inherit the app theme automatically. |

**When to reverse this decision:** only if the day-1 UI kit takes more than a day, which would signal that the fluency assumption was wrong. In that case switch to Tailwind + shadcn/ui before any feature code depends on the kit.

**Why not Docling?** It gives better layout understanding, but its dependency footprint (multiple GB of models) makes the one-command setup and the free-tier deployment painful. pdfplumber gives us word boxes, which is what provenance needs. Recorded in `decisions.md`.

---

## 3. Repository layout

```
distill/
├── README.md               one-command setup, architecture summary, demo script
├── decisions.md            required by the brief; see section 12 for seed entries
├── docker-compose.yml      postgres + api + web; needs only LLM_API_KEY
├── Makefile                make dev | test | e2e | seed
├── samples/                8 heterogeneous documents + expected extraction fixtures
├── api/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py             FastAPI app, middleware, routers
│   │   ├── config.py
│   │   ├── db/                 models, session, migrations (alembic)
│   │   ├── routers/            workspaces, documents, schema, records, query, events, actions
│   │   ├── pipeline/           parse.py, extract.py, ground.py, score.py, worker.py
│   │   ├── schema/             propose.py, drift.py, versioning.py
│   │   ├── query/              nl2sql.py, guard.py, execute.py, present.py (A2UI emitter)
│   │   ├── a2ui/               message builders, JSON Schema validation of emitted messages
│   │   └── events.py           SSE event types (shared vocabulary with frontend)
│   └── tests/
└── web/
    ├── package.json
    ├── src/
    │   ├── app/                routes, providers, layout
    │   ├── api/                generated OpenAPI types + thin client
    │   ├── features/
    │   │   ├── upload/
    │   │   ├── processing/     progress list driven by SSE
    │   │   ├── table/          DataTable, cell renderers, confidence tiers
    │   │   ├── viewer/         DocumentViewer, HighlightLayer, coordinate math
    │   │   ├── review/         ReviewQueue, keyboard flow
    │   │   ├── schema/         SchemaPanel, ProposalHost (renders A2UI proposal surface)
    │   │   └── query/          QueryBox, ResultHost (renders A2UI result surface)
    │   ├── a2ui/               THE ONLY place that imports @a2ui/*
    │   │   ├── processor.ts    creates MessageProcessor with project catalog
    │   │   ├── transport.ts    SSE → processor.processMessages, reconnect logic
    │   │   ├── useSurface.ts   React hook: surfaces, status, error, raw stream
    │   │   ├── catalog/        ResultTable, Metric, BarChart, ProvenanceCell,
    │   │   │                   SchemaProposal, FieldMapping (Zod API + implementation)
    │   │   ├── Fallback.tsx    deterministic table renderer for malformed surfaces
    │   │   └── SurfaceBoundary.tsx  error boundary + logging
    │   ├── ui/                 styled-components + Radix kit: theme tokens, Button, Input,
    │   │                       Select, Dialog, DropdownMenu, Tooltip, Tabs, Badge, Toast
    │   ├── lib/                events client, logger, formatters
    │   └── test/               setup, MSW handlers, fixtures
    └── e2e/                    Playwright demo-script test
```

---

## 4. Data model

```sql
workspaces        (id, token_hash, created_at)
documents         (id, workspace_id, filename, mime, size, status, failure_reason,
                   page_count, created_at)
pages             (id, document_id, index, width, height, image_key, text_layer jsonb)
                   -- text_layer: [{text, x0, y0, x1, y1}] per word, page coordinates
schema_versions   (id, workspace_id, version, fields jsonb, created_at, created_by, parent_id)
                   -- fields: [{key, label, type, description, enum_values?, currency?}]
                   -- created_by: 'model_auto' (confident match or clearly novel field,
                   --   applied without a prompt) | 'user' (decided via a proposal card, or
                   --   a direct schema edit). Never the workspace token itself: only its
                   --   hash is ever stored (decision D8). Both are equally real entries in
                   --   history; see decision D23.
records           (id, workspace_id, document_id, schema_version_id, created_at)
field_values      (id, record_id, field_key, value jsonb, value_type,
                   confidence numeric, tier text, status text,
                   provenance jsonb, model_run_id, updated_at)
                   -- tier: high | medium | low | conflict | verified
                   -- status: model | human_verified | not_present
                   -- provenance: {page_index, bbox:[x0,y0,x1,y1], quote, reasoning}
proposals         (id, workspace_id, document_id, kind, payload jsonb, status, created_at)
                   -- kind: initial_schema | drift ; payload includes the A2UI surface
queries           (id, workspace_id, question, sql, row_count, duration_ms, created_at)
```

Design notes:

- **One `field_values` row per (record, field).** This makes provenance, confidence, and human-verified status first-class and makes "never overwrite a human correction" a one-line `WHERE status <> 'human_verified'`.
- **A per-workspace SQL view** `ws_<id>_records` is regenerated whenever the schema version changes. It pivots `field_values` into typed columns (`(value->>'amount')::numeric`, `(value->>0)::date`, and so on). Natural-language queries target this view only, so the LLM sees a flat, typed table and the executor never touches base tables.
- Rejected alternative: one physical table per workspace with real columns. Faster to query, but schema changes become migrations and human corrections need a shadow table. Recorded in `decisions.md`.

---

## 5. API contract

All routes prefixed `/api/v1`. Workspace token in `Authorization: Bearer <token>`.

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/workspaces` | Create anonymous workspace; returns token. |
| POST | `/workspaces/{id}/seed` | Load sample documents. |
| GET | `/workspaces/{id}` | Schema (current version), documents, record count. |
| POST | `/workspaces/{id}/documents` | Multipart upload (many files). Returns document IDs; processing is async. |
| GET | `/workspaces/{id}/documents/{docId}/file` | Original file stream (Range supported for pdf.js). |
| GET | `/workspaces/{id}/documents/{docId}/pages/{n}/image` | Rendered page PNG for non-PDF sources and thumbnails. |
| GET | `/workspaces/{id}/records?cursor=&limit=` | Paged records with field values and provenance. |
| PATCH | `/workspaces/{id}/records/{recId}/fields/{key}` | Human correction: `{value}` or `{not_present: true}`. |
| POST | `/workspaces/{id}/documents/{docId}/reextract` | Re-run extraction; honors human-verified values. |
| GET | `/workspaces/{id}/schema/versions` | Version history. |
| PATCH | `/workspaces/{id}/schema` | Apply edits or a proposal decision; creates a new version. |
| POST | `/workspaces/{id}/schema/revert` | `{version}`. |
| POST | `/workspaces/{id}/schema/backfill` | `{field_keys}`; async, progress via events. |
| GET | `/workspaces/{id}/events` | **SSE.** `Last-Event-ID` supported. |
| POST | `/workspaces/{id}/query` | `{question}` → **SSE** stream: `sql`, then A2UI messages, then `done`. |
| POST | `/workspaces/{id}/actions` | A2UI action round-trip: `{surface_id, action, context}` → SSE of follow-up A2UI messages. |
| GET | `/workspaces/{id}/export?format=csv|json&filter=` | Export current view. |
| GET | `/healthz` | Liveness, DB check, LLM key presence (not value). |

### 5.1 SSE event vocabulary (`/events`)

```tsx
type WorkspaceEvent =
  | { type: 'document.status'; document_id: string; status: 'uploaded'|'parsed'|'extracting'|'done'|'failed';
      stage_detail?: string; failure_reason?: string; attempt?: number }
  | { type: 'record.upsert'; record: Record }            // streamed per document as extraction completes
  | { type: 'field.updated'; record_id: string; field_key: string; value: FieldValue }
  | { type: 'schema.proposal'; proposal_id: string; kind: 'initial_schema'|'drift'; surface: A2UIMessage[] }
  | { type: 'schema.version'; version: number }
  | { type: 'backfill.progress'; done: number; total: number }
  | { type: 'heartbeat' };
```

Every event has an `id` (monotonic per workspace) so reconnects resume with `Last-Event-ID`. The frontend applies events to the TanStack Query cache directly (`setQueryData`) instead of refetching, which is what keeps the table from flickering during streaming.

---

## 6. Backend pipeline

### 6.1 Ingest and parse (`pipeline/parse.py`)

1. Sniff content type from bytes (not extension). Reject mismatches.
2. PDF: pdfplumber extracts words with boxes per page; pypdfium2 renders each page to PNG at 144 DPI for thumbnails and for the OCR path. If a page has fewer than 5 words, run Tesseract on the render and use its word boxes.
3. Images: Tesseract directly.
4. DOCX: paragraphs become "lines" with a synthetic provenance unit `{paragraph_index}`; backend renders a simple page image so the viewer has something to highlight.
5. XLSX and CSV: each sheet becomes a page; provenance unit is a cell range `{sheet, range}`.
6. TXT: line offsets.

Output: a normalized `ParsedDocument { pages: [{ index, width, height, words: [{text, bbox}], lines: [...] }] }`. Everything downstream is format-agnostic.

### 6.2 Extract (`pipeline/extract.py`)

Two modes, both through Instructor with Pydantic response models:

- **Open extraction** (no schema yet): the model returns a list of `{key, value, value_type, evidence_quote, page_index, confidence, reasoning}` for every salient field it finds. Used for the first batch.
- **Schema-guided extraction** (schema exists): the model fills the current schema. The response model is generated dynamically from `schema_versions.fields` with `pydantic.create_model`, plus an `extra_fields` list for anything salient that did not fit. `extra_fields` is what feeds drift detection.

Prompting details that matter:

- Pages are sent as numbered text blocks with line numbers, and the model must cite `page_index` and a verbatim `evidence_quote` for every value. This is the contract that makes grounding possible.
- Currency values are extracted as `{amount, currency}`; dates as ISO strings; the model is told to return `null` rather than guess.
- Max 3 retries on validation failure (Instructor), then the document is marked failed with the reason.

### 6.3 Ground (`pipeline/ground.py`): the provenance sub-problem

Given `evidence_quote` and `page_index`, find the bounding box:

1. Normalize both quote and page words (lowercase, collapse whitespace, strip currency symbols and thousands separators).
2. Sliding-window fuzzy match of the quote against the page's word sequence (RapidFuzz partial ratio, threshold 85). Window size is the quote's word count plus or minus 2.
3. Bounding box is the union of matched word boxes. If words span two lines, return one box per line (the viewer draws multiple rectangles).
4. If no match on the cited page, try neighboring pages (models are frequently off by one on page breaks). If still nothing, `provenance.bbox = null` and the confidence tier is capped at `low`, with `reasoning` noting "could not locate quote in document."

This step is deterministic and fully unit-testable with fixture pages, and it is where most "the model hallucinated a value" cases get caught: a hallucinated value has no quote to ground.

### 6.4 Score (`pipeline/score.py`)

`tier` is derived, never asked of the model directly:

| Condition | Tier |
| --- | --- |
| Grounded, model confidence ≥ 0.85, value passes type validation | high |
| Grounded, confidence 0.6 to 0.85, or minor normalization applied (e.g. date format inferred) | medium |
| Not grounded, or confidence < 0.6, or type coercion needed | low |
| Two extraction runs disagree, or re-extraction disagrees with a human-verified value | conflict |
| Human edited or accepted | verified |

The review queue orders by `impact = weight(field) × (1 - confidence)`, where currency and date fields carry higher weight by default and the user can adjust weights later (not in the 5-day slice).

### 6.5 Schema proposal and drift (`schema/`)

**Initial proposal:** after the first batch completes open extraction, one LLM call receives all `(key, value_type, sample values, document_id)` tuples and returns canonical fields: `{key, label, type, description, source_keys: [...], coverage}`. The backend validates that every source key maps to exactly one canonical field, then applies it directly — creates the `schema_versions` row with `created_by='model_auto'` and emits `schema.version`. This never blocks; the full field list renders in the schema panel and the table fills.

Each proposed unification of two or more source keys is then re-checked with the same D24 scoring used for drift. A merge the rule finds uncertain is **undone before the version is written**: the keys stay as separate fields, and a non-blocking `initial_schema` proposal is queued asking whether to merge them (decision D25). Confident merges — which is what `vendor_name` / `Supplier` / `Vendor` should be — are kept, so the unified-table demo is unaffected. The resolution action is a field merge (FR-16), not a split, because this path never merges on a guess.

**Drift detection:** when schema-guided extraction returns `extra_fields`, each is scored against every existing field with two independent signals (decision D24): string similarity over the normalized `label`, and embedding cosine over `label + description`. The cheap string pass runs first, so a label that is identical after normalization never spends an embedding call. Three zones, not two:

- **auto-map** — requires all of: (a) a normalized-exact/alias hit, *or* string ≥ `drift_string_automap_min` (0.90), *or* embedding ≥ `drift_embedding_automap_min` (0.95); (b) the best candidate beats the runner-up by ≥ `drift_candidate_margin_min` (0.05) on whichever signal fired; (c) type compatibility. Applied immediately as `created_by='model_auto'`; no card.
- **auto-add as new** — `max(string, embedding) < drift_novel_max` (0.30) against *every* existing field. Also `created_by='model_auto'`; backfill across existing documents is enqueued automatically rather than offered, since adding the field was itself automatic.
- **everything else** — a mid-band score, two candidates inside the margin, or a type mismatch. Emits an A2UI `SchemaProposal` surface with `FieldMapping` components — map to existing / add as new / ignore — whose actions round-trip through `/actions` and are applied as `created_by='user'` once the user decides.

`LLMClient` gains `embed()` for this. `GeminiClient` calls the real embeddings endpoint — actual usage assumes a working API key, per D13. `FakeClient` replays recorded vectors for tests and a no-key reviewer clone, same as its other fixtures. A genuine call failure goes through the existing `LLMUnavailable`/retry path like any other model call, not a designed fallback (D24).

Every path — auto-map, auto-add, or user decision — writes one `schema_versions` row and one `schema.version` event, so schema history (FR-15) is a complete, reversible log regardless of which path produced a change. This is what makes the auto-apply zones safe: nothing is silent in the sense of "untracked," only in the sense of "not blocking."

**Applying a decision** (automatic or user-made) creates a new `schema_versions` row, regenerates the workspace view, and (if fields were added) enqueues backfill. Backfill runs schema-guided extraction restricted to the new fields and never touches `human_verified` rows.

### 6.6 Query (`query/`)

1. `nl2sql.py`: the model receives the view's column list with types and three sample rows, plus the question, and returns `{sql, explanation, presentation_hint: 'table'|'metric'|'bar_chart'|'list'|'message'}`.
2. `guard.py`: parse with `sqlglot`; reject anything that is not a single `SELECT`; reject references to any relation other than the workspace view; inject `LIMIT 500`; run under a Postgres role with `SELECT` only and `statement_timeout = 5s`.
3. `execute.py`: run, capture rows, duration, and column types.
4. `present.py`: build A2UI messages. The `presentation_hint` is a hint; the emitter overrides it when the data shape contradicts it (one row and one numeric column is always `Metric`; more than 30 rows is never `BarChart`). Result rows include `record_id` and `field_key` so `ProvenanceCell` can link back.

If the SQL fails, the failure is fed back to the model once for a repair attempt; a second failure returns a `message` surface explaining what was tried.

---

## 7. A2UI integration (frontend)

### 7.1 Installation

```bash
npm i @a2ui/react@0.11.0 @a2ui/web_core@0.10.7 zod@^3.25.76
```

Pin exactly in `package.json` (no caret on the two `@a2ui` packages). The renderer has shipped breaking changes at 0.9.1, 0.10.0, and 0.11.0.

### 7.2 Processor and transport (`a2ui/processor.ts`, `a2ui/transport.ts`)

```tsx
import { MessageProcessor } from '@a2ui/web_core/v0_9';
import { basicCatalog } from '@a2ui/react/v0_9';
import { distillCatalog } from './catalog';

export function createProcessor() {
  return new MessageProcessor([basicCatalog, distillCatalog]);
}

// transport.ts: SSE lines → processor
export function connectSurfaceStream(url: string, processor: MessageProcessor, onMeta: (m: MetaEvent) => void) {
  const es = new EventSource(url); // for POST /query use fetch + ReadableStream instead
  es.addEventListener('a2ui', (e) => processor.processMessages([JSON.parse(e.data)]));
  es.addEventListener('sql',  (e) => onMeta({ type: 'sql', ...JSON.parse(e.data) }));
  es.addEventListener('done', () => es.close());
  return () => es.close();
}
```

`POST /query` cannot use `EventSource` (GET only), so the query transport uses `fetch` with a `ReadableStream` reader and a small SSE line parser. Both transports share the reconnect and parsing code.

### 7.3 Surface hook (`a2ui/useSurface.ts`)

Follows the pattern in the `@a2ui/react` README: subscribe to `processor.onSurfaceCreated` and `onSurfaceDeleted`, mirror `processor.model.surfacesMap` into React state, and expose `{ surfaces, status: 'idle'|'streaming'|'done'|'error', rawMessages }`. `rawMessages` powers the "Inspect surface" developer toggle.

### 7.4 Custom catalog (`a2ui/catalog/`)

A2UI v0.9 separates a component's API (a Zod schema) from its implementation. Sketch for the result table:

```tsx
// ResultTable.api.ts
import { z } from 'zod';
import { CommonSchemas } from '@a2ui/web_core/v0_9';

export const ResultTableApi = {
  name: 'ResultTable',
  schema: z.object({
    columns: z.array(z.object({ key: z.string(), label: z.string(), type: z.enum(['string','number','currency','date','boolean']) })),
    rows: CommonSchemas.DynamicString,        // JSON pointer path into the data model, e.g. {path: '/rows'}
    onRowSelect: CommonSchemas.Action.optional(),
  }),
};

// ResultTable.tsx
import { createComponentImplementation } from '@a2ui/react/v0_9';
export const ResultTable = createComponentImplementation(ResultTableApi, ({ props }) => {
  // props.rows is resolved by the Generic Binder; props.onRowSelect is a ready-to-call function
  return <DataTableLite columns={props.columns} rows={parseRows(props.rows)} onRowSelect={props.onRowSelect} />;
});
```

Catalog members and their purpose:

| Component | Used in | Notes |
| --- | --- | --- |
| `ResultTable` | query results | Reuses the same cell renderers as the main table; virtualized above 100 rows. |
| `Metric` | query results | Big number, unit, optional comparison text. |
| `BarChart` | query results | Recharts; capped at 30 bars; falls back to `ResultTable` above that. |
| `ProvenanceCell` | inside `ResultTable` | Carries `record_id` and `field_key`; click opens the viewer. |
| `SchemaProposal` | schema panel | Container for `FieldMapping` children with Accept all / Review actions. |
| `FieldMapping` | schema proposals | Field name, detected type, sample values, three-way choice; the choice is an A2UI action. |

Exact helper names for child references (`componentId()`, `childList()`) and the action-dispatch wiring must be confirmed against the installed README on day 1; the 0.11.0 changelog changed how child references are marked.

### 7.5 Safety and fallback

- `SurfaceBoundary.tsx` wraps every `A2uiSurface`. On render error, on `onError` reports of unknown component types, or if no surface arrives within 15 seconds, it renders `Fallback.tsx` with the raw result rows (the backend always sends rows in the data model, so the fallback has something to show) and logs an `a2ui.fallback` event.
- Agent-provided strings are rendered as text, never as HTML. Component count per surface is capped at 200 in the transport layer before the processor sees the messages.
- The backend validates every emitted message against the v0.9 JSON Schema in tests, so malformed payloads are caught in CI rather than in the browser.

### 7.6 Deployment and build risks (verified September 3, 2026)

A2UI is pure JavaScript with no native dependencies, so it adds nothing to the Docker build and needs no system packages. The risks are build-configuration and packaging issues, all of which are handled at day 1 rather than discovered at deploy time.

| Risk | Verified finding | Handling |
| --- | --- | --- |
| **Zod version conflict** | Confirmed hard runtime failure. See section 7.1. | Pin `zod@3.25.76` exactly; CI asserts `npm ls zod` shows one version. |
| **Default catalog CSS is broken in the published tarball** | `@a2ui/react@0.11.0` compiles its CSS-module imports to empty objects, so `Button` renders as `<button class="">`. The stylesheet `v0_9/index.css` ships in the tarball but is absent from the package `exports` map, so importing it by package name fails with `ERR_PACKAGE_PATH_NOT_EXPORTED`. The declared `./styles/structural.css` export points to a file that does not exist in the tarball at all. | **Does not affect us.** We ship our own styled-components catalog, and the basic catalog's layout components (`Row`, `Column`, `Card`) use inline styles, which work. We use the basic catalog only for layout and text. If default styling were ever needed, the fallback is `injectBasicCatalogStyles()` from `web_core`, which uses `adoptedStyleSheets` and needs no bundler CSS handling. This is a second, independent reason the styled-components decision in section 2.3 is the right one. |
| **`injectBasicCatalogStyles()` crashes under jsdom** | Throws `Cannot read properties of undefined (reading 'includes')` because jsdom does not implement `document.adoptedStyleSheets`. | Do not call it (see above). If it is ever needed, add an `adoptedStyleSheets = []` polyfill to `web/src/test/setup.ts`. |
| **Bundle size** | A minimal surface plus the basic catalog builds to 239 kB raw, 56 kB gzipped, pulling in `markdown-it`, `date-fns`, `zod`, `zod-to-json-schema`, and `@preact/signals-core`. | Acceptable for a desktop-first tool. The A2UI route is lazy-loaded with `React.lazy` so the initial table view does not pay for it. Budget asserted in CI with `size-limit` at 70 kB gzipped for the A2UI chunk. |
| **SSE buffering behind a proxy** | Not A2UI-specific, but A2UI streaming is the thing that breaks. Reverse proxies buffer `text/event-stream` and compression middleware defeats it entirely, producing a surface that renders only after the whole response completes. | Set `X-Accel-Buffering: no` and `Cache-Control: no-cache` on all SSE responses; exclude `/events` and `/query` from the compression middleware; send a comment heartbeat every 15 seconds. Deployed-environment smoke test asserts the first A2UI message arrives before the last one. |
| **Protocol churn** | Breaking changes in three consecutive minor releases; v1.0 is a release candidate. | Exact pins, lockfile committed, `npm ci` in the Docker build, and all A2UI code confined to `web/src/a2ui/`. |
| **Renderer regressions reaching production** | The published package has had defects (the CSS issue above; a manifest problem reported in April 2026). | A Vitest smoke test renders one surface per catalog component and asserts on output; it runs in CI, so a bad upgrade fails the build rather than the demo. |

The net answer on deployment: **no, A2UI will not cause deployment problems**, provided Zod is pinned to 3 and the SSE endpoints are configured to stream. Both are one-line fixes, and both are day-1 checklist items in section 13.

---

## 8. Frontend implementation details

### 8.1 State model

- **Server state** (documents, records, schema, versions): TanStack Query. SSE events mutate the cache with `setQueryData`; no polling.
- **UI state** (selected cell, review cursor, viewer page and zoom, column layout): Zustand, persisted per workspace in `localStorage` for column layout only.
- **A2UI state**: owned by `MessageProcessor` instances inside the hook; never duplicated into Zustand.

### 8.2 Data table

- TanStack Table with `@tanstack/react-virtual` for rows and columns.
- Cell renderer is selected by field type; each renderer receives `FieldValue` and draws the tier marker (an icon plus a subtle left border, never color alone).
- Inline edit uses a type-specific editor (date picker, currency input with code, enum select). Save issues `PATCH .../fields/{key}` with optimistic update and rollback on failure.

### 8.3 Document viewer and highlight math

- PDF pages render with react-pdf at a chosen scale `s`. Provenance boxes are stored in PDF points with a top-left origin as produced by pdfplumber. Overlay rectangle = `bbox × s`. (pdfplumber already flips the PDF's bottom-left origin, so no extra transform; this is asserted by a unit test with a known fixture.)
- For non-PDF sources, the backend serves a page image plus its pixel dimensions; the same overlay code runs with `s = renderedWidth / imageWidth`.
- Clicking a cell scrolls the viewer to the page, animates the highlight, and shows a side card with quote and reasoning.

### 8.4 Review queue

- Derived selector over records: cells where `tier ∈ {low, conflict}` ordered by impact. Keyboard handler is a single `useReviewKeys` hook; every action is available as a visible button too.

### 8.5 Empty and error states

- Empty workspace: illustration-free, one sentence, drop zone, "Try with sample documents."
- Every error toast shows the correlation ID and a "copy details" button.

---

## 9. Testing strategy

Tests are chosen to catch failures we would actually hit, not to pad coverage.

**Backend (pytest)**

- `ground.py`: quotes with different casing, currency formatting, line wraps, off-by-one page citation, and unfindable quotes. Uses fixture pages from `samples/`.
- `score.py`: tier table above as parametrized cases.
- `schema/drift.py`: rename detection (`Supplier` → `vendor_name`), type conflict, genuinely new field.
- `query/guard.py`: rejects `UPDATE`, `;` chaining, references to base tables, missing `LIMIT`.
- Re-extraction preserves `human_verified` rows (integration test against a Postgres test container).
- Every emitted A2UI message validates against the v0.9 JSON Schema.
- SSE resume: events after `Last-Event-ID` are replayed exactly once.

**Frontend (Vitest + Testing Library + MSW)**

- Highlight overlay coordinate math with known boxes and scales.
- Table applies `record.upsert` and `field.updated` events without remounting rows (assert row identity).
- Confidence tier renders an icon and text label, not only a color.
- Inline edit: optimistic update and rollback on 500.
- A2UI: a fixture stream renders `Metric`; a stream with an unknown component triggers `Fallback` and logs the event; a stream that never arrives triggers the timeout fallback.
- SSE transport reconnects with backoff and sends `Last-Event-ID`.

**End to end (Playwright)**

- One test that runs the acceptance demo script from `requirements.md` section 8 against a seeded workspace with the LLM mocked by a recorded fixture, so it is deterministic in CI.

**CI (GitHub Actions)**: lint, typecheck, backend tests with Postgres service, frontend tests, Playwright against `docker compose`. Green CI is a precondition for deploy.

---

## 10. Setup, deployment, observability

**Local:** `cp .env.example .env`, set `LLM_API_KEY`, then `docker compose up`. Compose starts Postgres, runs migrations, seeds nothing (the UI's sample button does that), and serves the web build from the API container at `http://localhost:8000`. `make dev` runs Vite and Uvicorn with hot reload for development.

**Deployment:** a single container on Fly.io (or Railway) with an attached Postgres and a persistent volume for uploads. Frontend static assets are served by FastAPI so judges get one URL and there is no CORS surface. Environment variables: `DATABASE_URL`, `LLM_API_KEY`, `STORAGE_DIR`, `MAX_UPLOAD_MB`.

**Observability:**

- Backend: structlog JSON logs with `request_id`, `workspace_id`, `document_id`, stage timings, LLM token counts and latency per call. `/healthz` reports DB and storage checks.
- Frontend: `lib/logger.ts` emits structured events (`upload.start`, `extract.done`, `correction.made`, `query.run`, `a2ui.fallback`) to console in dev and to `POST /api/v1/client-events` in prod (fire-and-forget, batched).
- The processing progress list in the UI is literally the event log for that document, so users see the same information operators would.

---

## 11. Five-day plan

| Day | Goal | Shippable at end of day |
| --- | --- | --- |
| 1 | Scaffold monorepo, compose, CI. Theme tokens and the `ui/` kit on Radix (half day, hard stop; see section 2.3). Upload → parse → open extraction → records in DB. Basic table. Verify A2UI package APIs against installed README and write the `useSurface` spike. | A file becomes a table row locally. |
| 2 | Grounding + scoring + viewer with highlights. SSE events driving progress and table. Sample documents and seed endpoint. Deploy. | **Demo-able slice with a URL:** upload, see rows, click cell, see highlight. |
| 3 | Initial schema proposal and drift detection. `SchemaProposal` and `FieldMapping` catalog components. Human corrections and re-extraction guarantees. Schema versions and revert. | Heterogeneous documents produce proposals instead of breakage. |
| 4 | Query: NL→SQL, guard, executor, A2UI presenter, `ResultTable`/`Metric`/`BarChart`, fallback, inspect toggle. Export. | Ask questions, get agent-shaped results. |
| 5 | Review queue with keyboard flow, empty and error states, accessibility pass, Playwright demo test, README, `decisions.md` polish, final deploy. | Everything in the acceptance script passes. |

Buffer strategy: if day 3 slips, drift detection ships without backfill (FR-14 is Should). If day 4 slips, `BarChart` is cut and `Metric` plus `ResultTable` carry the demo.

---

## 12. Seed entries for `decisions.md`

Each entry follows the brief's format: decision, alternatives, reasoning, what was cut.

1. **Framed the problem as unification and trust, not extraction.** Alternatives: single-document extractor with a nice viewer; generic chat-over-documents. Reasoning: extraction alone is commodity; the cross-document schema problem is where naive approaches break and where a finance ops user actually loses time. Cut: per-document Q&A chat.
2. **Python + FastAPI backend over Node.** Alternatives: Node/TS for shared types; Go. Reasoning: parsing and LLM structured-output tooling maturity; A2UI reference agents are Python. Cut: shared type package; replaced by OpenAPI-generated client.
3. **pdfplumber + Tesseract over Docling.** Reasoning: word boxes are what provenance needs; Docling's model footprint breaks one-command setup on free tiers. Cut: layout-aware table extraction for complex multi-column PDFs.
4. **Postgres JSONB `field_values` plus a per-workspace typed view, over physical tables per workspace.** Reasoning: schema changes are cheap, human corrections are first-class, and the LLM still sees a flat typed table. Accepted tradeoff: view regeneration on every schema version; query performance is fine at the scale of this round.
5. **Derived confidence tiers instead of trusting model self-report.** Reasoning: grounding success is a stronger signal than a number the model made up; conflicts between runs are a real-world failure mode worth surfacing. Cut: a second full extraction pass on every document by default (available as a per-document "double-check" action instead).
6. **A2UI for query results and schema proposals, not for the whole app.** Alternatives: hand-built result components with a `presentation_hint` switch; CopilotKit's A2UI renderer over AG-UI. Reasoning: agent-chosen presentation is the genuine value; using A2UI everywhere would make the core table depend on an evolving protocol. CopilotKit adds a runtime layer we do not need. Accepted risk: renderer churn, mitigated by exact pins, a single module boundary, and a deterministic fallback.
7. **SSE over WebSockets.** Reasoning: one-directional streaming is all we need; SSE resumes with `Last-Event-ID` for free and works through every proxy. Cut: live cursors and multi-user presence.
8. **Anonymous workspaces with a bearer token in the URL, no accounts.** Reasoning: five days; auth demonstrates nothing about the problem. Accepted risk: anyone with the URL can see the workspace; stated clearly in the UI.
9. **In-process job queue over Redis + worker.** Reasoning: single instance, five days. Documented upgrade path. Accepted risk: a deploy restarts in-flight extractions; the status model makes them resumable on boot.
10. **Read-only SQL role, `sqlglot` allow-list, 5-second timeout, 500-row cap for generated SQL.** Reasoning: the model writes SQL; we assume it will eventually write something dangerous. Cut: user-editable SQL.
11. **styled-components + Radix Primitives over Tailwind + shadcn/ui.** Alternatives: Tailwind + shadcn/ui (fastest to a finished component set); Linaria or Panda CSS (styled API with zero runtime). Reasoning: author fluency in a 5-day build outweighs shadcn's head start; Radix provides the accessibility and behavior; the project is a Vite single-page app, so the server-component concern behind styled-components' maintenance mode does not apply. Accepted risks: a library its maintainer no longer recommends for new projects, and runtime CSS-in-JS cost, mitigated by static variants driven by data attributes and a single `ui/` module boundary that makes a Linaria swap mechanical. Cut: a prebuilt component library of any kind.

---

## 13. Day-1 verification checklist

Items in this document that must be confirmed against real packages before code depends on them:

- [ ]  `@a2ui/react@0.11.0` + `@a2ui/web_core@0.10.7` + `zod@3.25.x` install cleanly with React 19.2.x and the README quick-start renders.
- [ ]  Exact export names for child reference markers and action dispatch in `@a2ui/react/v0_9` (changed in 0.11.0).
- [ ]  The v0.9 message JSON Schema location inside the A2UI repository, for backend validation in tests.
- [ ]  Current Anthropic model identifier and Instructor's Anthropic client signature.
- [ ]  pdfplumber word coordinate origin on the sample PDFs (assert with a fixture before writing overlay math).
- [ ]  `create-vite` template's TypeScript version and whether `openapi-typescript` runs on it without flags.