# Sift: Requirements Document (Frontend Focus)

**Project round task:** Problem 1, "Turn messy documents into structured, queryable data"
**Author:** Anubhav
**Date:** September 2, 2026
**Status:** Draft v1
**Build window:** 5 days

---

## 1. Problem framing

### 1.1 The prompt, as written

> Build a system that takes unstructured or semi-structured documents and converts them into clean, structured data that can be searched and queried.

### 1.2 How we interpret it

The prompt hides three separate problems, and most submissions will solve only the first:

1. **Extraction.** Pull values out of a single document. This is largely a solved problem with modern Large Language Models (LLMs) and is not where the difficulty lives.
2. **Unification.** Turn *many* documents that disagree with each other (different layouts, different field names, missing fields, conflicting types) into *one* coherent schema you can query across. Nobody hands you the schema in advance. This is the hard part.
3. **Trust.** Structured data that a person cannot verify is worse than no data, because it looks authoritative. Every extracted value must be traceable to where it came from and how confident the system is, and the person must be able to correct it cheaply.

We are deliberately choosing to go deep on problems 2 and 3, and to make the frontend the place where that depth is visible and usable. Extraction quality matters, but it is table stakes.

### 1.3 The hard sub-problem we are owning

**Schema inference and evolution across heterogeneous documents, surfaced through a review loop the user can trust.**

A naive approach fails as follows: you ask the model to "extract the fields" from document 1 and get `vendor_name`; document 2 yields `supplier`; document 3 has `Vendor` with a trailing tax ID; document 4 has no vendor at all because it is a bank statement. Now you have four incompatible shapes and no way to answer "total spend by vendor." The interesting work is:

- proposing a unified schema from the first few documents,
- detecting when a new document does not fit (schema drift),
- letting the user decide whether to extend the schema, map the field to an existing one, or reject it,
- and re-extracting affected documents without losing prior corrections.

### 1.4 Who this is for

**Primary persona: a finance operations person at a small or mid-sized company** (chosen because Zamp is a finance company and this makes the demo legible to the judges). They receive vendor invoices, receipts, purchase orders, and bank statements as PDFs, scans, spreadsheets, and forwarded emails. They currently retype values into a spreadsheet and cannot answer cross-document questions without hours of manual work.

Their jobs to be done:

- "Turn this pile of documents into a table I can filter and sort."
- "Tell me which values you are unsure about so I only check those."
- "Answer a question across all of them, like total spend per vendor last quarter."
- "When a new kind of document shows up, do not silently break my table."

**The system must remain domain-agnostic.** Finance documents are the demo corpus and default examples, not a hard-coded assumption. A user should be able to upload research papers or property listings and get the same experience.

### 1.5 What we are deliberately leaving out (and why)

| Cut | Reason |
| --- | --- |
| Authentication and multi-user accounts | Adds a day of work and demonstrates nothing about the problem. Each browser gets an anonymous workspace token stored locally; the shareable URL includes it. |
| Real-time multi-user collaboration | Orthogonal to the problem. |
| Handwriting recognition | Optical Character Recognition (OCR) of typed scans is in scope via the parsing library; handwriting is a separate research problem. |
| Fine-tuning or custom models | Five days. We use a hosted LLM with structured output. |
| Email inbox integration | Nice input source, but the core loop works with manual upload. `.eml` upload is a stretch goal. |
| Export to accounting systems | Export to CSV and JSON is enough to prove the data is portable. |
| A general-purpose SQL editor | Natural-language querying is the product. Showing the generated SQL is in scope; letting users hand-write SQL is not. |

---

## 2. Product principles (frontend)

1. **Show your work.** Every number on screen can be traced to a highlighted region of a source document in one click. No exceptions.
2. **Uncertainty is a first-class UI state.** Low-confidence values look different from high-confidence ones before the user asks. The review queue is sorted by how much a correction would matter.
3. **The schema is the user's, not the model's.** The model proposes; the user disposes. Schema changes are explicit, previewed, and reversible.
4. **Never lose a human correction.** Re-extraction, schema changes, and re-uploads must preserve values a person has confirmed or edited.
5. **The empty state teaches.** A first-time visitor should understand the product in 30 seconds without reading documentation, and should be able to try it with sample documents in one click.
6. **Degrade, don't die.** A failed document, a timed-out model call, or an unparseable page produces a specific, actionable message and leaves the rest of the collection usable.

---

## 3. User journeys

### 3.1 First run

1. User lands on the deployed URL. They see a one-sentence explanation, a drop zone, and a "Try with sample invoices" button.
2. Clicking the sample button creates a workspace, loads 6 to 8 deliberately heterogeneous sample documents, and starts extraction. The user watches the table build itself.
3. Within a minute they see a populated table, a schema panel, a review queue with a handful of flagged cells, and a query box with three suggested questions.

### 3.2 Upload and extraction

1. User drops files (PDF, PNG, JPG, DOCX, XLSX, CSV, TXT). Unsupported types are rejected inline with the list of supported ones.
2. Each file appears as a row in a progress list with stages: Uploaded, Parsed, Extracting, Done, or Failed (with a reason).
3. Extraction results stream into the table row by row as they complete. The user can start reviewing document 1 while document 8 is still processing.
4. If the workspace has no schema yet, the system proposes one from the first batch and shows it in the schema panel before filling the table.

### 3.3 Reviewing and correcting

1. Cells are visually tiered by confidence. The review queue lists low-confidence and conflicting cells, highest impact first.
2. Clicking any cell opens the source document on the right with the exact region highlighted and the model's reasoning for that value.
3. The user can accept, edit, or mark a value as "not present." Edits are recorded as human-verified and are immune to re-extraction.
4. Keyboard flow: arrow keys move between review items, Enter accepts, E edits, N marks not present.

### 3.4 Schema drift

1. A new document arrives whose extracted fields do not fit the current schema (new field, incompatible type, or a field that looks like a rename of an existing one).
2. Instead of silently adding a column or dropping data, the system shows a **schema proposal** card: "This document has `Supplier` which looks like your `vendor_name` (92% match). Map it, add as new field, or ignore?"
3. The user decides. If they add a field, the system offers to backfill it across existing documents. If they map it, the value lands in the existing column.
4. Every schema change is versioned and visible in a history view with a one-click revert.

### 3.5 Querying

1. The user types a question in natural language: "Which invoices over 10,000 have no purchase order number?"
2. The system shows the generated SQL (collapsible), runs it, and renders the result in the shape that best fits the answer: a table, a single number with context, a bar chart, or a short list. The **shape is chosen by the agent and rendered via A2UI** (see section 6).
3. Every result cell that came from an extracted value keeps its provenance link.
4. If the question cannot be answered from the schema, the response says which field is missing and offers to add it.

### 3.6 Things going wrong

| Situation | Required behavior |
| --- | --- |
| A PDF is password protected or corrupt | Row shows "Could not read this file: it appears to be password protected." Other files continue. |
| A scanned page has no extractable text | Row shows "Scanned image detected, running OCR," then proceeds or fails with a clear message. |
| The model call times out or is rate limited | Row shows "Extraction is taking longer than usual, retrying (2 of 3)." After final failure: a Retry button. |
| The generated query is invalid or returns nothing | Message explains what was tried and suggests a rephrasing. Never a raw database error. |
| Backend is unreachable | Global banner, cached table stays visible and read-only. |
| A2UI payload is malformed or uses an unknown component | Fallback renderer shows the raw result as a table. The user never sees a blank area. |

---

## 4. Functional requirements

Priority uses MoSCoW: **M**ust, **S**hould, **C**ould, **W**on't (this round).

### 4.1 Workspace and ingestion

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-01 | Create an anonymous workspace on first visit; the workspace token is stored in the browser and encoded in a shareable URL. | M |
| FR-02 | Drag-and-drop and file-picker upload of multiple files at once; supported types: PDF, PNG, JPG, JPEG, DOCX, XLSX, CSV, TXT. | M |
| FR-03 | Reject unsupported types and files over 20 MB inline, before upload begins. | M |
| FR-04 | Per-file processing status with stages and failure reasons, streamed live without page refresh. | M |
| FR-05 | "Try with sample documents" loads a curated heterogeneous set in one click. | M |
| FR-06 | Upload `.eml` files and extract attachments. | C |

### 4.2 Schema

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-10 | When a workspace has no schema, propose one from the first batch, showing field name, type, description, example values, and coverage (how many documents have it). | M |
| FR-11 | User can accept, rename, retype, remove, or add fields before the proposal is applied. | M |
| FR-12 | Supported field types: string, number, currency (amount plus ISO 4217 code), date, boolean, enum, and list of strings. | M |
| FR-13 | Detect schema drift on new documents and present a proposal card with three actions per field: map to existing, add as new, ignore. | M |
| FR-14 | Adding a field offers backfill across existing documents; backfill runs in the background and streams results. | S |
| FR-15 | Schema history with version list and one-click revert. | S |
| FR-16 | Manually merge two fields into one. | C |

### 4.3 Data table

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-20 | Virtualized table (smooth at 5,000 rows) with sort, per-column filter, column show/hide and reorder, and resizable columns. | M |
| FR-21 | Cells render by type (currency formatted with code, dates localized, booleans as marks, lists as chips). | M |
| FR-22 | Cells show confidence tier (high, medium, low, conflict, human-verified) through a consistent visual treatment that does not rely on color alone. | M |
| FR-23 | Inline cell editing with type validation; edits are marked human-verified. | M |
| FR-24 | Export current view (respecting filters) to CSV and JSON. | S |
| FR-25 | Bulk accept all high-confidence values in a column. | C |

### 4.4 Provenance and review

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-30 | Clicking a cell opens the source document viewer at the correct page with the source region highlighted. | M |
| FR-31 | The viewer shows the model's short reasoning and the raw text span for that value. | M |
| FR-32 | A review queue lists cells needing attention, ordered by impact (low confidence on high-value fields first, then conflicts). | M |
| FR-33 | Keyboard-driven review flow (navigate, accept, edit, mark not present). | S |
| FR-34 | Re-extraction never overwrites a human-verified value; it may add a "model now disagrees" flag. | M |
| FR-35 | Show document-level provenance for non-PDF sources (a highlighted cell range for spreadsheets, a highlighted paragraph for DOCX and TXT). | S |

### 4.5 Query

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-40 | Natural-language question input with three suggested questions generated from the current schema. | M |
| FR-41 | Show the generated SQL in a collapsible panel; SQL is read-only (SELECT only) and scoped to the workspace. | M |
| FR-42 | Results are rendered from an agent-generated A2UI surface using a project-defined catalog (table, metric, bar chart, list, message). | M |
| FR-43 | Result rows keep provenance links back to source documents. | S |
| FR-44 | Query history within the session, re-runnable. | S |
| FR-45 | Follow-up questions that refine the previous result ("now only Q2"). | C |
| FR-46 | Full-text search across raw document text as a fallback when structured fields do not answer the question. | C |

---

## 5. Non-functional requirements

| Area | Requirement |
| --- | --- |
| Performance | First contentful paint under 1.5 s on a mid-range laptop. Table interactions under 16 ms per frame at 5,000 rows. Streaming updates apply without full re-render. |
| Accessibility | WCAG 2.1 AA target: full keyboard navigation, visible focus, ARIA labels on custom controls, confidence never conveyed by color alone, minimum 4.5:1 contrast. |
| Resilience | All network calls have timeouts and typed error states. Streaming reconnects with backoff and resumes from the last event ID. No unhandled promise rejections reach the console in normal use. |
| Observability | Frontend logs structured events (upload started, extraction completed, correction made, query run, A2UI fallback triggered) to the console in development and to a lightweight endpoint in production. Every request carries a correlation ID shown in error toasts so a bug report can be traced. |
| Security | Agent-generated UI is treated as untrusted input: only catalog components render, no raw HTML or scripts, string properties are sanitized. Generated SQL runs as a read-only database role. Uploaded files are validated by content type, not extension. |
| Browser support | Latest two versions of Chrome, Firefox, Safari, Edge. Desktop first; tablet usable; phone read-only. |
| Setup | `docker compose up` runs everything locally with one environment variable (the LLM API key). A `make dev` path runs frontend and backend with hot reload. |

---

## 6. A2UI requirements

### 6.1 What A2UI is and why we use it

A2UI (Agent-to-User Interface) is an open protocol from Google in which an agent emits declarative JSON describing *what* UI it wants (a column containing a text and a table bound to a data path), and the client renders it using its own trusted component catalog. The agent never sends HTML or code. We use it for the **query results surface** and the **schema proposal card**, because in both cases the right presentation depends on the content, and we want the agent to make that call without the frontend hard-coding every shape.

This is the "wow" moment for judges: ask a question, and the interface decides whether you need a number, a chart, or a table, with the frontend remaining fully in control of look, safety, and interactivity.

### 6.2 Requirements

| ID | Requirement | Priority |
| --- | --- | --- |
| A2-01 | Use the official `@a2ui/react` renderer with the v0.9 protocol (`@a2ui/react/v0_9` and `@a2ui/web_core/v0_9`), pinned to exact versions verified to work at build time. | M |
| A2-02 | Define a project catalog of custom components with Zod schemas: `ResultTable`, `Metric`, `BarChart`, `ProvenanceCell`, `SchemaProposal`, `FieldMapping`, plus the basic catalog for layout and text. | M |
| A2-03 | The backend streams A2UI messages (`createSurface`, `updateComponents`, `updateDataModel`) over Server-Sent Events (SSE), so results render progressively. | M |
| A2-04 | User actions inside A2UI surfaces (accept a mapping, drill into a row) round-trip to the backend through the protocol's action mechanism and update the surface. | M |
| A2-05 | Every A2UI surface is wrapped in an error boundary with a deterministic fallback renderer that shows the underlying result as a plain table. Fallback triggers are logged. | M |
| A2-06 | Agent-provided strings are treated as untrusted: no HTML injection, length caps, component count caps per surface. | M |
| A2-07 | A developer-only "Inspect surface" toggle shows the raw A2UI JSON stream for the current surface, useful for the demo and for debugging. | S |

### 6.3 Known risks with A2UI (as of September 2026)

- The React renderer is at 0.11.0 and has shipped breaking changes in minor versions (0.9.1, 0.10.0, 0.11.0). Mitigation: pin exact versions; keep the catalog small; run renderer smoke tests in CI.
- Peer dependency on React 19.2 and Zod 3.x. Zod 4 is current on npm and will not satisfy the peer range. Mitigation: pin `zod@3.25.x` project-wide.
- There is no official Python SDK for emitting A2UI. Mitigation: the backend emits plain JSON validated against the spec's JSON Schema; this is a small, well-defined surface.
- The protocol is still evolving (v1.0 is a release candidate). Mitigation: isolate all A2UI code behind one module so the rest of the app does not depend on protocol details.

---

## 7. Frontend to backend contract (summary)

Detailed in the implementation document. The frontend needs:

- `POST /workspaces` to create; `GET /workspaces/{id}` for schema, documents, and row data.
- `POST /workspaces/{id}/documents` multipart upload; `GET /workspaces/{id}/events` SSE stream for processing status, extraction results, and schema proposals.
- `PATCH /workspaces/{id}/schema` to apply proposals and edits; `GET .../schema/versions`; `POST .../schema/revert`.
- `PATCH /workspaces/{id}/records/{recordId}/fields/{field}` to correct a value.
- `GET /workspaces/{id}/documents/{docId}/file` to stream the original for the viewer; provenance regions come with each field value.
- `POST /workspaces/{id}/query` returning an SSE stream of A2UI messages plus the generated SQL.
- `POST /workspaces/{id}/actions` for A2UI action round-trips.

---

## 8. Acceptance criteria (demo script)

The submission is acceptable when a judge can, without help:

1. Open the URL, click "Try with sample documents," and see a populated table within 60 seconds.
2. Click a low-confidence cell and see the exact region in the source PDF highlighted, with reasoning.
3. Edit that cell, then re-run extraction on the document and confirm the edit survives.
4. Upload a new document of a different type and see a schema proposal card rather than a broken table; map one field and add another; watch backfill fill the new column.
5. Ask "total amount by vendor" and get a bar chart; ask "how many invoices are missing a PO number" and get a single metric; ask something unanswerable and get a helpful explanation.
6. Toggle "Inspect surface" and see the A2UI JSON that produced the chart.
7. Disconnect the network mid-upload and see a graceful, specific message; reconnect and see processing resume.
8. Run `docker compose up` locally and reach the same experience.

---

## 9. Mapping to the evaluation criteria

| Criterion | Where it shows up |
| --- | --- |
| Problem framing | Section 1: three-problem decomposition, explicit hard sub-problem, explicit cuts. |
| Product thinking | Finance ops persona with named jobs to be done; domain-agnostic core. |
| UX decisions | Confidence tiers, provenance-first cells, proposal cards instead of silent schema changes, keyboard review flow, empty state with samples. |
| Code quality | Single A2UI module boundary, typed API client generated from the backend schema, feature-folder structure (implementation doc). |
| Tests | Schema unification logic, provenance highlighting math, A2UI fallback, SSE reconnection, end-to-end demo script as a Playwright test. |
| Documentation | This document, the implementation document, `decisions.md`, and a README with a one-command setup. |
| Setup experience | `docker compose up` with one environment variable; sample data bundled. |
| Velocity | Five-day plan in the implementation document, with a shippable slice at end of day 2. |
| Above and beyond | Schema drift handling with backfill that preserves human corrections; agent-chosen result presentation through A2UI with a safe fallback. |

---

## 10. Open questions to resolve in `decisions.md`

- Which LLM provider and model for extraction versus query generation? (Cost, structured-output reliability, latency.)
- Postgres JSONB rows versus one physical table per workspace schema. (Query flexibility versus schema-change cost.)
- Whether to store document images for the viewer or re-render from the PDF on demand.
- Confidence: model self-report, agreement between two extraction passes, or both?
- Whether follow-up query refinement (FR-45) is worth a day, or whether query history is enough.
