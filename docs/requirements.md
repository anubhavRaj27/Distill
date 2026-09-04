# Distill: Requirements Document (v2)

**Project round task:** Problem 1, "Turn messy documents into structured, queryable data"
**Author:** Anubhav Raj
**Date:** September 4, 2026 (v1 was September 2, 2026)
**Status:** v2, governing. Supersedes v1 in full.
**Build window:** 4 to 5 days from September 3, 2026

---

## 0. What changed from v1, and why

v1 framed the product around **schema unification with a human review loop**: proposal
cards for uncertain field matches, schema history with one-click revert, a review queue with
a keyboard flow, and a natural-language-to-SQL query console. Two days of backend work went
into that plan and most of it runs.

v2 changes the product, not the pipeline underneath it. The judgment behind the change is
recorded in decisions D34 through D43, and in one sentence: **the review loop asks a finance
operations person to do schema administration, and that is not the job they came to do.**
They came to get a pile of documents read, ask questions across it, and see what is in it.
So v2 is:

1. **Upload** many documents at once.
2. **Chat** with the whole pile. Answers cite the exact region of the source document. When
   an answer has numbers in it, the agent shows them as a metric, a chart, or a table that
   it chose, rendered through A2UI, and the numbers are computed by the server from the
   extracted data rather than written by the model.
3. **Data**: one table of everything extracted, plus a dashboard of charts and metrics the
   agent decided were worth showing, generated on the fly and also rendered through A2UI.

| Cut from v1                                                            | Why                                                                                                                                                                                                          |
| ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Schema proposal cards, `initial_schema` and `drift` questions          | Schema administration is not the user's job. Uncertain matches resolve to the safe default (a separate field) without a prompt. Decision D38.                                                                |
| Schema history view and one-click revert                               | Only mattered because the system was asking the user to make schema decisions. With no decisions to reverse, there is nothing to show.                                                                       |
| Review queue and keyboard review flow                                  | A second screen dedicated to checking cells competes with the chat for the user's attention. Confidence stays visible on the table; the queue goes. Decision D42.                                            |
| Natural language to SQL, generated-SQL panel, the four-limit SQL guard | Replaced by retrieval over the documents themselves. SQL over a typed view answers only questions the schema anticipated; retrieval answers questions about anything written in the documents. Decision D35. |
| Backfill of a new field across old documents                           | Belonged to the schema-editing loop.                                                                                                                                                                         |
| Virtualized 5,000-row table                                            | A workspace holds tens of documents, not thousands.                                                                                                                                                          |
| `docker compose up` as the setup path                                  | No container runtime on the development machine, so it cannot be verified. Setup is a Makefile against local Postgres. Kept as a Could.                                                                      |

Everything about **provenance and trust stays**: every value on screen, in the table or in a
chat answer, traces to a highlighted region of its source document, confidence tiers remain
visible, and a human correction is never overwritten by the model.

---

## 1. Problem framing

### 1.1 The prompt, as written

> Build a system that takes unstructured or semi-structured documents and converts them into
> clean, structured data that can be searched and queried.

### 1.2 How we interpret it

The prompt has three jobs hiding in it:

1. **Read everything.** Turn PDFs, scans, spreadsheets, Word files, and text into one table
   of general facts, without being told the fields in advance. A Large Language Model (LLM)
   does the reading; the system's job is to make the result consistent across documents that
   disagree with each other about names and formats.
2. **Answer questions across the pile.** "Which invoices over 10,000 have no purchase order?"
   "What did we pay Acme in Q2?" "What does the lease say about early termination?" The
   first two are structured questions, the third is not. A person does not want two tools.
3. **Show me what is in here.** Before anyone types a question, the system should already
   have looked at the data and put the useful shapes on screen.

### 1.3 The hard sub-problem we are owning

**Trustworthy answers across heterogeneous documents.** Concretely:

- an answer must cite the passage it came from, and the passage must light up on the page;
- a number in an answer must be computed from extracted data by deterministic code, not
  produced by the model's prose (decision D37, the data-binding rule);
- the presentation of an answer (a sentence, a metric, a chart, a table) is chosen by the
  agent from what the data actually looks like, and rendered by the client from a trusted
  component catalog (A2UI);
- the same guarantees hold for the dashboard the agent generates without being asked.

Single-document extraction is table stakes and is already built.

### 1.4 Who this is for

**Primary persona: a finance operations person at a small or mid-sized company.** They
receive vendor invoices, receipts, purchase orders, bank statements, and contracts as PDFs,
scans, spreadsheets, and forwarded emails. They currently retype values into a spreadsheet
and cannot answer cross-document questions without hours of manual work.

Their jobs to be done:

- "Turn this pile into a table I can scan and sort."
- "Let me ask questions about it in plain English and show me where the answer came from."
- "Tell me what is interesting in here before I ask."
- "When I add more documents next week, do not break what I have."

**The system must remain domain-agnostic.** Finance documents are the demo corpus and the
default examples, not a hard-coded assumption. Research papers or property listings must get
the same experience.

### 1.5 What we are deliberately leaving out (and why)

| Cut                                                                           | Reason                                                                                                                         |
| ----------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| Authentication and multi-user accounts                                        | A day of work that demonstrates nothing about the problem. Each browser gets an anonymous workspace token (decisions D8, D31). |
| Real-time multi-user collaboration                                            | Orthogonal.                                                                                                                    |
| Handwriting recognition                                                       | Optical Character Recognition (OCR) of typed scans is in scope; handwriting is a research problem.                             |
| Fine-tuning or custom models                                                  | Hosted Gemini with structured output (decision D13).                                                                           |
| Multi-turn conversation memory beyond the current workspace's message history | The chat sends recent turns as context; there is no long-term memory or summarisation.                                         |
| Export to accounting systems                                                  | CSV export of the table is a Could.                                                                                            |
| A general-purpose SQL editor                                                  | There is no SQL in the product any more.                                                                                       |

---

## 2. Product principles

1. **Three screens, nothing else.** Upload, Chat, Data. Anything that wants a fourth screen
   is out of scope for this round.
2. **Show your work.** Every value in the table and every claim in a chat answer can be
   traced to a highlighted region of a source document in one click. No exceptions.
3. **Numbers come from data, never from the model's prose.** When the agent wants to show a
   figure, it emits a reference to a variable or a query specification. The server evaluates
   it against the extracted records and binds the result into the interface. The model does
   not retype numbers. (Decision D37.)
4. **The agent chooses the shape, the client owns the pixels.** Whether an answer is a
   sentence, a metric, a bar chart, or a table is the agent's call, expressed as A2UI. Only
   catalog components render, so agent-chosen never means unsafe.
5. **Uncertainty is visible, not interrupting.** Low-confidence values look different from
   high-confidence ones on the table. Nothing pops up to ask the user to adjudicate.
6. **Never lose a human correction.** If a person edits a value, re-extraction does not
   overwrite it. The backend already enforces this (decision D16).
7. **Degrade, don't die.** A failed document, a timed-out model call, an unanswerable
   question, or a malformed A2UI payload each produce a specific message and leave the rest
   of the workspace usable.

---

## 3. Screens and user journeys

### 3.1 Screen 1: Upload

Route `/`. Already built.

1. A first-time visitor sees one sentence, a drop zone, "Choose files", and "Try with sample
   documents".
2. Dropping files or clicking the sample button creates a workspace, uploads, and navigates
   to the Chat screen. Processing runs in the background and streams status.
3. Unsupported types and files over 20 MB are refused inline before upload.
4. The screen carries the same application header as the other two, showing all three
   screens with Chat and Data inert until a workspace exists, so the shape of the product is
   legible before anything is uploaded (decision D51).
5. Beneath the drop zone, an illustration of six mismatched documents falling through a
   funnel into one ruled table. It is the argument of the product made before the person has
   done anything, and it is decorative: its caption carries the same meaning in words.

Documents can also be added later from inside the workspace (a small "Add documents" control
in the workspace header, on both the Chat and Data screens). Added documents run through the
same pipeline; the chat can use them as soon as they are indexed, and the dashboard marks
itself stale until regenerated.

### 3.2 Screen 2: Chat (the main screen)

Route `/w/{id}` and `/w/{id}/chat`.

1. The screen opens on a conversation view with a composer at the bottom and, while the
   first batch is still processing, a compact processing strip at the top showing each
   document's stage. Three suggested questions appear once the first documents finish, and
   are generated from the actual extracted schema and content.
2. The user asks a question in plain language. An assistant bubble appears at once and
   **streams** over Server-Sent Events (SSE), in this order:
   - a stage line: "Finding relevant passages", then "Reading 6 passages from 4 documents"
     with the source documents shown as chips;
   - if the agent decided the answer has a quantitative shape, a **visual card** (metric,
     bar chart, line chart, or table) slides in at the top of the message before any prose.
     It is an A2UI surface whose data the server computed from the extracted records
     (principle 3). A table visual's cells carry provenance and open the viewer;
   - the **prose**, token by token. Citation markers become numbered buttons the moment
     they appear, and any figure the prose quotes from the visual is substituted by the
     server from the computed result rather than written by the model;
   - the **citations** list under the prose: document name, page, locator, and an excerpt.
     Clicking a marker or a citation opens the source viewer with the passage highlighted.
3. The user can stop a streaming answer; what has arrived is kept and marked as stopped.
   If the connection drops, the client reconnects and resumes from the last event it saw;
   generation continues on the server regardless.
4. If the question cannot be answered from the documents, the answer says so and names what
   would be needed, rather than guessing.
5. The conversation persists with the workspace: a refresh or a shared link shows the same
   history, including visuals and citations.

### 3.3 Screen 3: Data

Route `/w/{id}/data`.

1. **The table.** One row per document, one column per unified field. Cells are typed
   (currency with code, dates localised, booleans as marks, lists as chips) and carry their
   confidence tier through a mark and a label, never colour alone. Columns sort; columns can
   be hidden; a column menu allows rename and "merge into" for the case where the system
   kept two fields apart that the user knows are one (decision D38). Clicking a cell opens
   the source viewer with the region highlighted and the model's short reasoning.
2. **The dashboard.** Below (or beside, on wide screens) the table, a set of panels the
   agent generated: metrics and charts it judged useful given the fields, their coverage,
   and their value distributions. Each panel has a title and a one-line rationale ("Six of
   eight documents carry a total and a vendor, so spend by vendor is answerable"). Panels are
   A2UI surfaces bound to server-computed data (principle 3). A "Regenerate" control asks the
   agent again; a stale marker appears when documents were added since the last generation.
3. The dashboard is generated automatically the first time all documents of the first batch
   reach a terminal state, so a user arriving on the Data screen after the sample set loads
   already sees panels.

### 3.4 The source viewer (shared)

Not a screen. A right-hand panel that opens from any citation or table cell and closes with
Escape.

- Shows the page as an image rendered by the backend (every format, including PDF, is
  rendered to page images; decisions D18 and D43), with one or more highlight rectangles
  over the cited words.
- Shows the quoted text, the page number, the human-readable locator for non-paginated
  sources (sheet and row, paragraph number), and, for table cells, the model's reasoning
  and confidence tier.
- Offers page navigation within the document and a link to download the original.

### 3.5 Things going wrong

| Situation                                                   | Required behaviour                                                                                                |
| ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| A PDF is password protected or corrupt                      | Processing strip row shows "Could not read this file: it appears to be password protected." Other files continue. |
| A scanned page has no extractable text                      | Row shows "Scanned image detected, running OCR", then proceeds or fails with a clear message.                     |
| The model call times out or is rate limited                 | Row shows "Extraction is taking longer than usual, retrying (2 of 3)." After final failure: a Retry action.       |
| A question has no supporting passages                       | Answer says what was searched and suggests a rephrasing or names the missing information. Never a blank message.  |
| The agent's visual specification evaluates to no data       | The visual is dropped and the prose answer stands alone; a log event records it.                                  |
| The A2UI payload is malformed or names an unknown component | Fallback renderer shows the underlying data as a plain table. The user never sees a blank area.                   |
| Backend unreachable                                         | Global banner. Cached table and conversation stay visible, read-only.                                             |
| Dashboard generation fails                                  | The table is unaffected; the dashboard area shows the failure and a Retry.                                        |

---

## 4. Functional requirements

Priority uses MoSCoW: **M**ust, **S**hould, **C**ould, **W**on't (this round). Identifiers
are new in v2; v1 identifiers are retired.

### 4.1 Workspace and ingestion

| ID    | Requirement                                                                                                                                                                    | Priority |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------- |
| FR-01 | Create an anonymous workspace on first visit; the token is stored in the browser and carried in the fragment of a shareable link (decision D31).                               | M        |
| FR-02 | Drag-and-drop and file-picker upload of many files at once; supported types PDF, PNG, JPG, JPEG, DOCX, XLSX, CSV, TXT.                                                         | M        |
| FR-03 | Reject unsupported types and files over 20 MB inline, before upload begins.                                                                                                    | M        |
| FR-04 | Per-document processing status with stages and failure reasons, streamed live over Server-Sent Events (SSE), visible on the Chat and Data screens while anything is in flight. | M        |
| FR-05 | "Try with sample documents" loads a curated heterogeneous set in one click.                                                                                                    | M        |
| FR-06 | Add more documents to an existing workspace from the workspace header.                                                                                                         | M        |
| FR-07 | Delete a document from the workspace; its row, chunks, and citations go with it.                                                                                               | S        |

### 4.2 Extraction and the unified table

| ID    | Requirement                                                                                                                                                                                                           | Priority |
| ----- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| FR-10 | Extract salient fields from every document with no schema given in advance, and infer one unified schema from the first batch automatically. No confirmation step.                                                    | M        |
| FR-11 | Later documents are extracted against the current schema. New fields are added and confident renames are mapped automatically; an uncertain match is kept as a separate field rather than asked about (decision D38). | M        |
| FR-12 | Field types: string, number, currency (amount plus ISO 4217 code), date, boolean, enum, list of strings.                                                                                                              | M        |
| FR-13 | The Data screen shows one table: a row per document, a column per field, typed cell rendering, sortable columns, column show/hide.                                                                                    | M        |
| FR-14 | Each cell shows its confidence tier (high, medium, low, conflict, verified) with a mark and label, never colour alone.                                                                                                | M        |
| FR-15 | Column menu: rename a field; merge a field into another (values move, provenance intact).                                                                                                                             | S        |
| FR-16 | Export the table to CSV.                                                                                                                                                                                              | C        |

### 4.3 Chat

| ID    | Requirement                                                                                                                                                                                                                                                                                                                                                                  | Priority |
| ----- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| FR-20 | A conversation per workspace, persisted server-side, shown on the Chat screen with a composer.                                                                                                                                                                                                                                                                               | M        |
| FR-21 | Answers are produced by retrieval over the documents' text plus the extracted records: the relevant passages are found by embedding similarity, and the model answers from those passages and the structured data only.                                                                                                                                                      | M        |
| FR-22 | Every factual claim in an answer carries a citation to a passage; each citation opens the source viewer with the passage highlighted. Citations resolve while the answer streams, not after (decision D45).                                                                                                                                                                  | M        |
| FR-23 | When an answer has a quantitative shape, the agent may attach one visual (metric, bar chart, line chart, or table). The visual's data is a query specification evaluated by the server over the extracted records; the model never supplies the numbers (decision D37). Figures the prose quotes from that result are placeholders substituted by the server (decision D46). | M        |
| FR-24 | Visuals are rendered through A2UI from the project catalog; a table visual's cells keep provenance links. In chat, the visual arrives as one complete surface before the prose and renders at the top of the message (decision D47).                                                                                                                                         | M        |
| FR-25 | Three suggested questions, generated from the workspace's actual schema and content, shown when the conversation is empty.                                                                                                                                                                                                                                                   | S        |
| FR-26 | Answers stream token by token over a per-message SSE stream that also carries stage, sources, the visual, and citations as they become available. The first visible event arrives within 1 s of asking and the first prose token within 3 s on the Flash tier (decision D44).                                                                                                | M        |
| FR-27 | An unanswerable question gets an explicit "not in these documents" answer naming what was searched.                                                                                                                                                                                                                                                                          | M        |
| FR-28 | The last few turns are sent as context so follow-up questions ("now only Q2") work.                                                                                                                                                                                                                                                                                          | S        |
| FR-29 | A streaming answer can be stopped by the user; a dropped stream resumes from the last event identifier without losing or duplicating text; generation completes on the server even if no client is listening, and the persisted message is what a refresh shows.                                                                                                             | M        |

### 4.4 Dashboard

| ID    | Requirement                                                                                                                                                                                                                                | Priority |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------- |
| FR-30 | The agent proposes up to six dashboard panels from the schema and per-field statistics (type, coverage, distinct count, numeric range, top values). Each panel is a title, a visual kind, a query specification, and a one-line rationale. | M        |
| FR-31 | The server evaluates every panel's query over the records and drops panels with empty or degenerate results before anything is shown.                                                                                                      | M        |
| FR-32 | Panels render as A2UI surfaces bound to the evaluated data.                                                                                                                                                                                | M        |
| FR-33 | The dashboard is generated automatically when the first batch finishes, can be regenerated on demand, and is marked stale when documents are added or values corrected.                                                                    | M        |
| FR-34 | Panels are persisted with the workspace so a refresh does not re-run generation.                                                                                                                                                           | S        |

### 4.5 Provenance

| ID    | Requirement                                                                                                            | Priority |
| ----- | ---------------------------------------------------------------------------------------------------------------------- | -------- |
| FR-40 | Clicking a table cell or a chat citation opens the source viewer at the right page with the source region highlighted. | M        |
| FR-41 | The viewer shows the quoted text, page, and locator; for table cells also the model's reasoning and confidence tier.   | M        |
| FR-42 | Every format is shown as a backend-rendered page image with the same overlay code path (decisions D18, D43).           | M        |
| FR-43 | A2UI table visuals carry `record_id` and `field_key` per cell so provenance works inside agent-generated UI.           | S        |

### 4.6 Corrections

| ID    | Requirement                                                                                                                                          | Priority |
| ----- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| FR-50 | Inline edit of a table cell with type validation; the value becomes human-verified.                                                                  | S        |
| FR-51 | Re-extraction never overwrites a human-verified value; if the model now disagrees, the cell shows the conflict tier with both values (decision D16). | M        |
| FR-52 | Corrections and merges mark the dashboard stale (FR-33).                                                                                             | S        |

---

## 5. Non-functional requirements

| Area            | Requirement                                                                                                                                                                                                                                                                                                                            |
| --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Performance     | First contentful paint under 1.5 s on a mid-range laptop. In chat: first stream event under 1 s, first prose token under 3 s, a typical answer complete in under 12 s on the Gemini Flash tier. Token rendering never blocks input. Dashboard generation under 30 s.                                                                   |
| Accessibility   | WCAG 2.1 AA target: keyboard navigation, visible focus, ARIA labels on custom controls, confidence never conveyed by colour alone, minimum 4.5:1 contrast (asserted in tests, decision D32).                                                                                                                                           |
| Resilience      | All network calls have timeouts and typed error states. Both SSE streams (workspace events and per-message answer streams) reconnect with backoff and resume from the last event identifier. No unhandled promise rejections in normal use.                                                                                            |
| Observability   | Backend: structured logs with correlation identifier, workspace, document, stage timings, model token counts and latency per call. Frontend: structured events (upload started, answer requested, answer rendered, visual dropped, A2UI fallback) to the console in development. Every error surface shows the correlation identifier. |
| Security        | Agent-generated UI is untrusted input: only catalog components render, no HTML, string length caps, component count caps. The model never produces code or SQL that is executed. Uploaded files are validated by content, not extension.                                                                                               |
| Browser support | Latest two versions of Chrome, Firefox, Safari, Edge. Desktop first; tablet usable.                                                                                                                                                                                                                                                    |
| Setup           | `make setup` then `make dev` on a machine with Homebrew: installs Postgres 16, Python 3.12 via `uv`, Tesseract, Node dependencies; creates the database; runs migrations; starts both servers. One environment variable, `GEMINI_API_KEY`.                                                                                             |

---

## 6. A2UI requirements

### 6.1 What A2UI is and where it is used

A2UI (Agent-to-User Interface) is an open protocol from Google in which an agent emits
declarative JSON describing _what_ interface it wants (a column containing a text and a bar
chart bound to a data path), and the client renders it from its own trusted component
catalog. The agent never sends HTML or code.

v2 uses A2UI in two places, both of which are "the agent decided what to show":

1. **Visuals inside chat answers** (FR-23, FR-24).
2. **Dashboard panels** (FR-30 to FR-34).

Both are built on the same mechanism: the server evaluates a query specification into a
result set, writes that result into the A2UI **data model**, and emits components whose
properties are **path bindings** into that data model. This is the data-binding rule from
principle 3 made concrete: the model chooses `BarChart` and says "the series is at
`/result/rows`"; the server puts real rows there.

### 6.2 Requirements

| ID    | Requirement                                                                                                                                                                                                                                                                                                                  | Priority |
| ----- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| A2-01 | Use the official `@a2ui/react` renderer with the v0.9 protocol (`@a2ui/react/v0_9`, `@a2ui/web_core/v0_9`), pinned to exact versions verified at install time.                                                                                                                                                               | M        |
| A2-02 | A project catalog with Zod schemas: `Metric`, `BarChart`, `LineChart`, `ResultTable`, plus the basic catalog for layout and text. `ResultTable` cells may carry provenance.                                                                                                                                                  | M        |
| A2-03 | The backend builds A2UI messages (`createSurface`, `updateComponents`, `updateDataModel`) as complete arrays. In chat the array is sent as one `visual` event on the answer stream before prose tokens; on the dashboard it is stored with the panel. Every emitted message validates against the v0.9 JSON Schema in tests. | M        |
| A2-04 | Every surface is wrapped in an error boundary with a deterministic fallback that renders the data model's result rows as a plain table. Fallback triggers are logged.                                                                                                                                                        | M        |
| A2-05 | Agent-provided strings are untrusted: rendered as text, length capped, component count per surface capped.                                                                                                                                                                                                                   | M        |
| A2-06 | A developer-only "Inspect surface" toggle shows the raw A2UI JSON for a chat visual or dashboard panel.                                                                                                                                                                                                                      | S        |
| A2-07 | User actions inside surfaces round-trip to the backend (for example clicking a `ResultTable` row to open the viewer is handled client-side; a future "drill into this bar" action would post back).                                                                                                                          | C        |

### 6.3 Known risks (as of September 4, 2026)

- The React renderer is at 0.11.0 and has shipped breaking changes in minor versions.
  Mitigation: exact pins, small catalog, a renderer smoke test per catalog component.
- Peer dependency on React 19.2 and Zod 3.x. Zod is pinned to `3.25.76` project-wide.
- No official Python emitter. The backend emits plain JSON validated against the spec's
  JSON Schema.
- All A2UI knowledge is confined to `client/src/a2ui/` and `server/app/a2ui/`.

---

## 7. Frontend to backend contract (summary)

Detailed in the implementation document. All routes under `/api/v1`, workspace token as a
bearer header.

- `POST /workspaces`; `GET /workspaces/{id}` for the cold-start payload (schema, documents,
  counts, dashboard state).
- `POST /workspaces/{id}/documents` multipart; `POST .../documents/seed`;
  `DELETE .../documents/{docId}`; `GET .../documents/{docId}/file`;
  `GET .../documents/{docId}/pages/{n}/image`.
- `GET /workspaces/{id}/events` SSE: document status, record upserts, field updates, schema
  updates, chat progress, dashboard state.
- `GET /workspaces/{id}/records`; `PATCH .../records/{recId}/fields/{key}`.
- `GET /workspaces/{id}/schema`; `PATCH .../schema` for rename and merge.
- `GET /workspaces/{id}/chat/messages`; `POST .../chat/messages` with `{question}` starts
  generation and returns `{message_id, stream_url}`; `GET .../chat/messages/{msgId}/stream`
  is the per-message SSE stream (stage, sources, visual, tokens, citations, done), resumable
  with `Last-Event-ID`; `POST .../chat/messages/{msgId}/stop`.
- `GET /workspaces/{id}/chat/suggestions`.
- `GET /workspaces/{id}/dashboard`; `POST .../dashboard/generate`.
- `GET /workspaces/{id}/export?format=csv` (Could).

---

## 8. Acceptance criteria (demo script)

The submission is acceptable when a judge can, without help:

1. Open the URL, click "Try with sample documents", land on the Chat screen, and watch the
   processing strip complete within 60 seconds while suggested questions appear.
2. Ask "total amount by vendor" and watch the answer stream: source chips, then a bar chart
   sliding in, then prose token by token with citation buttons appearing as it goes; click a
   citation and see the source invoice open with the passage highlighted. Stop an answer
   midway and see the partial text kept and marked stopped.
3. Ask "how many invoices are missing a purchase order number" and get a metric; ask "what
   does the contract say about payment terms" and get a cited passage that lights up on the
   page; ask something not in the documents and get an explicit "not in these documents".
4. Open the Data screen and see the unified table with confidence tiers, plus a dashboard of
   panels the agent generated, each with a rationale. Click any cell and see its highlight.
5. Toggle "Inspect surface" on a chart and see the A2UI JSON, including the `updateDataModel`
   message holding the server-computed rows.
6. Add a new document of a different kind from the header; watch it flow through the
   processing strip, appear as a table row, become askable in chat, and mark the dashboard
   stale; regenerate.
7. Edit a cell, re-extract that document, and confirm the edit survives.
8. Clone the repository and run `make setup && make dev` with one environment variable.

---

## 9. Mapping to the evaluation criteria

| Criterion        | Where it shows up                                                                                                                                                                                                                     |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Problem framing  | Section 1: three jobs, the trust sub-problem, and section 0's honest account of the pivot.                                                                                                                                            |
| Product thinking | A finance ops persona with named jobs; three screens and nothing else; the data-binding rule that keeps numbers honest.                                                                                                               |
| UX decisions     | Chat-first with streaming that shows sources, then the visual, then prose; citations that light up as they appear; agent-chosen presentation with a safe fallback; confidence visible without interrupting.                           |
| Code quality     | Feature-folder client; one A2UI module per side; typed API client generated from OpenAPI; deterministic query evaluation separated from the model.                                                                                    |
| Tests            | Grounding, tier derivation, chunking and retrieval, query-spec evaluation, placeholder substitution across token boundaries, citation resolution mid-stream, A2UI message validation, fallback rendering, SSE resume on both streams. |
| Documentation    | This document, the implementation document, `decisions.md` with the pivot recorded rather than hidden, README with setup and demo script.                                                                                             |
| Setup experience | `make setup && make dev`, one environment variable, sample documents bundled.                                                                                                                                                         |
| Velocity         | Three-day plan in the implementation document from a working pipeline.                                                                                                                                                                |
| Above and beyond | Agent-generated dashboard with rationales; visuals whose numbers are provably computed, not generated; provenance inside agent-generated UI.                                                                                          |

---

## 10. Open questions to resolve in `decisions.md`

- Whether the chat's retrieval should also include a lexical (keyword) pass alongside
  embedding similarity, for identifiers like invoice numbers that embeddings handle poorly.
  Leaning yes as a Should; see implementation section 6.3.
- Whether the dashboard should regenerate automatically on every new document or only mark
  itself stale. v2 says mark stale; automatic regeneration costs a model call per upload.
- Whether inline cell editing (FR-50) ships in this round or the backend guarantee alone is
  demonstrated through the re-extract route. Leaning ship, since the backend route exists
  and the cell editor is small.
