# Distill

Drop in a pile of messy documents. Distill reads them, pulls out the values that matter, and
gives you one table you can search, question in plain language, and trace back to the exact
region of the page each value came from.

Three screens, nothing else: **Upload**, **Chat**, **Data**.

This file covers running it on your own machine. The reasoning behind every choice lives in
[`decisions.md`](decisions.md); the specification lives in [`docs/requirements.md`](docs/requirements.md)
and [`docs/implementation.md`](docs/implementation.md).

---

## What you need

Everything below was verified on macOS (Apple silicon) on September 5, 2026, with the
versions this project is developed against.

| Tool | Version used | Why |
| --- | --- | --- |
| PostgreSQL | 16.15 | The only external service. No Docker anywhere in this setup. |
| Python | 3.12 (pinned in `server/.python-version`) | Backend. |
| [uv](https://docs.astral.sh/uv/) | 0.12.9 | Installs Python dependencies and runs commands. |
| Node.js | 22.16.0 | Frontend. |
| npm | 10.9.2 | Frontend. |
| Tesseract | any recent | Optical Character Recognition, for pages with no text layer. Optional; see below. |

On macOS with Homebrew:

```bash
brew install postgresql@16 uv node tesseract && brew services start postgresql@16
```

Tesseract is only needed for scanned documents. Without it, set `OCR_ENABLED=false` in
`server/.env` and a scanned page fails with a clear message instead of being silently
mis-parsed. Every other format works without it.

---

## First-time setup

Four steps. Run them from the repository root.

### 1. Create the database role and the two databases

```bash
psql -d postgres -f server/scripts/bootstrap_db.sql && createdb -O distill distill && createdb -O distill distill_test
```

That creates the `distill` login role (password `distill`, matching the default connection
string), the application database, and the database the test suite uses.

The script also creates a `distill_readonly` role. It is a leftover: it existed to confine
generated Structured Query Language (SQL) under v1's SQL guard, and v2 generates none
(decision D24). Nothing connects as it, and
`server/scripts/bootstrap_db_per_database.sql` exists only to grant privileges to it, so you
can skip that script entirely.

### 2. Configure the server

```bash
cp server/.env.example server/.env
```

The defaults work as they are. The only variable that changes behavior is `LLM_PROVIDER`:

- **`fake`** (the default) runs the entire pipeline against recorded fixtures, with no
  network and no key. A fresh checkout works immediately. This is a supported way to run the
  product, not a degraded one (decision D11).
- **`gemini`** makes real model calls. Set `GEMINI_API_KEY` as well, or the server refuses to
  start rather than quietly falling back.

### 3. Install dependencies and run migrations

```bash
cd server && uv sync && uv run alembic upgrade head && cd ../client && npm ci && cd ..
```

### 4. Check it worked

```bash
cd server && uv run pytest -q && cd ../client && npm test && cd ..
```

Expect 483 server tests and 100 client tests, all passing, in well under a minute. The server
suite needs the `distill_test` database from step 1; it runs `alembic upgrade head` against
it itself.

---

## Running it

Two processes, two terminals.

There is a `Makefile` for all of this: `make setup` once, then `make api` and `make web` in
two terminals. `make help` lists the rest. The commands below are what those targets run.

**Terminal 1, the backend:**

```bash
cd server && uv run uvicorn app.main:app --port 8000 --workers 1
```

Port 8000 is not arbitrary: the frontend proxies `/api` and `/healthz` there, so the browser
talks to a single origin in development exactly as it does in production.

`--workers 1` is not arbitrary either. Document processing runs on an in-process asyncio
queue (decision D8), and while every event is persisted so a reconnecting client can replay
it, *live* delivery goes through an in-process bus (decision D12). A second worker would give
you two independent queues, and a browser connected to one process would never see the live
events published by the other. The streaming chat answer buffer is in-process for the same
reason. Avoid `--reload` while a document is processing, since a reload mid-run restarts the
queue.

**Terminal 2, the frontend:**

```bash
cd client && npm run dev
```

Open **http://localhost:5173**. If that port is taken, Vite picks the next free one and
prints the actual address; the proxy works on any port.

**Confirm the two halves are talking:**

```bash
curl -s localhost:8000/healthz
```

```json
{
  "status": "ok",
  "database": { "ok": true },
  "storage": { "ok": true, "detail": "var/storage" },
  "llm": {
    "ok": true,
    "detail": "provider=gemini extract=gemini-3.5-flash fast=gemini-3.5-flash-lite embed=gemini-embedding-001@768"
  }
}
```

`status: ok` needs the database and the storage directory; the `llm` line reports what is
configured and never the key. With `LLM_PROVIDER=fake` it says so plainly, which is a healthy
state, not a warning.

---

## Using it

1. **Upload.** Click **"Try with sample documents"** to load the bundled corpus, or drag
   your own files on. PDF, DOCX, XLSX, CSV, images, and plain text. Up to 20 MB per file and
   25 files at once, and the limit is enforced by counting bytes as they stream rather than
   by trusting the declared size. Come back to this screen at any time and it lists
   everything in the workspace: what each file was parsed as, its stage or failure reason,
   and buttons to open or delete it.
2. **Watch the progress screen.** Each document moves through parsing, extraction, grounding,
   and indexing. A value appears in the table and becomes askable at the same moment.
3. **Chat.** Ask in plain language. The answer streams, cites the passages it used, and may
   open with a chart or a metric. Every figure in that visual is computed by the server from
   a query the model specified, never typed by the model (decision D26).
4. **Data.** One unified table across every document, plus a dashboard the agent assembles
   from the fields it found. Click any cell to open the source document with the value
   highlighted on the page. Edit a cell to correct it; a human correction is never overwritten
   by a later re-extraction.

There are no accounts. Creating a workspace mints a token once, which the frontend keeps in
`localStorage` and encodes in a shareable link fragment. That token is the only credential, so
**anyone with the link has full access** to that workspace, and only its hash is stored server
side (decision D7). Lose it and the workspace is unreachable: there is no recovery, by design.

---

## The sample documents

`samples/` holds ten documents that the "Try with sample documents" button loads in one
click. They are generated, not real, and every organisation and figure in them is invented.

| File | Kind | Format | What it is there for |
| --- | --- | --- | --- |
| `acme-invoice-INV-2041.pdf` | invoice | PDF | Baseline. Says "Vendor", "Total due", has a purchase order. |
| `acme-invoice-INV-2098.pdf` | invoice | PDF | Same vendor again, so "total by vendor" has to group. |
| `globex-invoice-GX-7781.docx` | invoice | Word | Says "Seller", "Invoice No", "Amount due". No purchase order. |
| `initech-invoice-INT-5567.xlsx` | invoice | Spreadsheet | A third vocabulary: "Vendor name", "Document number", "Amount now due". |
| `umbrella-invoice-UL-0442.txt` | invoice | Plain text | No layout to lean on. No purchase order. |
| `hooli-receipt-R-2291.png` | receipt | Image | A scan, so Optical Character Recognition runs. No purchase order. |
| `acme-services-agreement.pdf` | contract | PDF, 2 pages | Prose. Answers "what does the contract say about payment terms". |
| `northwind-expense-policy.docx` | policy | Word | Prose that is not about invoices at all. |
| `seaboard-statement-march-2026.pdf` | bank statement | PDF | Different fields entirely: account number, closing balance, no vendor. |
| `supplier-directory.csv` | reference table | CSV | Tabular reference data, deliberately with no amounts. |

The set is **deliberately inconsistent**: the invoice total is written five different ways,
the sending party four, and dates in five formats. That is the point of it. `expected.json`
records the ground truth, including that the invoices total 16,752.90 USD across five
vendors and that three of them carry no purchase order, so you can check the table against a
stated answer rather than against whether it looks plausible.

To change the corpus, edit `server/scripts/generate_samples.py` and run it:

```bash
cd server && uv run python scripts/generate_samples.py
```

It asserts its own arithmetic before writing anything, so a document whose line items do not
add up fails the run instead of shipping.

### A demo that takes two minutes

1. Click **"Try with sample documents"** and watch the ten process (about 45 seconds).
2. Ask **"What is the total amount by vendor?"** A bar chart arrives before the prose. The
   figures are computed by the server, not written by the model.
3. Ask **"How many invoices are missing a purchase order number?"** The answer is 3.
4. Ask **"What does the contract say about payment terms?"** and click a citation to see the
   clause highlighted on page 1 of the agreement.
5. Ask something the documents cannot answer, such as **"Who is our largest supplier by
   headcount?"**, and get an explicit refusal rather than a guess.
6. Open **Data** and check any cell against `samples/expected.json`.

---

## Model configuration

Relevant only with `LLM_PROVIDER=gemini`. Every model identifier below was verified callable
on September 5, 2026 (decision D42).

| Variable | Default | What it does |
| --- | --- | --- |
| `LLM_EXTRACT_MODEL` | `gemini-3.5-flash-lite` | Extraction and schema inference, once per document in the background. |
| `LLM_FAST_MODEL` | `gemini-3.5-flash-lite` | Chat, dashboard planning, suggestions. Everything you wait on. |
| `LLM_FAST_THINKING_LEVEL` | `low` | Reasoning effort for that fast path only. Leave blank for a Gemini 2.x model, which has no such setting. |
| `LLM_EMBED_MODEL` | `gemini-embedding-001` | Retrieval and schema matching. |
| `LLM_EMBED_DIMENSIONS` | `768` | Vector width. Changing it changes the vector space, so re-index afterwards. |

Three things worth knowing before a demo:

- **Gemini 2.5 is closed to new keys.** `gemini-2.5-pro` and `gemini-2.5-flash` return 404 to a
  key issued recently, even though they still appear in the model list. The Pro tier is not on
  the free plan at all: it answers 429 with `limit: 0`, which is permanent and reads exactly
  like an ordinary rate limit.
- **Free-tier daily caps are per model, and they are small.** Every non-lite model this key
  can reach allows **20 requests per day**, which one pass over the ten sample documents
  spends. That is why both tiers are Lite. With a paid key, point `LLM_EXTRACT_MODEL` at a
  Pro model.
- **Latency comes from the reasoning effort, not the model size.** Flash Lite starts a chat
  answer in under a second where the larger Flash model takes about nine, which is why the tier
  you wait on is Lite.

---

## Checks

Run from the directory named.

| Command | Directory | What it does |
| --- | --- | --- |
| `uv run pytest -q` | `server` | 483 tests. No network, no key: the fake provider replays recorded fixtures. |
| `uv run ruff check app tests` | `server` | Lint. |
| `uv run mypy app` | `server` | Types. Reports 14 known pre-existing errors, mostly at the boundary with untyped parsing libraries. |
| `npm test` | `client` | 100 tests, Vitest with jsdom. |
| `npm run typecheck` | `client` | TypeScript. |
| `npm run lint` | `client` | oxlint. One known warning in `usePageImage.ts`. |

---

## When something goes wrong

**`LLM_PROVIDER is 'gemini' but GEMINI_API_KEY is not set`** at startup. Deliberate: a server
that boots with a mistyped key would serve offline heuristics dressed as real extraction.
Either supply the key or set `LLM_PROVIDER=fake`.

**`connection refused` on the database.** Postgres is not running:
`brew services start postgresql@16`. If it is running, check that step 1 created the role, and
that `DATABASE_URL` in `server/.env` matches it.

**HTTP 401 on every request after the first screen.** The workspace token is missing or belongs
to a different workspace. A wrong token and a nonexistent workspace return the same 401 on
purpose, so neither can be probed for. Start a new workspace from the upload screen.

**"We are being rate limited by the model provider."** A free-tier cap. The adapter obeys the
delay the provider asks for, so a document may simply take longer. If it says the model is
*not included in this plan*, retrying will never help: change `LLM_EXTRACT_MODEL` or
`LLM_FAST_MODEL` to a model the key covers.

**A scanned document fails.** Tesseract is missing or not on the process `PATH`. Install it, or
set `TESSERACT_CMD` to its full path, or set `OCR_ENABLED=false` to fail those pages loudly.

**Chat answers "not in these documents" about something clearly in them.** The workspace was
indexed in a different embedding space from the current settings, and the server logs
`search.space_mismatch` saying so. Restore the previous `LLM_EMBED_*` values, or re-upload the
documents to re-index them.

**The frontend loads but every call fails.** The backend is not on port 8000, which is what
`client/vite.config.ts` proxies to.

---

## How it fits together

```
client/  React 19, TypeScript, Vite          feature folders: upload, processing, chat,
   |     relative API base + /api proxy       data, viewer, a2ui
server/  FastAPI, one process
   |     pipeline/    parse -> extract -> ground -> score -> index
   |     llm/         provider protocol: gemini | fake, plus the schema converter
   |     retrieval/   chunking, embedding, cosine search in process
   |     insights/    query specifications evaluated in Python, never by the model
   |     a2ui/        Agent-to-User Interface surfaces the agent composes
PostgreSQL  documents, pages, records, field values, chunks, chat messages, events
var/storage originals and rendered page images
```

Two properties are worth stating because they shape everything else. **Every value on screen
traces to a highlighted region of its source document**, so table cells and chat citations open
the same viewer. **Every number displayed is computed by the server**: the agent emits a query
specification, the server evaluates it, and the result is bound into the interface by path.

---

## Known gaps

Stated rather than hidden, in the spirit of `decisions.md`.

- **No CSV export** from the Data screen.
- **The image has never been built.** There is no container runtime in this environment, so
  the `Dockerfile` is written and unbuilt: the first build will happen on the platform.
  `make preflight` checks the five things that can be checked without one. See
  `docs/deployment.md`.
