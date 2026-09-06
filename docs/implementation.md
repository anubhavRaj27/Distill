# Distill: Implementation Document (v2)

**Companion to:** `requirements.md` v2
**Author:** Anubhav Raj
**Date:** September 4, 2026 (v1 was September 2, 2026)
**Status:** v2, governing. Supersedes v1 in full. Sections marked **built** describe code
that exists and has been verified against a live server; sections marked **new** are the
remaining work.

---

## 1. Architecture overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Browser  (React 19, TypeScript, Vite; client/)                          │
│                                                                          │
│   / Upload ──► /w/{id}/chat  Chat ◄──────────► Source viewer (overlay)   │
│                  │  prose + citations + A2UI visual        ▲             │
│                  │                                         │             │
│               /w/{id}/data  Data: unified table + A2UI dashboard panels  │
│                                                                          │
│   client/src/a2ui: the only importer of @a2ui/*  (renderer, catalog,     │
│                    fallback, inspect)                                    │
└──────────────┬───────────────────────────────────────┬───────────────────┘
               │ REST (typed client from OpenAPI)      │ SSE /events
┌──────────────▼───────────────────────────────────────▼───────────────────┐
│  Server  (Python 3.12, FastAPI; server/)                                 │
│                                                                          │
│  documents ─► worker ─► parse ─► extract ─► ground ─► score ─► persist   │
│                                   │                             │        │
│                                   └─► unify schema (auto only)  └─► index│
│                                                                (chunks + │
│                                                                 vectors) │
│  chat ─► retrieve (cosine + records digest) ─► plan (structured)         │
│        ─► evaluate query spec ─► build A2UI ─► stream prose (SSE)        │
│  dashboard ─► field stats ─► plan (structured) ─► evaluate ─► A2UI       │
└──────────────┬──────────────────────────────┬────────────────────────────┘
               │                              │
      ┌────────▼─────────┐        ┌───────────▼───────────┐     ┌─────────┐
      │ Postgres 16      │        │ Local file storage    │     │ Gemini  │
      │ records, values, │        │ originals, page PNGs  │     │ (google │
      │ chunks+vectors,  │        │                       │     │ -genai) │
      │ chat, dashboard, │        └───────────────────────┘     └─────────┘
      │ event log        │
      └──────────────────┘
```

Three things carry the design:

1. **The model never produces a number that is displayed.** For any visual, the model emits
   a _query specification_; deterministic code evaluates it over `field_values`; the result
   is bound into the A2UI data model by path. Decision D37. This is also what makes the
   dashboard trustworthy without a review step.
2. **One provenance path.** Every format is rendered to page images with word geometry
   (decision D18), so a chat citation and a table cell open the same viewer with the same
   overlay code. PDF pages use the backend render too (decision D43), which removes pdf.js
   from the client.
3. **A2UI is confined to one module per side.** `server/app/a2ui/` builds messages;
   `client/src/a2ui/` renders them. Nothing else knows the protocol.

---

## 2. Technology choices

### 2.1 Frontend (built unless noted)

| Concern           | Choice                                                                       | Version                | Why                                                                                                                                                                             |
| ----------------- | ---------------------------------------------------------------------------- | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Build             | Vite                                                                         | 8.2                    | Scaffolded by `create-vite`. Decision D33.                                                                                                                                      |
| Framework         | React                                                                        | 19.2.8                 | Required by `@a2ui/react` peer range.                                                                                                                                           |
| Language          | TypeScript, `strict`, `noUncheckedIndexedAccess`                             | 6.0.3                  | As scaffolded.                                                                                                                                                                  |
| Lint              | oxlint                                                                       | 1.79                   | As scaffolded. Decision D33.                                                                                                                                                    |
| Styling           | styled-components                                                            | 6.5                    | Decision D11. Warm-paper tokens in `src/ui/theme.ts`, decision D32. Radix Primitives added only where a primitive is needed (dialog for the viewer, dropdown for column menus). |
| Routing           | `react-router`, declarative                                                  | 7.18                   | Decision D30. Routes: `/`, `/w/:id` (redirects to chat), `/w/:id/chat`, `/w/:id/data`.                                                                                          |
| Server state      | TanStack Query                                                               | 5                      | SSE events write into the cache with `setQueryData`.                                                                                                                            |
| UI state          | Zustand                                                                      | 5                      | Viewer open state, selected citation, inspect toggle.                                                                                                                           |
| Table (**new**)   | TanStack Table                                                               | 8.x current            | Headless sort, visibility, column API. No virtualisation: a workspace holds tens of rows.                                                                                       |
| Charts (**new**)  | Recharts                                                                     | current                | Inside the A2UI `BarChart` and `LineChart` catalog components only.                                                                                                             |
| A2UI (**new**)    | `@a2ui/react` + `@a2ui/web_core`, `/v0_9` imports                            | 0.11.0 / 0.10.7, exact | Official renderer.                                                                                                                                                              |
| Schema validation | Zod                                                                          | **3.25.76 exact**      | `@a2ui/react` peer range. Zod 4 must not be installed.                                                                                                                          |
| API client        | `openapi-fetch`; types via pinned `npx openapi-typescript`, output committed | 0.17 / 7.13            | Decision D33.                                                                                                                                                                   |
| Tests             | Vitest 4 + Testing Library; MSW (**new**)                                    |                        | Unit and component tests with a mocked network.                                                                                                                                 |

Removed from v1's list: react-pdf (decision D43), TanStack Virtual, Playwright (cut to a
manual demo script; see section 9).

### 2.2 Backend (built unless noted)

| Concern           | Choice                                                              | Why                                                                                                                                                                                                                                   |
| ----------------- | ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Runtime           | Python 3.12, `uv`                                                   | Decisions D2, D12.                                                                                                                                                                                                                    |
| Web               | FastAPI, `sse-starlette`                                            | Async, Pydantic-native, OpenAPI for the typed client.                                                                                                                                                                                 |
| Database          | Postgres 16, SQLAlchemy 2 async, Alembic                            | Decision D4 (values half; the per-workspace SQL view is cut).                                                                                                                                                                         |
| Parsing           | pdfplumber, pypdfium2, Tesseract, python-docx, openpyxl, `filetype` | Decision D3. Every format rendered to page images, decision D18.                                                                                                                                                                      |
| Grounding         | RapidFuzz                                                           | Quote to word-box matching, section 6.2.                                                                                                                                                                                              |
| LLM               | Gemini via `google-genai` directly                                  | Decisions D13, D20, **D62**. `gemini-3.5-flash` for extraction and schema; `gemini-3.5-flash-lite` at `thinking_level=low` for chat planning and prose, dashboard planning, and suggestions. The Pro tier is not available on the project's key. `generate_content_stream` for prose (decision D44). `gemini-embedding-001` at 768 dimensions for vectors (**D63**). |
| Vectors (**new**) | Stored as JSONB float arrays; cosine computed in process            | Decision D36. Upgrade path to pgvector documented there.                                                                                                                                                                              |
| Jobs              | In-process asyncio worker, one process                              | Decision D9.                                                                                                                                                                                                                          |
| Events            | Persisted `workspace_events` log plus in-process bus                | Decision D14.                                                                                                                                                                                                                         |
| Logging           | structlog with correlation identifier middleware                    |                                                                                                                                                                                                                                       |
| A2UI (**new**)    | Hand-built message builders, `jsonschema` validation in tests       | No official Python emitter.                                                                                                                                                                                                           |

Removed from v1: Instructor (D20), sqlglot and the read-only database role (D35), the
`schema/view.py` pivot view (D35).

---

## 3. Repository layout

```
Zamp assignment/
├── CLAUDE.md
├── README.md                 setup, architecture summary, demo script
├── decisions.md              decision log (required deliverable)
├── Makefile                  setup | dev | test | seed          (new)
├── docs/                     requirements.md, implementation.md
├── samples/                  10 generated documents, manifest.json, expected.json (D67)
├── server/
│   ├── pyproject.toml, uv.lock, alembic.ini, .env.example
│   ├── app/
│   │   ├── main.py, config.py, deps.py, auth.py, errors.py, logging.py, middleware.py
│   │   ├── db/               models.py, session.py, migrations/
│   │   ├── domain/           document, fields, values, geometry, provenance, records, events
│   │   ├── events/           bus.py, stream.py
│   │   ├── storage/          local.py
│   │   ├── llm/              base.py, gemini.py, fake.py, jsonschema.py, registry.py, prompts/
│   │   ├── pipeline/         parse/, extract.py, ground.py, score.py, persist.py,
│   │   │                     process.py, worker.py, index.py                      (index new)
│   │   ├── schema/           similarity.py, embeddings.py, propose.py, drift.py, versioning.py
│   │   ├── retrieval/        chunking.py, search.py                                (new)
│   │   ├── chat/             answer.py, citations.py, service.py, suggestions.py  (new)
│   │   ├── insights/         queryspec.py, evaluate.py, stats.py, dashboard.py    (new)
│   │   ├── a2ui/             catalog.py, build.py, schema/ (v0.9 JSON Schema)      (new)
│   │   └── routers/          health, workspaces, documents, records, schema, events,
│   │                         chat, dashboard                              (chat, dashboard new)
│   └── tests/                unit/, integration/, fixtures/
└── client/
    ├── package.json, vite.config.ts, tsconfig*.json
    └── src/
        ├── app/              App.tsx, Providers.tsx, WorkspaceLayout.tsx (header, nav,
        │                     add-documents, processing strip host)
        ├── api/              client.ts, schema.d.ts (generated), openapi.json
        ├── features/
        │   ├── upload/       UploadScreen (both routes), DocumentLibrary     (built)
        │   ├── processing/   ProcessingStrip, useWorkspaceEvents           (new)
        │   ├── chat/         ChatScreen, MessageList, AssistantMessage, Citations,
        │   │                 Composer, Suggestions, useChat                (new)
        │   ├── data/         DataScreen, RecordsTable, cells/, ColumnMenu, Dashboard,
        │   │                 DashboardPanel, useRecords, useDashboard      (new)
        │   └── viewer/       SourceViewer, PageImage, HighlightLayer, useViewer (new)
        ├── a2ui/             processor.ts, SurfaceHost.tsx, SurfaceBoundary.tsx,
        │                     Fallback.tsx, Inspect.tsx, catalog/ (Metric, BarChart,
        │                     LineChart, ResultTable)                       (new)
        ├── ui/               theme, GlobalStyle, Button, Wordmark, ParticleText,
        │                     Spiral, Toasts + toastStore (D73)
        ├── lib/              files, logger, workspace-token, formatters (new), sse (new)
        └── test/             setup, msw handlers (new)
```

Rule for the client: a feature folder owns its screen, its hooks, and its components. Shared
primitives live in `ui/`; shared logic in `lib/`; protocol code in `a2ui/`. Nothing in
`features/` imports from another feature except through `app/`.

---

## 4. Data model

Built tables are unchanged unless noted. Types are indicative.

```
workspaces          (id, token_hash, label, event_seq, created_at)                    built
documents           (id, workspace_id, filename, mime, source_format, size_bytes,
                     content_hash, storage_key, status, stage_detail, failure_reason,
                     attempts, page_count, created_at, updated_at)                    built
pages               (id, document_id, index, width_pt, height_pt, image_key,
                     ocr_applied, locator, text_layer jsonb)                          built
document_extractions(id, document_id, kind, schema_version, payload, model_name,
                     model_run_id, created_at)                                        built
schema_versions     (id, workspace_id, version, fields jsonb, created_by,
                     change_summary, parent_id, created_at)                           built
                     -- kept as the store of the current schema and as an audit trail
                     -- in the database; not exposed as a history view in v2 (D38).
records             (id, workspace_id, document_id, schema_version_id, ...)           built
field_values        (id, record_id, field_key, value jsonb, value_type, confidence,
                     tier, status, provenance jsonb, model_value, model_value_at,
                     model_run_id, updated_at)                                        built
workspace_events    (id, workspace_id, seq, type, payload, created_at)               built

chunks              (id, document_id, page_index, ordinal, text, word_start, word_end,
                     token_estimate, embedding jsonb, created_at)                     new
                     -- one passage of a page; word_start/word_end index into
                     -- pages.text_layer so a citation maps to boxes without re-parsing.
chat_messages       (id, workspace_id, role, status, content, sources jsonb,
                     citations jsonb, visual jsonb, surface jsonb, model_run_id,
                     error, created_at, completed_at)                                 new
                     -- role: user | assistant. status: streaming | done | stopped |
                     -- failed. sources: retrieved chunk refs. citations: [{n, chunk_id,
                     -- document_id, page_index, boxes, excerpt}]. visual: the query
                     -- spec the model chose. surface: the A2UI messages built from its
                     -- evaluation. content is written once at the end of the stream
                     -- (or on stop); while streaming, text lives in the in-memory
                     -- answer buffer (D44).
dashboards          (id, workspace_id, status, stale, panels jsonb, generated_at,
                     model_run_id, error)                                             new
                     -- one row per workspace. panels: [{title, kind, rationale,
                     -- query, surface}]. status: pending | ready | failed.

dropped:  proposals (D38), queries (D35)
```

Design notes:

- `field_values` stays tall (one row per record and field) so "never overwrite a
  human-verified value" remains a `WHERE status <> 'human_verified'` clause (D4, D16).
- Query specifications are evaluated in Python over the workspace's `field_values` rather
  than through a pivot view, because the workspace is small and the evaluator is easier to
  test than generated SQL (decision D35).
- Vectors live in JSONB and similarity is computed in process (decision D36). A workspace of
  25 documents at roughly 40 passages each is about a thousand vectors of 768 floats, which
  is trivially scanned.

---

## 5. API contract

All routes under `/api/v1`. Workspace token in `Authorization: Bearer <token>`.

| Method | Path                                                 | Purpose                                                                                                                                                                                 | State                       |
| ------ | ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------- |
| POST   | `/workspaces`                                        | Create anonymous workspace; returns token once.                                                                                                                                         | built                       |
| GET    | `/workspaces/{id}`                                   | Cold start: schema, documents, record count, dashboard status.                                                                                                                          | built, add dashboard status |
| POST   | `/workspaces/{id}/documents`                         | Multipart upload, many files. Async processing.                                                                                                                                         | built                       |
| POST   | `/workspaces/{id}/documents/seed`                    | Load the sample manifest.                                                                                                                                                               | built, corpus in `samples/` |
| GET    | `/workspaces/{id}/documents/{docId}`                 | One document with pages.                                                                                                                                                                | built                       |
| GET    | `/workspaces/{id}/documents/{docId}/file`            | Original, byte ranges.                                                                                                                                                                  | built                       |
| GET    | `/workspaces/{id}/documents/{docId}/pages/{n}/image` | Rendered page PNG.                                                                                                                                                                      | built                       |
| POST   | `/workspaces/{id}/documents/{docId}/reextract`       | Re-run extraction honouring verified values.                                                                                                                                            | built                       |
| DELETE | `/workspaces/{id}/documents/{docId}`                 | Remove document, record, chunks.                                                                                                                                                        | built, add chunks           |
| GET    | `/workspaces/{id}/events`                            | SSE, `Last-Event-ID` resume.                                                                                                                                                            | built                       |
| GET    | `/workspaces/{id}/records`                           | Cursor-paged records with values and provenance.                                                                                                                                        | built                       |
| PATCH  | `/workspaces/{id}/records/{recId}/fields/{key}`      | Human correction.                                                                                                                                                                       | built                       |
| GET    | `/workspaces/{id}/schema`                            | Current fields.                                                                                                                                                                         | built                       |
| PATCH  | `/workspaces/{id}/schema`                            | Rename or merge fields.                                                                                                                                                                 | built (edit), add merge     |
| GET    | `/workspaces/{id}/chat/messages`                     | Conversation history, persisted state only.                                                                                                                                             | new                         |
| POST   | `/workspaces/{id}/chat/messages`                     | `{question}` → `202 {user_message, message_id, stream_url}`. Starts generation as a background task.                                                                                    | new                         |
| GET    | `/workspaces/{id}/chat/messages/{msgId}/stream`      | **SSE**, per-answer stream (section 5.2). `Last-Event-ID` resume from the in-memory buffer; if the message is already terminal, replays the persisted message as a single `done` event. | new                         |
| POST   | `/workspaces/{id}/chat/messages/{msgId}/stop`        | Cancel generation; persists what has streamed with `status = stopped`.                                                                                                                  | new                         |
| GET    | `/workspaces/{id}/chat/suggestions`                  | Three suggested questions.                                                                                                                                                              | new                         |
| GET    | `/workspaces/{id}/dashboard`                         | Current panels, status, stale flag.                                                                                                                                                     | new                         |
| POST   | `/workspaces/{id}/dashboard/generate`                | Regenerate; async, progress over events.                                                                                                                                                | new                         |
| GET    | `/workspaces/{id}/export?format=csv`                 | Table export.                                                                                                                                                                           | new, Could                  |
| GET    | `/healthz`                                           | Liveness, database, provider name.                                                                                                                                                      | built                       |

Removed: `/review`, `/proposals`, `/proposals/{id}/decide`, `/schema/versions`,
`/schema/revert`, `/schema/backfill`, `/query`, `/actions`.

### 5.1 SSE event vocabulary (`/events`)

```ts
type WorkspaceEvent =
  | {
      type: "document.status";
      document_id: string;
      status:
        | "uploaded"
        | "parsing"
        | "extracting"
        | "indexing"
        | "done"
        | "failed";
      stage_detail?: string;
      failure_reason?: string;
      attempt?: number;
    }
  | { type: "record.upsert"; record: Record }
  | {
      type: "field.updated";
      record_id: string;
      field_key: string;
      value: FieldValue;
    }
  | { type: "schema.updated"; version: number; summary: string }
  | {
      type: "chat.progress";
      message_id: string;
      stage: "retrieving" | "reading" | "building" | "done" | "failed";
      detail?: string;
    }
  | {
      type: "dashboard.status";
      status: "pending" | "ready" | "failed";
      stale: boolean;
    }
  | { type: "heartbeat" };
```

`indexing` is the new document stage (chunk and embed). `chat.progress` and
`dashboard.status` are new. `schema.proposal`, `schema.version`, and `backfill.progress`
are removed. `chat.progress` on the workspace stream carries only coarse state (a message
started, finished, or failed) so a second tab shows the conversation moving; the tokens
themselves travel on the per-message stream below and are never written to
`workspace_events`.

### 5.2 Per-message answer stream (`/chat/messages/{msgId}/stream`)

Decision D44. Each event has a monotonic `id` starting at 1 for that message. Events in
the order a client will normally see them:

```ts
type AnswerEvent =
  | {
      type: "status";
      stage:
        | "retrieving"
        | "reading"
        | "planning"
        | "answering"
        | "done"
        | "stopped"
        | "failed";
      detail?: string;
    }
  | {
      type: "sources";
      sources: Array<{
        chunk_id: string;
        document_id: string;
        filename: string;
        page_index: number | null;
        locator?: string;
      }>;
    }
  | {
      type: "visual";
      kind: "metric" | "bar" | "line" | "table";
      title: string;
      surface: A2UIMessage[];
    } // complete array, sent once, before tokens
  | {
      type: "visual_skipped";
      reason: "none_planned" | "empty_result" | "evaluation_failed";
    }
  | { type: "token"; text: string } // prose delta, placeholders already substituted
  | {
      type: "citation";
      n: number;
      chunk_id: string;
      document_id: string;
      filename: string;
      page_index: number | null;
      boxes: Box[];
      excerpt: string;
    }
  | { type: "done"; message: ChatMessage } // the persisted message, authoritative
  | { type: "error"; message: string; correlation_id: string };
```

Rules: `visual` or `visual_skipped` always precedes the first `token`, so the client can
reserve the card's space before prose starts. A `citation` event is emitted the first time
its marker appears in the token stream, before the token that contains the marker's closing
bracket, so the client never renders an unresolved marker. `done` carries the whole message
so a client that reconnected late can replace its local state wholesale.

---

## 6. Backend pipeline

### 6.1 Parse, extract, ground, score, persist (built)

Unchanged from what exists. Summary for orientation:

- **Parse** sniffs content type from bytes, then routes to a format parser. Every format
  produces pages with word geometry and a rendered PNG (D18). Pages with fewer than
  `ocr_min_words_per_page` words go through Tesseract.
- **Extract** calls Gemini with a flat response shape: a list of `{key, value_text,
type_guess, evidence_quote, page_index, confidence, reasoning}` (D19). The first batch
  uses open extraction; once a schema exists, guided extraction communicates the schema in
  the prompt and reports `extra_fields`.
- **Ground** locates each `evidence_quote` in the page's word sequence with RapidFuzz and
  returns word boxes (one per line if wrapped). Unlocatable quotes cap the tier at low.
- **Score** derives the tier from grounding, confidence, and whether a judgment was made in
  parsing the value (D5, D21).
- **Persist** writes records and `field_values`, never touching `human_verified` rows;
  disagreement with a verified value lands in `model_value` with the conflict tier (D16).

### 6.2 Schema unification (built, narrowed)

The initial schema is proposed by the model from the first batch and applied immediately.
Later documents' `extra_fields` are classified against the schema with string similarity and
embedding cosine (D24, D27). v2 changes only what happens to the **ask** outcome:

| Classification                                                             | v1            | v2 (decision D38)                                              |
| -------------------------------------------------------------------------- | ------------- | -------------------------------------------------------------- |
| Unambiguous match                                                          | auto-map      | auto-map (unchanged)                                           |
| Clearly novel                                                              | auto-add      | auto-add (unchanged)                                           |
| Ask (borderline, competing candidates, type mismatch, unconfirmed novelty) | proposal card | **auto-add as a separate field**, `change_summary` records why |

The asymmetry argument from D25 still holds: a wrong split is a cheap merge later, a wrong
merge is expensive to unpick. The user's merge is `PATCH /schema` with
`{merge: {from: key, into: key}}`, which moves values and provenance and writes a new
`schema_versions` row. `proposals`, the proposal routes, and the debounce setting are
removed. `schema_versions` stays as the store of the current schema.

### 6.3 Index: chunking and embedding (new, `pipeline/index.py`, `retrieval/`)

Runs after persist, as the document's `indexing` stage.

1. **Chunking** (`retrieval/chunking.py`). For each page, walk `text_layer.lines` and
   accumulate lines into passages of roughly 80 to 160 words, breaking at line boundaries,
   with a one-line overlap between neighbours. Chunks are kept this small because a chat
   citation highlights the whole chunk's word span (decision D45), so chunk size is
   highlight size. Each chunk records `page_index`,
   `word_start`, `word_end` (indices into the page's word list), and the text. A spreadsheet
   page chunks by row groups; a DOCX page by paragraphs; the logic is the same because D18
   already gave every format lines and words.
2. **Records digest.** One extra chunk per document with `page_index = null` whose text is
   the document's extracted record rendered as `label: value` lines. It is embedded like any
   other chunk, so a question phrased in the schema's vocabulary retrieves the record even
   when the page text uses different words. It carries no boxes and is never cited by
   quote; a citation to a digest chunk resolves to the underlying `field_values` provenance.
3. **Embedding.** Batches of up to 64 chunk texts through `LLMClient.embed` with
   `gemini-embedding-001`, requested at 768 dimensions and tagged `task="document"`; the
   question is embedded as `task="query"` (decision D63). A chunk records its space as
   `model@width`, so a width or model change is visible rather than silently returning
   zero similarity. `FakeClient` returns recorded vectors for the sample corpus and
   deterministic hashed pseudo-vectors otherwise, so the test suite and a no-key clone
   retrieve something plausible (D13).
4. Chunks are written in the document's transaction; `document.status` moves to `done` and
   the `record.upsert` event fires only after indexing, so "askable" and "in the table" are
   the same moment.

**Retrieval** (`retrieval/search.py`): embed the question, cosine against every chunk in the
workspace, take the top `chat_top_k` (default 8) above `chat_min_similarity`, and always
append the records digests of the documents those chunks belong to. Open question 1 in the
requirements (a lexical pass for identifiers) is a Should: if time allows, add a simple
token-overlap score and take the union of the top results from both.

### 6.4 Chat answer (new, `chat/`)

Two model calls per answer, both on the Flash tier, run by a background task that writes
into an in-memory **answer buffer** (`chat/buffer.py`, one per in-flight message: a list of
events with sequence numbers plus an `asyncio.Condition`). The SSE route tails the buffer;
the task does not know or care whether anyone is listening (decision D44).

**Step 1, retrieve** (section 6.3). Emit `status: retrieving`, then `sources` and
`status: reading` with the count of passages and documents.

**Step 2, plan** (`CallKind.CHAT_PLAN`, structured). Prompt: the schema, the retrieved
passages tagged `[chunk:<id>] document "<name>" page <n>`, the records digests, the last
four turns, the question. Returns:

```python
class ChatPlan(BaseModel):
    answerable: bool
    not_answerable_reason: str | None
    visual: Visual | None           # section 6.5; the query spec, never numbers
```

If `visual` is present, evaluate its `DataQuery` (section 6.5), build the A2UI surface
(section 6.6), and emit `visual`. Otherwise emit `visual_skipped` with the reason. Either
way this happens **before** any prose token, so the visual card is on screen while the
answer streams beneath it (decision D47).

**Step 3, answer** (`CallKind.CHAT_ANSWER`, streamed text via `LLMClient.stream_text`).
Prompt: everything from step 2 plus, when a visual exists, the evaluated result as a
compact table with named paths (`result.total`, `result.rows[0].label`, and so on). Rules
in the system instruction:

- write only from the passages and the result; say plainly when they do not support an
  answer;
- cite every factual claim inline with `[^chunk:<id>]` markers; there are no quotes to
  write, the chunk is the citation (decision D45);
- refer to any figure that comes from the result with a placeholder, `{{result.total}}`,
  never by retyping it (decision D46); figures that appear verbatim in a cited passage may
  be repeated as written;
- do not mention the chart itself except as "the chart above" or "the table above".

**Stream processing** (`chat/stream.py`) transforms the raw token stream before it reaches
the buffer:

1. **Marker resolution.** Hold back text from an unmatched `[^` until its `]`. On close,
   validate the chunk identifier against the retrieved set. Known: assign the next citation
   number (or reuse an existing one for a repeated chunk), emit a `citation` event with the
   chunk's boxes (word span from `chunks.word_start` to `word_end`) and a short excerpt,
   then emit the token with the marker rewritten to `[^n]`. Unknown: drop the marker.
2. **Placeholder substitution.** Hold back text from an unmatched `{{` until `}}`. Resolve
   the path against the evaluated result and emit the formatted value (currency with code,
   date localised by type). An unresolvable path emits nothing and logs
   `chat.placeholder_unresolved`.
3. Everything else is forwarded as `token` events, coalesced to at most one event per 40 ms
   so a fast model does not produce thousands of tiny frames.

**Finish.** On completion, join the emitted text, persist the assistant message with
`status = done`, `content`, `sources`, `citations`, `visual`, `surface`, emit `done` with
the persisted message, fire `chat.progress` on the workspace stream, and release the
buffer after a grace period (60 s) so late resumers can still catch up. On `stop`, cancel
the task, persist with `status = stopped`. On a model failure, persist `status = failed`
with `error` and emit `error`.

**Query specification model** (`insights/queryspec.py`, shared with the dashboard):

```python
class DataQuery(BaseModel):
    measure_field: str | None       # field key; None means count of records
    aggregate: Literal['sum','count','avg','min','max']
    group_by: str | None            # field key
    bucket: Literal['none','month','quarter','year'] = 'none'   # for date group_by
    filters: list[Filter] = []      # {field, op: eq|ne|gt|gte|lt|lte|contains|missing|present, value}
    sort: Literal['value_desc','value_asc','label_asc'] = 'value_desc'
    limit: int = 20

class Visual(BaseModel):
    kind: Literal['metric','bar','line','table']
    title: str
    query: DataQuery
    unit_hint: str | None           # e.g. currency code the server should format with
```

**Citations to digest chunks.** A records-digest chunk has no page or boxes. A marker that
cites one resolves to the underlying record's field provenance: the `citation` event carries
the page and boxes of the field value the digest line came from, and the excerpt is the
`label: value` line. This keeps "every citation lights up on a page" true for structured
facts too.

**`LLMClient` changes.** The protocol gains `stream_text(request) -> AsyncIterator[str]`.
`GeminiClient` wraps `generate_content_stream` and yields `chunk.text`. `FakeClient` yields
a recorded answer in word-sized pieces with a small delay, so the client's streaming path is
exercised in tests and in a no-key clone (D13).

### 6.5 Query specification evaluation (new, `insights/`)

`insights/queryspec.py` holds the `DataQuery` model (shared with the dashboard).
`insights/evaluate.py` evaluates it in Python over the workspace's records:

- load records with their `field_values` (one query, the workspace is small);
- apply filters with type-aware comparison (`values.py` already parses every stored shape);
- group by the `group_by` field, bucketing dates when asked;
- aggregate the measure; `count` with no measure counts records;
- sort and limit;
- return `{columns: [{key, label, type}], rows: [{label, value, record_ids: [...]}]}`.

Every row carries the `record_ids` that contributed, and a `table` visual carries
`record_id` and `field_key` per cell, which is what lets provenance work inside A2UI (FR-43).

`insights/stats.py` computes per-field statistics for the dashboard planner: type,
coverage, distinct count, numeric min, max, and sum, date range, top five values.

### 6.6 A2UI building (new, `a2ui/`)

`a2ui/catalog.py` is the single declarative table of custom components and their property
schemas (mirrored by Zod on the client). `a2ui/build.py` turns an evaluated result plus a
`Visual` into a v0.9 message array:

```
createSurface        { surfaceId }
updateDataModel      { path: '/result', value: { title, unit, columns, rows } }
updateComponents     [ Column(root) → Text(title), <kind component bound to /result> ]
```

| Visual kind | Component     | Binding                                                          |
| ----------- | ------------- | ---------------------------------------------------------------- |
| metric      | `Metric`      | `value: {path: '/result/rows/0/value'}`, `label`, `unit`         |
| bar         | `BarChart`    | `rows: {path: '/result/rows'}`, `xKey: 'label'`, `yKey: 'value'` |
| line        | `LineChart`   | same as bar, used when `bucket != none`                          |
| table       | `ResultTable` | `columns`, `rows: {path: '/result/rows'}`                        |

Tests validate every emitted array against the v0.9 JSON Schema vendored under
`a2ui/schema/`. The model never sees or writes an A2UI message; it writes a `Visual`.

### 6.7 Dashboard generation (new, `insights/dashboard.py`)

Triggered when the last document of the first batch reaches a terminal state, and by
`POST /dashboard/generate`. One structured call to the Flash tier, `CallKind.PLAN_DASHBOARD`:

**Prompt:** document count, the schema, the per-field statistics, and the instruction to
propose up to six panels a person scanning this collection would want, each as a title, a
kind, a `DataQuery`, and a one-sentence rationale grounded in the statistics.

**Response model:** `DashboardPlan { panels: list[Panel] }` where `Panel` is `Visual` plus
`rationale: str`.

**Post-processing:** evaluate every panel; drop empty results, single-row bar charts, and
metrics over fields with coverage below a third; build a surface per surviving panel; write
the `dashboards` row; emit `dashboard.status`. Documents added, values corrected, or fields
merged set `stale = true`.

### 6.8 Suggested questions (new, `chat/suggestions.py`)

`CallKind.SUGGEST_QUESTIONS` on the Flash tier with the schema, statistics, and the first
digest chunk of three documents. Returns three short questions. Cached on the workspace until
the schema changes.

### 6.9 `CallKind` changes

`NL2SQL` is removed. Added: `CHAT_PLAN` (structured), `CHAT_ANSWER` (streamed text),
`PLAN_DASHBOARD`. `SUGGEST_QUESTIONS` stays. `needs_strong_model` remains true only for
extraction and schema calls.

---

## 7. A2UI integration (client)

> **Changed September 5, 2026.** This section originally specified `@a2ui/react` and
> `@a2ui/web_core` as the renderer. What is built renders the catalog itself, with no A2UI
> dependency. Decision **D60** records the argument, states plainly that it overrules a
> decision taken deliberately, and describes what switching back would cost — one module
> behind one component. The safety properties section 7.3 asked for are all kept.

### 7.1 Dependencies

None. `zod@3.25.76` stays pinned for now because it was pinned for the `@a2ui/react` peer
range, and unpinning it is a separate change that should not ride along with this one.

### 7.2 Module shape (`client/src/features/a2ui/`)

- `model.ts`: folds a message array into `{ data, components, rootId }`. `updateDataModel`
  writes at its path; `updateComponents` collects components, **dropping any name outside
  the catalog**. `resolvePath` walks `/`-separated paths, indexing arrays on numeric
  segments, so `/result/rows/0/value` resolves without a special case. `readProperty` is the
  single place a `{ path }` binding is resolved — the enforcement point for decision D37.
- `Surface.tsx`: renders `Metric`, `BarChart`, `LineChart`, `ResultTable` plus `Column`,
  `Row`, `Text`, `Card`, `Divider`, in this project's theme tokens. Total by construction: a
  missing binding renders an em dash, a chart with no rows renders nothing, recursion is
  depth-capped against a `children` cycle. `ResultTable` cells carry `record_ids` and open
  the viewer through a callback, which is what makes provenance work inside generated
  interface (FR-43).
- `SurfaceBoundary.tsx`: an error boundary around every surface. On a render error it logs
  `a2ui.fallback` and renders the rows from `/result` as a plain table — always possible,
  because the server always writes the data model. Keyed per message by the caller rather
  than resetting itself.

### 7.3 Safety

Unchanged in substance. The catalog is the allow-list and is applied at parse time, so an
unknown component never reaches the renderer. Strings render as text, never as markup. The
server caps components per surface at 40 and agent-provided strings at 400 characters
(`server/app/a2ui/catalog.py`); the client adds a depth cap and the boundary above.

### 7.4 Charts

Hand-drawn. A bar chart is a baseline rule with flex columns standing on it; a line chart is
one `polyline` in an SVG viewBox. Both are single-series by catalog definition. Recharts was
dropped with the rest of section 7.1.

---

## 8. Client implementation details

### 8.1 Workspace layout (`app/WorkspaceLayout.tsx`)

Header with wordmark, workspace label, "Add documents" (opens the same intake used on
screen 1), "Copy link" (D31), and two tabs: Chat and Data. The processing strip renders
under the header on both tabs while any document is not terminal. `useWorkspaceEvents`
opens the SSE connection once per layout and applies events to the TanStack Query cache.

### 8.2 Chat (`features/chat/`)

- `useChat`: `GET messages` on mount. Asking is a mutation: append the user bubble and an
  assistant bubble in `streaming` state, `POST messages`, then hand the returned
  `stream_url` to `useAnswerStream`.
- `useAnswerStream(messageId, streamUrl)` (`lib/sse.ts` underneath): opens a native
  `EventSource` (the stream is a `GET`, so no custom parser), applies events to a local
  reducer keyed by message id, and reconnects with backoff. The browser sends
  `Last-Event-ID` on its own reconnects; on a deliberate remount the hook passes the last
  seen id as a query parameter. On `done` it writes the persisted message into the TanStack
  Query cache and closes. On `error` or a terminal reconnect failure it falls back to
  `GET messages` to recover whatever was persisted. A **Stop** button calls the stop route
  and closes the source.
- Streaming reducer state per message: `stage`, `sources`, `visual` (or `skipped`), `text`
  (appended tokens), `citations` (by `n`), `status`. Tokens are appended into a `ref` and
  flushed to state on `requestAnimationFrame`, so a burst of frames costs one render.
- `AssistantMessage` renders, top to bottom: the **stage line** with source chips (collapses
  to a single "6 passages from 4 documents" line once prose starts); the **visual card**
  (`SurfaceHost` in a `SurfaceBoundary` with the inspect toggle) once `visual` arrives, with
  a fixed-height skeleton reserved from `status: planning` until `visual` or
  `visual_skipped` so the prose below never jumps; the **prose**, rendered by a small
  streaming markdown renderer that tolerates an unclosed emphasis or list at the tail and
  never emits raw HTML, with `[^n]` rendered as numbered buttons; a blinking caret while
  streaming; then the **citations list** as they resolve; and a "Stopped" or error footer
  when applicable. Decision D47 covers why the visual sits above the prose.
- Clicking a marker or citation calls
  `useViewer().open({documentId, pageIndex, boxes, excerpt})`. A `ResultTable` cell inside
  the visual opens the viewer the same way through the callback the host supplies.
- Auto-scroll follows the stream only while the user is at the bottom of the conversation;
  scrolling up pauses it and shows a "Jump to latest" pill.

### 8.3 Data (`features/data/`)

- `RecordsTable`: TanStack Table over `GET records`; columns from `GET schema`; cell
  renderers by type in `cells/`, each drawing the tier mark and label from theme tokens.
  Column header menu: sort, hide, rename, merge into.
- Cell click opens the viewer with the value's provenance and reasoning. Cell double-click
  (FR-50, Should) opens a type-specific editor; save issues the PATCH with optimistic
  update and rollback.
- `Dashboard`: `GET dashboard`; renders a `DashboardPanel` per panel (title, rationale,
  `SurfaceHost`), a stale banner, and Regenerate. Status changes arrive over events.

### 8.4 Source viewer (`features/viewer/`)

- `SourceViewer`: a right-side panel (Radix Dialog in non-modal mode) with the page image
  from `/pages/{n}/image`, page controls, and the detail card.
- `HighlightLayer`: draws rectangles from boxes in page points scaled by
  `renderedWidth / width_pt`. Same code for every format because every format is a backend
  render (D18, D43). A unit test asserts the scaling with a known fixture.

### 8.5 State

- Server state in TanStack Query, mutated by workspace SSE events.
- In-flight answer state in the `useAnswerStream` reducer, local to the chat feature; it is
  written into the TanStack Query cache only on `done`, so the cache holds persisted truth
  and the reducer holds the live stream.
- UI state in one Zustand store: viewer target, inspect toggle, hidden columns (persisted
  per workspace in `localStorage`).
- A2UI state lives inside each `SurfaceHost`'s processor and is never copied elsewhere.

---

## 9. Testing strategy

**Backend (pytest, `uv run pytest` from `server/`; about 350 tests exist)**

- Existing: parsers, geometry, grounding, scoring, values, schema similarity and drift,
  event stream resume, offline extraction, workspaces and view integration.
- Remove: tests for proposals, review queue, schema revert, and `schema/view.py`.
- New: chunking (boundaries, overlap, word spans map back to boxes); retrieval ranking on a
  fixture corpus with recorded vectors; `DataQuery` evaluation (filters per type, date
  buckets, count without measure, empty results); stream processing with markers and
  placeholders split across token boundaries, unknown chunk identifiers dropped, repeated
  chunks reusing a number, `citation` emitted before its token; the answer buffer replays
  from a given sequence and a late subscriber to a finished message receives one `done`;
  stop persists partial text; A2UI builders validate against the v0.9 JSON Schema for every
  kind; dashboard post-processing drops degenerate panels; merge moves values and
  provenance and preserves verified status.

**Frontend (Vitest + Testing Library + MSW)**

- Existing: theme contrast, file intake, first-run screen.
- New: highlight scaling math; cell renderers show a tier mark and label; `SurfaceHost`
  renders each catalog component from a fixture array; an unknown component triggers the
  fallback and logs; the answer stream reducer applies a recorded event sequence and yields
  the expected text, citations, and visual, in order; a `visual` event before tokens fills
  the reserved skeleton without shifting the prose; a citation button opens the viewer; a
  reconnect replays from the last id without duplicated text; Stop leaves partial text
  marked stopped; the processing strip applies `document.status` events without remounting
  rows.

**End to end**

A written demo script in the README (requirements section 8), run manually before
submission. Playwright is cut for this round.

---

## 10. Setup, deployment, observability

**Local setup (`make setup`)**: checks for Homebrew; installs `postgresql@16`, `tesseract`,
`uv` if missing; starts Postgres; creates the `distill` database and role from
`server/scripts/bootstrap_db.sql`; `uv sync` in `server/`; `npm ci` in `client/`; runs
`alembic upgrade head`. **`make dev`** starts Uvicorn with one worker (D9) and Vite with the
`/api` proxy. Environment: `GEMINI_API_KEY` is the only required variable with
`LLM_PROVIDER=gemini`; `LLM_PROVIDER=fake` runs everything offline against recorded fixtures.

**Deployment**: out of scope to verify without a container runtime. A `Dockerfile` and
`docker-compose.yml` may be authored as a Could; the README states plainly whether they were
tested.

**Observability**: structlog JSON with `request_id`, `workspace_id`, `document_id`, stage
timings, and per-call model, tokens, latency. Chat and dashboard calls log the retrieved
chunk identifiers and whether a visual was dropped. The client logs `upload.start`,
`chat.ask`, `chat.answered`, `chat.visual_dropped`, `a2ui.fallback`, `dashboard.generated`.

---

## 11. Plan for the remaining days

Day 1 (September 3) and day 2 (September 4) built the backend pipeline, schema inference,
events, the client scaffold, and the upload screen. Today also carries this pivot.

| Day                | Backend                                                                                                                                                                                                                                                                                                                                        | Client                                                                                                                                                                                                                                                            | Shippable at end of day                                                                                        |
| ------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| **3, Sept 5**      | Remove proposals, review, revert, backfill, view, sqlglot. `chunks` and `chat_messages` migrations. Chunking, embedding, retrieval. `DataQuery` model and evaluator with tests. `LLMClient.stream_text` on Gemini and the fake. Plan call, answer buffer, stream processor (markers, placeholders), the three chat routes. `CallKind` changes. | `WorkspaceLayout` with tabs, add-documents, processing strip over SSE. `lib/sse.ts`, `useAnswerStream`, and the `ChatScreen` streaming prose with citation buttons (no visuals yet). `SourceViewer` with highlights from citations.                               | Ask a question and watch it stream with citations that light up the page.                                      |
| **4, Sept 6**      | A2UI builders and JSON Schema validation. Visual planning and the `visual` event. Suggestions. Sample corpus and manifest. Stop route.                                                                                                                                                                                                         | Install A2UI and Recharts. `a2ui/` module with four catalog components, fallback, inspect. Visual card with reserved skeleton in `AssistantMessage`. Stop button, reconnect, jump-to-latest. `RecordsTable` with typed cells and tiers, cells opening the viewer. | The chat screen works end to end: sources, chart, streaming prose, citations. The table is visible with tiers. |
| **5, Sept 7**      | Field stats, dashboard planner, evaluation, persistence, stale marking, auto-generation on first batch. Schema merge. Delete cascades chunks.                                                                                                                                                                                                  | `Dashboard` with panels, rationale, stale, regenerate. Column menu rename and merge. Inline cell edit (Should). Empty and error states.                                                                                                                           | The Data screen works end to end. Demo script passes.                                                          |
| **Buffer, Sept 8** | Export CSV. Lexical retrieval pass.                                                                                                                                                                                                                                                                                                            | Accessibility pass, polish.                                                                                                                                                                                                                                       | README, `decisions.md` final review, submission.                                                               |

Buffer strategy: if day 4 slips, `LineChart` is cut and `Metric`, `BarChart`, `ResultTable`
carry the chat. If day 5 slips, the dashboard ships with automatic generation only and no
regenerate control, and inline cell edit is dropped in favour of demonstrating the
correction guarantee through the re-extract route.

---

## 12. Verification checklist for the remaining work

- [ ] `@a2ui/react@0.11.0` and `@a2ui/web_core@0.10.7` install with React 19.2.8 and Zod 3.25.76; a `Metric` surface renders from a fixture array under Vitest.
- [ ] Exact export names for child references and the data-binding `path` shape in `@a2ui/react/v0_9` (changed in 0.11.0).
- [ ] The v0.9 JSON Schema file vendored into `server/app/a2ui/schema/` and used by tests.
- [x] Gemini `gemini-embedding-001` output dimension confirmed with a real key (native 3072, requested at 768, normalised in the adapter); cosine tested against it. September 5, 2026, decision D63.
- [x] `generate_content_stream` yields text deltas at a cadence that makes the 3 s first-token target realistic: 0.68 to 0.85 s to first token on `gemini-3.5-flash-lite`, against 8.8 to 9.8 s on `gemini-3.5-flash`, which is why the fast tier is Lite. September 5, 2026, decision D62.
- [x] Embedding thresholds calibrated against a real model: synonym pairs 0.822 to 0.982, unrelated pairs 0.764 to 0.827, so auto-map moves to 0.88 and the novelty ceiling to 0.80. September 5, 2026, decision D66.
- [x] Dashboard panels render their A2UI surfaces: a metric and a bar chart on the sample corpus, matching `samples/expected.json` (decision D75). They had been arriving and being discarded.
- [x] Response schemas accepted by a real Gemini call, closing review finding 8.7. Two faults found and fixed in the same pass: `maxItems` is rejected outright (D64) and an optional nested model lost its shape in conversion (D65).
- [ ] `sse-starlette` sends `id:` lines and honours `Last-Event-ID` on the per-message route the same way it does on `/events`; a Vite dev proxy passes `text/event-stream` through unbuffered.
- [x] `DataQuery` evaluation on the sample corpus produces the "total by vendor" and "missing purchase order count" results the demo script needs. Verified September 6, 2026 against `samples/expected.json`: 16,752.90 USD across five vendors, and 3 invoices with no purchase order. The count needed a planner rule first, since it was counting contracts and bank statements too (decision D69).
- [x] Sample corpus contains at least one non-invoice document with prose (a contract or policy) so the retrieval demo has something non-tabular to cite. It has two, a two-page services agreement and an expense policy, and both answer cited questions (decision D67).
- [x] pdfplumber coordinate convention asserted against a fixture (decision D17, done).
- [x] `create-vite` TypeScript version and `openapi-typescript` behaviour (decision D33, done).
