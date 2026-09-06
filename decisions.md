# Distill: Decision Log

Every technology chosen and every design decision made on this project is recorded here, in
the format the brief asks for: **decision**, **alternatives considered**, **reasoning**, and
**what was cut** or the accepted tradeoff.

Rules for this file:

- A decision that is not written here did not happen. Write the entry in the same change as
  the code that depends on it, never at the end of the project.
- Every decision that stands in the product is here. Where one narrows or extends another,
  both entries stay and the status lines say which part of which.
- Every entry is dated. Where a decision could not be verified, the gap is stated rather
  than hidden.

Legend: **Active** the decision stands. **Re-affirmed** it was challenged and held.
**Partly superseded** part of it was narrowed by a later entry, which the status line names.

---

## D1. Frame the problem as unification and trust, not extraction

**Date:** September 2, 2026 · **Status:** Active in its frame, narrowed September 4, 2026 by
D23. The trust half stands in full; the unification-with-a-review-loop half is withdrawn.

**Decision.** Treat single-document extraction as table stakes and go deep on two harder
problems: unifying many mutually disagreeing documents into one queryable schema, and making
every extracted value verifiable by a human.

**Alternatives considered.** A single-document extractor with a polished viewer. A
general-purpose chat-over-documents product.

**Reasoning.** Extraction from one document is close to solved with a modern Large Language
Model, so a submission that stops there demonstrates tool use rather than judgement. The
cross-document schema problem is where naive approaches actually break, and it is where a
finance operations person actually loses hours. Structured data a person cannot verify is
worse than no data, because it carries unearned authority.

**Cut.** Per-document question-and-answer chat.

---

## D2. Python 3.12 with FastAPI for the backend

**Date:** September 2, 2026 · **Status:** Re-affirmed September 3, 2026

**Decision.** Python 3.12 and FastAPI.

**Alternatives considered.** Node with TypeScript, for shared types with the frontend. Go,
for the application programming interface layer.

**Reasoning.** Document parsing with word-level geometry, Optical Character Recognition, and
DOCX and XLSX handling are noticeably more mature in Python. Structured-output tooling for
Large Language Models is more mature there too. Go is strong for the interface layer and
weak for both parsing and model tooling, which is the wrong trade for a five day build.

**Re-affirmation, September 3, 2026.** The choice was challenged on three grounds worth
recording, because two of them are real costs this project now carries.

1. _Nothing in the chosen stack was installed on the development machine._ Python was system
   3.9.6 only, with no Postgres, no Tesseract, and no `uv`. Resolved by installing Python
   3.12.14, Postgres 16.15, Tesseract 5.5.3, and `uv` 0.12.9 through Homebrew. Cost about
   twenty minutes, so this objection did not survive contact with the facts.
2. _A Node backend would let one Zod schema per Agent-to-User Interface catalog component
   serve both sides._ This is a genuine loss. The backend now validates emitted messages
   against the protocol's JSON Schema while the client validates with Zod, so requirements
   A2-02 and A2-06 are enforced twice from two sources of truth. **Accepted, and mitigated**
   by generating the backend's component contracts from a single declarative table in
   `app/a2ui/catalog.py` and asserting message validity in tests, so a divergence fails the
   build rather than the demo.
3. _A Node backend extracting geometry with pdf.js would share a coordinate space with the
   pdf.js-based viewer by construction._ Also a genuine loss, and the sharper of the two.
   The provenance overlay now depends on pdfplumber and pdf.js agreeing about the coordinate
   origin, which is an assumption rather than an identity. **Accepted, and mitigated** by
   promoting it to the first checkpoint in the build: an executable test asserts the
   coordinate convention against a real PDF fixture before any overlay mathematics is
   written.

**Cut.** A shared type package between frontend and backend, replaced by a typed client
generated from the OpenAPI document that FastAPI produces.

---

## D3. pdfplumber and Tesseract, not Docling

**Date:** September 2, 2026 · **Status:** Active

**Decision.** pdfplumber for word-level geometry, pypdfium2 for page rendering, Tesseract
for pages with no text layer.

**Alternatives considered.** Docling, which offers stronger layout understanding.

**Reasoning.** Provenance needs word bounding boxes, which pdfplumber gives directly.
Docling's dependency footprint runs to multiple gigabytes of models, which breaks both the
one-command setup promise and deployment on a free tier.

**Cut.** Layout-aware table extraction from complex multi-column PDFs.

---

## D4. Postgres JSONB field values with a per-workspace typed view

**Date:** September 2, 2026 · **Status:** Partly superseded September 4, 2026 by D24. The
tall `field_values` table stands; the per-workspace SQL view is cut with the SQL query path.

**Decision.** One `field_values` row per record and field pair, with the value stored as
JSONB, plus a per-workspace SQL view that pivots those rows into typed columns. Generated
queries target the view and never the base tables.

**Alternatives considered.** One physical table per workspace with real typed columns.

**Reasoning.** Schema changes stay cheap, because a schema change regenerates a view instead
of running a migration. Provenance, confidence, and human-verified status become first-class
per-value columns, which makes "never overwrite a human correction" a single `WHERE` clause
rather than an application-level convention. The model still sees a flat typed table.

**Accepted tradeoff.** View regeneration on every schema version change, and query
performance that is fine at this project's scale but would not be at a much larger one.

---

## D5. Confidence tiers are derived, never taken from the model

**Date:** September 2, 2026 · **Status:** Active

**Decision.** The tier is computed from whether the value could be grounded in the source
document, the model's self-reported confidence, and whether type validation or coercion was
needed. The model is never asked for a tier directly.

**Alternatives considered.** Trusting the model's self-reported confidence. Running two full
extraction passes on every document and scoring agreement.

**Reasoning.** Whether a quoted piece of evidence can actually be located in the document is
a far stronger signal than a number the model produced about itself, and it is the mechanism
that catches hallucinated values: a hallucinated value has no quote to ground.

**Cut.** A second full extraction pass by default, on cost and latency grounds. It is
available instead as a per-document "double-check" action.

---

## D6. Server-Sent Events, not WebSockets

**Date:** September 2, 2026 · **Status:** Active

**Decision.** Server-Sent Events for all streaming.

**Reasoning.** The streaming is one-directional, which is all Server-Sent Events do.
Resumption after a dropped connection comes free through the `Last-Event-ID` header, and the
transport works through every proxy without upgrade negotiation.

**Cut.** Live cursors and multi-user presence.

---

## D7. Anonymous workspaces with a bearer token, no accounts

**Date:** September 2, 2026 · **Status:** Active

**Decision.** Each browser gets an anonymous workspace and a bearer token, stored locally and
encoded in a shareable link. No sign-up, no accounts.

**Reasoning.** Five day window, and authentication demonstrates nothing about this problem.

**Accepted risk.** Anyone with the link can see the workspace. Stated plainly in the
interface rather than left implicit.

---

## D8. In-process asyncio job queue, not Redis with a separate worker

**Date:** September 2, 2026 · **Status:** Active

**Decision.** An in-process asyncio queue for document processing.

**Reasoning.** A single instance over five days does not need a broker, and a broker adds a
service to the one-command setup.

**Accepted risk.** A deployment restart interrupts in-flight extractions. The per-document
status model makes them resumable on boot. Upgrade path to Redis with `arq` is documented.

**Consequence, added September 3, 2026.** The queue and the event bus are both in-process, so
the interface **must run with exactly one worker process**. Two workers would split the bus
and deliver each event to only the subscribers sharing a process. The worker count is pinned
to one in the Dockerfile, the compose file, and the Makefile, with a comment at each site,
and the health route reports the process identifier so a misconfiguration is visible.

---

## D9. styled-components with Radix Primitives, not Tailwind with shadcn/ui

**Date:** September 2, 2026 · **Status:** Active, frontend, not yet exercised

**Decision.** styled-components 6 over Radix Primitives.

**Alternatives considered.** Tailwind with shadcn/ui, which is the fastest route to a
finished component set. Linaria or Panda CSS, which give the same authoring interface with
no runtime cost.

**Reasoning.** Author fluency in a five day build outweighs shadcn/ui's head start. Radix
supplies the accessibility and behaviour that shadcn/ui would have supplied. This is a Vite
single-page application, so the React Server Components concern behind styled-components'
maintenance mode does not apply here.

**Accepted risks.** A library its own maintainer no longer recommends for new projects, and
the runtime cost of CSS-in-JS inside a table of five thousand rows. Mitigated by driving all
table cell variants from static components with data attributes rather than interpolated
properties, and by confining every styled definition to one module so a move to Linaria
stays mechanical.

**Reversal condition.** If the day-one component kit takes longer than a day, the fluency
assumption was wrong, and the correct response is to switch to Tailwind with shadcn/ui
before any feature code depends on the kit.

**Cut.** A prebuilt component library of any kind.

---

## D10. `uv` for Python dependency and interpreter management

**Date:** September 3, 2026 · **Status:** Active

**Decision.** `uv` 0.12.9 manages dependencies, the lock file, and the Python interpreter
version itself. `uv.lock` and `.python-version` are committed.

**Alternatives considered.** pip with a `requirements.txt`, which has no lock file and so no
reproducibility. Poetry, which locks but is slower and does not manage the interpreter.

**Reasoning.** The one-command setup promise in the requirements is only true if the exact
dependency set is reproducible. `uv` also installs and pins the interpreter, which removes
the failure this project already hit once: the development machine had only Python 3.9.6.
Resolution is fast enough that adding a dependency does not interrupt flow.

**Cut.** Nothing. This replaces a tool that was never chosen, since the implementation
document specified only that a `pyproject.toml` exists.

---

## D11. Gemini behind a provider protocol, with a fake provider as a first-class implementation

**Date:** September 3, 2026 · **Status:** Active

**Decision.** Gemini is the model provider, reached through an `LLMClient` protocol selected
by configuration, alongside a **fake provider** that is a first-class implementation rather
than a test double. Which Gemini models sit behind the protocol is D42's decision, not this
one, and that separation is the point of the protocol.

**Alternatives considered.** Calling a provider software development kit directly
throughout, which is simpler but welds the project to one vendor. Claude. A test double
built only for the suite, rather than a provider the product can genuinely run on.

**Reasoning.** Model identifiers and tiers are a moving target: D42 records what a real key
turned out to allow, and none of it reached above this line. That is what a protocol is for.

The fake provider is what makes a no-key checkout acceptable rather than reckless. The whole
pipeline is buildable and testable with no key and no network, and the same fake supplies the
recorded fixtures the deterministic end-to-end test runs against. It is not a stub returning
empty objects: it synthesises values from label-and-value heuristics over the real document
text, so the pipeline it exercises is the pipeline that ships.

**Cut.** Instructor as the structured-output layer, for the reasons in D16. Any automatic
fallback from the real provider to the fake one at run time: heuristic values wearing the
confidence tiers and provenance links of real extraction is the one failure this product
cannot afford, so a configured provider that cannot be constructed is a hard failure at
startup instead.

---

## D12. The Server-Sent Events log is a database table, not in-memory state

**Date:** September 3, 2026 · **Status:** Active

**Decision.** A `workspace_events` table stores every published event with a per-workspace
monotonic sequence number. Streaming reads live events from an in-process bus and replays
missed events from the table.

**Alternatives considered.** Keeping the event log in memory, which is what the
implementation document implied.

**Reasoning.** Section 5.1 requires that reconnecting clients resume from `Last-Event-ID`.
Resumption is not implementable without a replayable log, so the log has to outlive the
connection. Persisting it also turns the processing timeline into queryable history rather
than something that vanishes on refresh, which is what lets the progress list in the
interface be the honest event log the observability requirement asks for.

**Accepted tradeoff.** A database write per event. At this project's event volume the cost is
irrelevant, and the writes batch naturally within a document's processing transaction.

---

## D13. `field_values` retains the disagreeing model value beside the human one

**Date:** September 3, 2026 · **Status:** Active

**Decision.** `field_values` carries `model_value` and `model_value_at` in addition to
`value`. A human-verified value stays in `value`, and a later re-extraction that disagrees
records its result in `model_value` and sets the tier to conflict.

**Alternatives considered.** A single `value` column, per section 4 of the implementation
document, with the conflict recorded as a boolean flag.

**Reasoning.** Requirement FR-34 says re-extraction may add a "model now disagrees" flag. A
flag alone loses _what_ the model said, so the interface could tell the user a disagreement
exists but not show them the two candidates, which makes the flag unactionable. Keeping both
values is what turns a conflict from a warning into a decision the user can make.

**Cut.** Full version history of every value. Only the current human value and the most
recent disagreeing model value are retained, which is enough to resolve a conflict and far
cheaper than an audit table.

---

## D14. One provenance shape for every format, by rendering every format to a page

**Date:** September 3, 2026 · **Status:** Active

**Decision.** Every supported format is laid out onto page-shaped sheets that the backend
renders itself, so provenance is always a list of bounding boxes over a page image, in one
coordinate convention, for PDF, image, DOCX, XLSX, CSV, and plain text alike. A
human-readable locator such as `Invoices!row 2` or `paragraph 12` is carried alongside for
display.

**Alternatives considered.** The implementation document's plan: a different provenance unit
per format, a bounding box for PDFs and images, a paragraph index for DOCX, a cell range for
spreadsheets, a line span for text.

**Reasoning.** Four provenance shapes means four frontend rendering paths, four sets of
coordinate mathematics, and four ways to be subtly wrong, on the feature that carries the
product's central trust claim. Rendering the non-paginated formats ourselves means the
backend knows exactly where every word sits, because it put it there, so there is one
highlight implementation and one set of tests. It also satisfies requirement FR-35 more
directly than the original plan, since the user gets both a real highlight and the semantic
address rather than only the address.

The word boxes are verified against the pixels rather than asserted: the renderer's tests
crop the rendered image to each reported box and assert there is ink inside it, and none in
a region no word claims.

**Accepted tradeoff.** Non-paginated formats are shown in a layout Distill chose rather than
one the user recognises, so a DOCX does not look like it does in Word. For a review surface
whose job is to show where a value came from, that is an acceptable loss, and it is
strictly better than having nothing to highlight.

---

## D15. A flat extraction response shape, with every value sent as text

**Date:** September 3, 2026 · **Status:** Active

**Decision.** Every extraction call returns the same fixed, flat shape: a list of entries
each carrying a key, the value **as text**, a type guess, an evidence quote, a page number, a
confidence, and a short reasoning. The workspace schema is communicated in the prompt, not
in the response schema. Conversion from text into the stored representation is done by
`app/domain/values.py`.

**Alternatives considered.** The implementation document's plan: build the response model at
runtime with `pydantic.create_model`, one typed attribute per schema field.

**Reasoning.** Three things, in order of weight.

First, it removes review finding 8.7. Gemini accepts a narrower schema subset than pydantic
can emit, and a dynamically generated model is the most likely thing to wander outside it.
That risk could not be tested without an API key, which made it the worst kind of risk. A
fixed shape is verified once and stops being a risk.

Second, provenance is per value, and nesting it is where the generated approach becomes
awkward. Every value needs its own quote, page, confidence, and reasoning. With one
attribute per field, each attribute becomes an object carrying five more, which is exactly
the deep nesting the first reason warns about.

Third, sending the value as text plays to each side's strengths. The model finds the value
and says what kind of thing it is. Deterministic, already-tested code parses `$12,480.50`
into an amount and a currency code, and reports that `03/04/2026` was ambiguous. That report
is what feeds confidence tier derivation, so the split is not merely tidy, it is what makes
the trust story computable.

**Cut.** The response schema can no longer force a value for every field. Coverage is asked
for in the prompt and checked afterwards, which is a check worth having regardless, because
a model can return a structurally perfect object full of nulls.

---

## D16. Call google-genai directly, not through Instructor

**Date:** September 3, 2026 · **Status:** Active, supersedes the Instructor half of
implementation.md section 2.2

**Decision.** The Gemini client uses the `google-genai` software development kit directly,
with a hand-written retry loop, and Instructor has been removed from the dependency
manifest.

**Alternatives considered.** Instructor, per the implementation document, for retries on
malformed output and provider independence.

**Reasoning.** Instructor takes a pydantic model and converts it to a provider schema using
its own converter. That would bypass `app/llm/jsonschema.py`, which exists specifically
because Gemini accepts a narrow schema subset, and which is verified by tests that need no
API key. Delegating schema conversion would put the one risk that cannot be tested without
a key back into an untested path, in exchange for roughly forty lines of retry logic.

Instructor's other benefit, provider independence, is already supplied by the `LLMClient`
protocol, which is the boundary the rest of the application talks to. Swapping Gemini for
another provider is a new class in `app/llm/`, with or without Instructor.

Instructor was removed rather than left installed, because an unused dependency is a false
statement about what the project needs.

**Accepted tradeoff.** The retry loop, error classification, and token accounting are ours
to maintain. They are about ninety lines, they are unit tested through the fake provider,
and the retry feeds the specific validation error back into the prompt, which is more
targeted than simply asking again.

---

## D17. Single repository for client and server, not separate repos

**Date:** September 4, 2026 · **Status:** Active

**Decision.** `client/` and `server/` live as sibling directories in one repository, per the
layout in CLAUDE.md. There is no per-package repo split.

**Alternatives considered.** Two repositories, one per package, with the client pulling the
server's API contract via a published package or git submodule.

**Reasoning.** This is a take-home with a single author and a fixed review window. A
monorepo means one `git clone`, one README with a one-command setup, and one `decisions.md`
that covers both sides without cross-referencing a second repository. A reviewer should not
have to juggle two remotes to see the whole system.

Splitting repos only pays off with independent teams, independent release cadences, or CI
isolation across packages, none of which apply here. It would also fragment the required
`decisions.md` deliverable and the provenance/review-loop docs, which describe behavior that
spans both packages.

Deployment is not a reason to split. Every major host used for a project this size (Vercel,
Render, Railway, Fly) supports pointing a deploy at a subdirectory of a monorepo, so
`client/` and `server/` can still ship as independently deployed services with their own
build commands, start commands, and environment variables.

**Cut.** Separate repositories, and any tooling that exists only to keep multiple repos in
sync (git submodules, a published internal package for shared types).

## D18. Field similarity is string similarity OR embedding similarity, with a margin rule

**Date:** September 4, 2026 · **Status:** Active. Thresholds measured against a real model on
September 5, 2026.

**Decision.** Drift matching scores a candidate field against each existing field with two
independent signals, and gates the auto-apply zones on them as follows.

_Auto-map_ requires **all three** of:

1. any one of — normalized-exact or known-alias match (case, separators, and
   `FieldSpec.source_keys` folded); **or** string similarity ≥ 0.90; **or** embedding
   cosine ≥ 0.95;
2. the best candidate beats the runner-up by ≥ 0.05 on whichever signal fired;
3. type compatibility.

_Auto-add as new_ requires that both signals fall below their **own** ceiling against
**every** existing field:

```
string_similarity  < 0.65
embedding_cosine   < 0.30
```

Everything else is uncertain, and D27 decides what happens then. The cheap string pass runs
first, so a label that is identical after normalization never spends an embedding call.
String similarity is measured on a case-and-separator fold (`fold_label`).

**Alternatives considered.**

1. _Embeddings only_ (as the plan of record originally read). Handles synonyms, but needs a
   network call for even `vendor_name` versus `Vendor Name`, and leaves the fake provider —
   which must work with no API key, per D11 — with nothing to score with.
2. _String similarity only._ Free, deterministic, offline, and already half-built in
   `app/llm/fake.py` (`LABEL_MATCH_THRESHOLD`, `difflib.SequenceMatcher`). But it scores
   `Supplier` against `vendor_name` at roughly 0.2, so it fails on precisely the renames
   drift detection exists to catch.
3. _A single weighted blend_, `w1 * string + w2 * embedding`. Rejected because averaging
   destroys the signal: a true synonym scores near-zero on string and high on embedding, and
   the blend lands it in the ambiguous band. The two signals are evidence of different
   things and should not be averaged.
4. _A strict AND of both signals._ Safest against false positives, but it cannot ever
   auto-map a synonym, since a synonym fails the string test by definition. That is
   alternative 2 with extra steps.
5. _One shared novelty ceiling for both signals._ Rejected: a character ratio and a cosine
   are not comparable numbers, so holding them to one threshold is a category error, and it
   makes the auto-add zone unreachable in practice.
6. _A filler-word fold for the string signal_, dropping "id", "number" and "reference".
   Rejected because it scores `Supplier` against `Supplier ID` at 1.00, clearing the
   auto-map bar and merging a company name into an identifier column.

**Reasoning.** The two signals fail on disjoint cases, which is what makes OR the right
combinator rather than AND or a blend: string similarity catches formatting and typo
variants that embeddings waste a call on, embeddings catch semantic renames that string
matching cannot see at all. Requiring either to fire, rather than both, is what lets both
classes of obvious match resolve without troubling anyone.

The margin rule is what keeps OR from being reckless. A high absolute score is not evidence
of an unambiguous match when a second field scores nearly as high — `Supplier` at 0.96 to
`vendor_name` and 0.94 to `supplier_id` is a genuine judgment call, and the margin test is
what routes it to the safe answer instead of a coin flip. This is the same instinct as D5:
the useful question is rarely "how confident is the score," it is "is there a competing
answer."

Novelty inverts the combinator deliberately. Declaring a field _new_ is a claim about the
absence of a match, so both signals have to agree nothing resembles it; if either sees a
resemblance, it is not clearly novel.

**The numbers are measured, not guessed.** Across the fixture corpus the highest string
similarity between two genuinely different field labels is **0.59** (`Currency` versus
`Reference`), with `Invoice No` versus `Vendor` at 0.50 and a p90 of 0.38. That distribution
is where the 0.65 string ceiling comes from, and it is also why the ceilings are per signal:
at a shared 0.30, every candidate field resembles something, and no field is ever "clearly
novel".

The same measurement is the strongest evidence for the OR combinator. `Supplier` versus
`Vendor` scores 0.29 on the string signal and `Amount` versus `Total Due` scores 0.27, both
**below** the 0.59 that two unrelated labels reach. On renames the string signal is not
weak, it is actively misleading. Embeddings do all the semantic work, and the string signal
is confined to the 0.90-and-above band where it catches formatting and typo variants, which
is the only job it can do honestly.

**Test and no-key behavior.** `LLMClient` gains `embed()`. `GeminiClient` calls the real
embeddings endpoint — the assumption for actual usage is a working API key, per D11, and
this decision is not designed around the model being unavailable in production. `FakeClient`
replays recorded vectors keyed the same content-derived way its other fixtures are, which is
what keeps the test suite and a no-key reviewer clone deterministic and network-free; that
is D11's concern, not a production fallback. If a live call genuinely fails (network error,
rate limit), that is handled by the existing `LLMUnavailable`/retry path in `app/llm/base.py`
like any other model call — it is a failure to surface and retry, not a silent
degrade-to-string-only mode.

**Cut.** A locally-hosted embedding model, on exactly the grounds D3 rejected Docling: a
multi-gigabyte dependency defeats the one-command setup. Also cut: a second string metric
for the novelty test alone, when a per-signal ceiling achieves the same separation with a
number.

**Still to measure.** `drift_novelty_ceiling_embedding` is the one threshold set by
assertion rather than by measurement, because measuring it needs a live key and the cosine
distribution over field pairs a human calls different. Unrelated business terms score
roughly 0.4 to 0.7, so 0.30 is deliberately strict: erring strict costs an occasional extra
column and never a wrong merge.

**Accepted cost.** Roughly half a day — the protocol method, the Gemini implementation,
recorded fixtures for the sample corpus, a label-keyed cache so a schema's labels are not
re-embedded once per document, and the thresholds in configuration.

## D19. Background work is queued after the transaction commits, never inside it

**Date:** September 4, 2026 · **Status:** Active

**Decision.** A request that creates a row and wants it processed calls
`submit_after_commit(session, document_id)`, which stages the identifier on the session.
`app/deps.py` flushes the staged submissions after the commit succeeds and discards them on
rollback. Direct `worker.submit` is reserved for callers holding an already-committed row.

**Alternatives considered.** Calling `worker.submit` from the route, which is the obvious
code and is what shipped first. Committing the document row early in its own transaction,
which splits one logical operation into two and leaves an orphan row if the rest fails.

**Reasoning.** The obvious version is broken, and its symptom is genuinely hard to diagnose
from the outside. The upload route creates a `documents` row and queues it; the row is not
committed until the request finishes, while the consumer pool picks the identifier up within
microseconds and opens its **own** session to load it. The row is not there, so the consumer
logs "document missing" and drops the job.

This is not theoretical. Uploading six files reproduced it on the first try: five were
dropped and one survived by winning the race with the commit. From the interface it looks
like documents stuck in `uploaded` forever, with nothing in the log but a warning.

The event bus already had this exact problem and already solved it this way, staging on the
session and flushing after commit, so this makes both halves of "the world changed" consistent:
nothing is announced, and no work is started, until the change is actually true. Having two
mechanisms for the same ordering problem would have been the real smell.

**Cut.** Nothing. The direct `submit` remains for the boot-time resume path, where the rows
are committed by definition.

**Caught by:** an end-to-end run against a live server, not by the test suite. Worth noting,
because every unit test passed while five of six uploads were being dropped. Regression tests
now cover the staging, the discard, and the flush.

---

## D20. React Router in declarative mode for the interface, not a type-generated router

**Date:** September 4, 2026 · **Status:** Active

**Decision.** Route the client with `react-router` 7 used declaratively — a `BrowserRouter`
with a `Routes` block in `client/src/app/App.tsx`. No file-system routing, no generated
route tree, no loaders.

**Alternatives considered.** TanStack Router, which would have matched the TanStack Query
and TanStack Table already chosen and would give typed path and search parameters. React
Router's own framework mode with file-based routes and loaders. No router at all, switching
on a piece of state.

**Reasoning.** The application has two routes today and will have perhaps five: the first
run screen, the workspace shell, and whatever the query console and review queue become.
TanStack Router's real advantage is type-safe search parameters, and this product keeps
almost nothing in search parameters — the workspace identifier is a path segment and the
token is deliberately not in the URL query at all (decision D21). Buying a route-generation
build step to type two parameters is a poor trade in a five-day build. Framework mode brings
loaders and a data layer that would duplicate TanStack Query, which already owns server
state. Doing without a router entirely was rejected because a shared workspace link has to
be a real URL that survives a reload.

**Cut.** Typed route parameters, which are asserted at the one call site that reads them
instead. Route-level code splitting, which is not needed until the A2UI chunk arrives; that
is lazy-loaded on its own rather than per route.

---

## D21. The workspace token travels in the URL fragment, never the query string

**Date:** September 4, 2026 · **Status:** Active

**Decision.** A shareable workspace link is `/w/{id}#t={token}`. On arrival the fragment is
read once, written to `localStorage`, and stripped from the address bar with
`history.replaceState`. In-application navigation carries no token at all, because storage
already has it.

**Alternatives considered.** A query parameter, `/w/{id}?t={token}`, which is the obvious
reading of "the token is encoded in a shareable URL" in requirement FR-01. A token in the
path. Storage only, with no shareable link, which would have contradicted FR-01.

**Reasoning.** Decision D7 accepts that anyone holding the link holds the workspace; that
is the stated cost of having no accounts. It does not follow that the credential should be
handed to every intermediary on the way. A query string is sent to the server on every
request, so it lands in access logs, in any reverse proxy in front of the application, and
in `Referer` headers on outbound links. A fragment is never transmitted at all. The two
options are identical for the person pasting a link to a colleague and materially different
for everything in between, so the fragment is simply the better version of the same feature.

Stripping the fragment after reading it means a reload, a bookmark, or a screenshot of the
address bar no longer carries the credential either.

**Cut.** Nothing. The link is the same length and works the same way.

**Accepted risk.** A person who bookmarks the stripped URL and later clears site data loses
the workspace, because the token is unrecoverable by design. The workspace shell will need a
visible "copy shareable link" affordance so the full link can be recovered while storage
still has it; that is noted as work, not solved here.

---

## D22. A warm-paper visual language, rebuilt in styled-components rather than adopted as Tailwind

**Date:** September 4, 2026 · **Status:** Active

**Decision.** Adopt the visual direction from the Flowstep design for screen 1 — warm paper
ground (`#FAF8F5`), navy ink (`#1A2238`), a serif display face for headlines against a
humanist sans for the interface, hairline rules, and an illustration in which scattered
documents narrow through a funnel into one ruled table. Rebuild it as tokens in
`client/src/ui/theme.ts` and styled-components, rather than importing the design's Tailwind
classes.

Type is set in system faces only: `Iowan Old Style` / Palatino / Georgia for display, the
system sans for interface text.

**Alternatives considered.** Pasting the generated Tailwind JSX and adding Tailwind to the
project, which would have been the fastest route to pixel parity and would have reversed
decision D9 by the back door. Loading the design's intended webfonts from Google Fonts.
Inventing a different visual language.

**Reasoning.** The design is a specification of intent, not a source file. Its value is the
decision that this product should look like a precision instrument on paper rather than
another indigo SaaS dashboard, and that value survives the translation intact — the
rendered screen is faithful. Bringing Tailwind in to preserve the class names would have
undone a decision made on fluency grounds three days earlier, and split the styling story
across two systems for one screen.

System fonts, because a webfont is a network round-trip on the very screen whose job is to
explain the product in thirty seconds, and a third-party font request contradicts the line
in the footer promising the documents never leave the workspace. The serif is doing a
register job, not a brand job, and a good system serif does it.

The tier palette (high / medium / low / conflict / verified) is defined in the same file
even though the table that consumes it is a later screen, so the rule that confidence is
never colour alone has one home. Each tier carries a colour, a mark, and a label, and
`ui/theme.test.ts` asserts both the second channel and a 4.5:1 contrast ratio for every
token pair, so the accessibility promise fails the build rather than an audit.

**Cut.** Pixel parity with the design's exact greys, which were warmed slightly to reach the
contrast floor. The design's webfonts.

---

## D23. Product pivot: three screens, chat first, no schema review loop

**Date:** September 4, 2026 · **Status:** Active. Supersedes D1 in part and sets the frame
for D24 through D31.

**Decision.** Distill is three screens and nothing else: **Upload** many documents,
**Chat** with the whole collection (the main screen), and **Data**, one unified table plus a
dashboard of charts and metrics the agent decided were worth showing. The schema review loop
(proposal cards, schema history, one-click revert, the review queue and its keyboard flow)
and the natural-language-to-SQL query console are removed from the product. The extraction
pipeline, automatic schema unification, confidence tiers, provenance highlighting, and the
never-overwrite-a-correction guarantee all stay.

**Alternatives considered.**

1. _Continue the v1 plan._ Two days of backend work implements it and it runs. Rejected on
   the product judgment below, not on feasibility.
2. _Keep the review loop but demote it to a side panel._ Rejected because a half-present
   review loop still needs its data model, its routes, its cards, and its history view to be
   correct, which is most of the cost for a fraction of the attention.
3. _Chat only, no table._ Rejected because the prompt asks for structured data, and a table
   is the honest proof that the documents were actually read into fields.

**Reasoning.** The review loop asks a finance operations person to do schema
administration: decide whether `Supplier` and `vendor_name` are the same column, adjudicate
type mismatches, revert schema versions. That is a data engineer's job dressed as a product
feature. The person who uploaded the pile wants three things: see it as a table, ask
questions about it and be able to check the answers, and be shown what is interesting
without asking. v2 is those three things, one screen each.

The parts of v1 that carried trust were never the review loop. They were the citations, the
highlight on the page, the visible confidence tier, and the guarantee that a human edit
survives. All of those are kept and extended into the chat and the dashboard.

Extraction, grounding, scoring, unification, and the event log are unchanged by this
pivot. What is thrown away is the proposal machinery and the SQL path; what is added is
retrieval, chat, a query-specification evaluator, and A2UI on both new surfaces.

**Cut.** Proposal cards and the `proposals` table and routes; schema history view and
revert; backfill; the review queue and keyboard flow; natural language to SQL, the SQL
panel, `sqlglot`, the read-only database role, the per-workspace pivot view; the 5,000-row
virtualised table; Playwright for this round. Recorded honestly in requirements v2 section 0
rather than rewritten out of history.

---

## D24. Retrieval over the documents replaces natural language to SQL

**Date:** September 4, 2026 · **Status:** Active. Supersedes the generated-SQL half of v1 and
the view half of D4.

**Decision.** Questions are answered by retrieval-augmented generation (RAG): the question
is embedded, the most similar passages of document text are found by cosine similarity, and
the model answers **only from those passages plus the extracted records**, citing each claim.
When an answer needs a number, the model emits a query specification that the server
evaluates over `field_values` in Python (see D26). No SQL is generated anywhere.

**Alternatives considered.**

1. _Natural language to SQL over a typed per-workspace view_ (v1, D4). Precise for
   aggregate questions the schema anticipated; blind to everything the schema did not
   capture, which for a contract or a policy document is nearly all of it.
2. _Both: SQL for structured questions, retrieval for the rest, with a router._ The most
   capable option and the most expensive: two query paths, two failure modes, a classifier
   in front, and the four-limit SQL guard still to build and test. Rejected on the remaining
   time.
3. _Retrieval only, with the model computing aggregates from retrieved rows._ Rejected
   because it violates the data-binding rule in D26: a model summing numbers in prose is
   exactly the failure a finance user cannot detect.

**Reasoning.** Retrieval answers the question the person actually asked, in the vocabulary
the documents actually use, and it produces a citation as a by-product because the answer
came from a passage. That is a better fit for "every value traces to a highlighted region"
than SQL ever was, since a SQL result's provenance had to be reconstructed from row
identifiers after the fact.

The structured half is not lost. Each document's extracted record is rendered as a "records
digest" chunk and embedded alongside the page text, so a question phrased in schema
vocabulary retrieves the record even when the page says it differently. Aggregations are
handled by the query-specification evaluator, which is a small, testable Python function
over the workspace's values, rather than by generated SQL against a pivot view.

**Cut.** `sqlglot`, `DATABASE_URL_READONLY`, `app/schema/view.py`, the `queries` table,
`CallKind.NL2SQL`. Added: `CallKind.CHAT_ANSWER` and `CallKind.PLAN_DASHBOARD`, both on the
Flash tier.

---

## D25. Vectors stored as JSONB arrays with in-process cosine, not pgvector

**Date:** September 4, 2026 · **Status:** Active

**Decision.** Chunk embeddings are stored in a `chunks.embedding` JSONB column as a list of
floats. Retrieval loads the workspace's vectors and computes cosine similarity in Python.

**Alternatives considered.**

1. _pgvector._ The right answer at scale: indexed nearest-neighbour search in the database.
   It is an extension that must be installed and enabled; the development machine has a
   Homebrew Postgres 16 with no extensions, and every reviewer's machine would need the same
   step in `make setup`.
2. _A separate vector store (Chroma, Qdrant, LanceDB)._ Another process or another
   dependency for a workload of a few hundred vectors per workspace.
3. _SQLite with a vector extension._ Would split the data across two databases.

**Reasoning.** A workspace is bounded by `max_files_per_upload` and practical use to tens of
documents. At roughly forty passages per document, that is about a thousand vectors of 768
floats, which a Python loop scans in a few milliseconds. The cost of pgvector is a setup step
on every machine that touches the project; the benefit is speed the workload does not need.
The scan is a pure function of the loaded vectors, which also makes retrieval trivially
testable with recorded fixtures.

**Upgrade path.** The `chunks` table and the `search.py` interface are shaped so that
swapping the scan for `ORDER BY embedding <=> :q LIMIT k` is a migration that changes the
column type and one function body.

**Cut.** Approximate nearest-neighbour indexing.

---

## D26. Displayed numbers are computed by the server and bound by path; the model never types them

**Date:** September 4, 2026 · **Status:** Active. This is the rule Anubhav described as
"we send a variable with the data mapped to it".

**Decision.** Whenever the agent wants to show a figure, a chart, or a table, it does not
emit the values. It emits a **query specification** (`DataQuery`: measure, aggregate, group
by, date bucket, filters, sort, limit). Deterministic code evaluates the specification over
the workspace's `field_values`, writes the result into the A2UI **data model** at `/result`,
and emits components whose properties are **path bindings** into that data model. The model
chooses `BarChart` and says the series lives at `/result/rows`; the server puts the real rows
there.

The general name for the pattern is **data binding** (in A2UI, the data model plus `path`
references). In prompting terms it is structured output with variable references instead of
literal values, evaluated by the application. It is the same instinct as function calling
with the tool result rendered directly, without a second model call to restate the result.

**Alternatives considered.**

1. _Let the model write the numbers into the A2UI component properties._ Simplest, and the
   most dangerous: a transposed digit in a bar chart is undetectable to the person reading
   it, in a product whose only claim is that the numbers can be trusted.
2. _Full function-calling loop._ The model calls an `aggregate_records` tool, receives the
   result, then writes the answer and the UI. Correct, and it would also let the model
   inspect the result before deciding on a shape. Rejected for this round because the
   `LLMClient` protocol has a single `structured()` method, the fake provider would need a
   tool-call simulator, and the two-turn latency lands on the demo's main screen. The query
   specification gets most of the benefit in one structured call.
3. _Model writes SQL._ D24.

**Reasoning.** Separating "what to show" from "what the values are" is what makes both the
chat visuals and the unsupervised dashboard safe without a human review step. The model is
good at deciding that spend by vendor is the interesting cut; it is bad at adding up
fourteen currency amounts. The specification also carries the row identifiers that produced
each result row, which is how provenance survives inside agent-generated UI (FR-43): a
number the model typed has no provenance, a number the evaluator computed knows exactly
which cells it came from.

**Consequences.** A visual whose specification evaluates to nothing is dropped and logged
rather than shown empty. The `DataQuery` model is shared between the chat answer and the
dashboard planner, so there is one evaluator to test. The fallback renderer can always show
`/result/rows` as a table because the data model is always populated by the server.

**Cut.** Free-form numbers in any agent-produced component property. `Metric.value` is a
path binding, not a literal.

---

## D27. Uncertain schema drift resolves to a separate field, silently

**Date:** September 4, 2026 · **Status:** Active. Supersedes the v1 proposal-card design. Narrows
D18, which remains the signal for the auto-map and auto-add zones.

**Decision.** When a new document's field cannot be confidently matched to an existing field
or confidently declared novel, the system **adds it as a separate field** and records why in
`schema_versions.change_summary`. No proposal card, no queued question, no history view. The
user's recourse is a column menu on the Data screen: rename, or "merge into" another field,
which moves values and provenance and is lossless.

**Alternatives considered.**

1. _Proposal cards_, the v1 design. Fully designed, partly built. Withdrawn with the review
   loop in D23.
2. _Merge on uncertainty._ Rejected on the same asymmetry v1 recorded: a wrong merge pools
   values from two different fields under one column and unpicking it means knowing which
   source key produced each value; a wrong split is two clean columns and a merge is a move.
   When unsure, prefer the error that is cheaper to undo.
3. _Let the model decide with a coin flip when uncertain._ Rejected: it is alternative 2
   half the time.

**Reasoning.** D18 works out _when_ the system is unsure. This decides the _response_, and
the response is to default safely rather than to ask.
The auto-map zone keeps `Supplier` landing in `vendor_name` when the embedding says so; the
auto-add zone keeps a clearly new field appearing as a new column; the middle zone now does
the safe thing instead of raising a hand. The user sees one extra column occasionally, with
a summary that says why, and can fix it in two clicks if they care. Most will not need to.

**Cut.** The `proposals` table and routes, `Proposal.kind`, `AskReason` as a user-facing
concept (it survives as text in `change_summary`), the debounce setting, and the merge
question at initial unification.

---

## D28. A2UI for chat visuals and dashboard panels

**Date:** September 4, 2026 · **Status:** Active. Supersedes the v1 A2UI scope, which served query results and schema
proposals.

**Decision.** The Agent-to-User Interface protocol is used for exactly two surfaces: the
optional visual inside a chat answer, and each panel of the generated dashboard. In both, the
server builds a complete message array (`createSurface`, `updateDataModel`,
`updateComponents`) and the client renders it from a catalog of four custom components
(`Metric`, `BarChart`, `LineChart`, `ResultTable`) plus the basic catalog for layout and
text. The rest of the application, including the unified table, is hand-built React.

**Alternatives considered.** Hand-built result components switched on a `kind` string
returned by the model. This is genuinely close in effort for four component kinds. It was
rejected because the value of the protocol here is not the renderer, it is the **data
model**: the path-binding contract is what enforces D26 mechanically, and the JSON Schema
validation of emitted messages gives the backend a test that the surface is well formed
before a browser ever sees it. Using A2UI for the main table, as considered and rejected in
v1, is still rejected for the same reason: the table does not need the agent to choose its
shape.

**Reasoning.** Both surfaces are "the agent decided what to show", which is the case the
protocol exists for. Keeping them on one mechanism means one builder module, one renderer
module, one fallback, and one inspect toggle serving both the chat and the dashboard.

**Accepted risk.** Renderer churn, as v1 already noted. Exact pins, a four-component catalog, and a
smoke test per component in Vitest.

**Cut.** Streaming A2UI messages piecemeal (a surface arrives whole in one event even
though the answer around it streams; see D32), the `SchemaProposal` and
`FieldMapping` components, A2UI action round-trips as a Must (a row click in
`ResultTable` is handled on the client; server round-trips are a Could).

---

## D29. Dashboard panels are proposed by the model from field statistics and vetted by evaluation

**Date:** September 4, 2026 · **Status:** Active

**Decision.** The dashboard is generated by one structured call on the Flash tier that
receives the document count, the schema, and per-field statistics (type, coverage, distinct
count, numeric range and sum, date range, top values) and returns up to six panels, each a
title, a visual kind, a `DataQuery`, and a one-sentence rationale grounded in those
statistics. The server evaluates every panel and drops the empty and the degenerate (a
single-bar chart, a metric over a field fewer than a third of documents carry) before
anything is shown. Panels persist with the workspace and are marked stale when documents are
added, values corrected, or fields merged.

**Alternatives considered.**

1. _Hard-coded dashboard rules_ ("if a currency field and a string field both have coverage
   above 70%, chart sum by string"). Deterministic and domain-agnostic in principle, but it
   cannot know that spend by vendor is more interesting than spend by currency, and the
   rules would be tuned to invoices within a day.
2. _Let the model write the panel data._ D26.
3. _Generate the dashboard on every new document._ One model call per upload for a screen
   the user may not be looking at. Rejected in favour of marking stale and regenerating on
   demand or on the first-batch completion.

**Reasoning.** Deciding what is worth showing is judgment, which is what the model is for.
Computing what is shown is arithmetic, which is what the evaluator is for. The statistics in
the prompt are what let the model's judgment be grounded rather than generic: it can see
that `purchase_order` is missing from three documents and propose a metric about it. The
rationale is shown to the user because a chart with a stated reason is a chart the user can
disagree with, which is the trust posture of the whole product.

**Cut.** User-arranged or user-pinned panels. Panel-level regeneration. Automatic
regeneration on upload.

---

## D30. Corrections stay as inline cell edits; the review queue is cut

**Date:** September 4, 2026 · **Status:** Active

**Decision.** A person can still correct a value by editing a cell on the Data screen
(Should), the value becomes human-verified, and re-extraction never overwrites it, with a
disagreeing model value shown as a conflict (D13 stands, FR-51 is a Must). The review queue,
impact ordering, and keyboard review flow are removed.

**Alternatives considered.** Keeping the queue as a filter on the table ("show me low
confidence cells"). Removing corrections entirely.

**Reasoning.** The correction guarantee is a backend property that is already built and
tested, and it costs nothing to keep. The review queue was a fourth screen's worth of
interface serving the review loop's mental model, in which a person works through cells
before trusting the table. v2's model is that confidence is visible where the value is and
the person corrects what they happen to notice. A sort by tier on the table gets most of
what the queue offered for free.

**Cut.** `GET /review`, the impact weighting, `useReviewKeys`, and acceptance criteria that
depended on them.

---

## D31. The source viewer shows backend-rendered page images for every format, including PDF

**Date:** September 4, 2026 · **Status:** Active. Extends D14.

**Decision.** The client's source viewer displays `GET /pages/{n}/image` for every document,
PDFs included, and draws highlight rectangles scaled by `renderedWidth / width_pt`. The
client does not embed pdf.js.

**Alternatives considered.** react-pdf (pdf.js) for PDFs with the backend render for other
formats, as v1 section 8.3 planned.

**Reasoning.** D14 already renders every format to page images with word geometry, and the
PDF renders already exist because the OCR path and thumbnails needed them. Two rendering
paths in the viewer means two coordinate systems to keep in agreement, which is the exact
risk the coordinate-convention test was written to contain. One image and one overlay is one unit test. The cost is
that a PDF is shown as a raster at 144 DPI rather than as selectable vector text, which for
a panel whose job is to show where a value came from is acceptable, and the original is one
click away for anyone who wants it.

**Cut.** react-pdf and the pdf.js worker configuration in Vite. Text selection inside the
viewer.

---

## D32. Chat answers stream token by token over a per-message Server-Sent Events stream

**Date:** September 4, 2026 · **Status:** Active. Supersedes the one-request, one-response chat design.

**Decision.** Asking a question is two requests. `POST /chat/messages` persists the user
turn, creates the assistant message in `streaming` state, starts generation as a
background task, and returns `202` with the message identifier and a stream URL. The client
opens a native `EventSource` on `GET /chat/messages/{id}/stream`, which tails an in-memory
**answer buffer** for that message and emits, in order: `status`, `sources`, `visual` or
`visual_skipped`, `token` events, `citation` events as markers appear, and `done` with the
persisted message. Every event carries a per-message sequence `id`, so a reconnect resumes
with `Last-Event-ID` and a late subscriber to a finished message receives one `done`.
Generation does not depend on a listener: closing the tab does not stop the answer, and
`POST .../stop` is the only way to cancel. Token events are never written to
`workspace_events`; the persisted result is the message row.

**Alternatives considered.**

1. _Return the whole answer in one response_, which is what the plan of record said.
   Simplest and safest for a structured
   object. Rejected: a chat that sits on a spinner for eight seconds and then drops a wall of
   text is the one thing a reviewer of a frontend-weighted submission will notice first.
2. _Stream on the `POST` response itself_ with `fetch` plus a `ReadableStream` line parser.
   One round trip fewer, but `EventSource` cannot be used, so resume, backoff, and
   `Last-Event-ID` all have to be hand-written, and a dropped connection kills the generator
   because the response _is_ the generation. Two requests buy the browser's native
   reconnect and a generation that outlives the connection.
3. _Multiplex tokens onto the existing `/events` workspace stream._ One connection, and
   resume already works. Rejected because D12 persists every workspace event to a table,
   which is the wrong contract for hundreds of token frames per answer, and because a
   second tab would receive every token of every answer whether or not it is showing the
   chat.
4. _WebSockets._ Bidirectional transport for a one-directional stream; D6 already rejected
   it for the same reason.

**Reasoning.** The blocker in that plan was real: citations must resolve to validated chunks and
the visual must be evaluated before it can be shown, and neither can be done on a
half-received structured object. The answer is not to give up streaming but to stop asking
one call to produce everything. A short structured **plan** call decides answerability and
the visual; the visual is evaluated and sent whole before the first token; then a streamed
**prose** call writes the text, with markers and placeholders resolved by the server as they
close (D33, D34). Everything the user sees is validated by the time they see it, and it
arrives as it is written.

The buffer is in memory rather than a table because D8 already pins the application to one
process, so there is nowhere else a second subscriber could be. It is released a minute
after completion so a resumer who reconnects late still catches up, after which the
persisted message is the only source and `GET /chat/messages` serves it.

**Cut.** Streaming A2UI messages piecemeal (the surface is one event). Streaming on
the dashboard, which is generated in the background and announced over `/events`.

**Accepted cost.** A second stream type on the client with its own reducer and tests, and
the `LLMClient` protocol growing a `stream_text` method that the fake provider has to
simulate with recorded text in word-sized pieces.

---

## D33. Citations are chunk-level markers resolved while the answer streams

**Date:** September 4, 2026 · **Status:** Active

**Decision.** The prose model cites with `[^chunk:<id>]` markers and writes no quotes. The
stream processor holds back an open marker until it closes, validates the identifier
against the retrieved set, assigns a citation number, and emits a `citation` event carrying
the chunk's page and boxes (its stored `word_start` to `word_end` span) **before** the token
containing the rewritten `[^n]`. Unknown identifiers are dropped silently. The highlight in
the viewer is the whole chunk, so chunks are kept to roughly 80 to 160 words.

**Alternatives considered.**

1. _Verbatim quotes grounded with RapidFuzz_, as the extraction pipeline does.
   Tighter highlights. Rejected for chat because a quote cannot be
   validated until it is complete, which means either holding back whole sentences during
   the stream or resolving citations after the fact, and a marker that sits unresolved for
   several seconds is exactly the "is this real?" moment the citation exists to prevent.
   Quotes also fail to ground often enough on paraphrase that a fallback to the chunk span
   would have been needed anyway.
2. _Resolve all citations after streaming completes._ Simplest. Rejected because the markers
   would appear as dead text during the stream.
3. _Sentence-level re-grounding after the stream_: match each cited sentence back against
   the chunk to narrow the box. Possible later as a refinement; not in this round.

**Reasoning.** For the extraction pipeline, a quote is the right unit because a field value
is a few words on a page. For a chat answer, the unit of evidence is a passage, and the
chunk already is one. Making the chunk the citation removes a model output that could be
wrong (the quote) and a matching step that could fail (grounding), and replaces both with a
lookup. The cost is a paragraph-sized highlight, which the smaller chunk size keeps
readable. Citations to a records-digest chunk resolve to the field value's own provenance,
so structured facts still light up on the page.

**Cut.** Quote-level highlights in chat.

---

## D34. Figures in chat prose are placeholders the server substitutes from the evaluated result

**Date:** September 4, 2026 · **Status:** Active. Extends D26 to prose.

**Decision.** When an answer has a visual, the prose model receives the evaluated result
with named paths and is instructed to refer to any figure from it as `{{result.total}}` or
`{{result.rows[0].value}}`, never by retyping the number. The stream processor holds back
text from an open `{{` until `}}`, resolves the path against the result, and emits the
formatted value (currency with its code, date localised). An unresolvable path emits
nothing and is logged. Figures that appear verbatim in a cited passage may be repeated as
written, because their provenance is the citation.

**Alternatives considered.** Passing the computed result into the prompt and trusting the
model to copy it correctly. Forbidding numbers in prose altogether and pointing at the
chart. Post-checking every number in the finished prose against the result.

**Reasoning.** D26 made displayed numbers in _components_ come from the evaluator. Prose is
also a display. A model that has just been shown `48,200.00` will usually write it
correctly, and "usually" is the problem in a finance product: the one transposition is
invisible. A placeholder is the same idea as a path binding in A2UI, applied to text, and it
is what Anubhav was describing as sending a variable with the data mapped to it. It also
keeps the chart and the sentence about the chart from ever disagreeing, because both read
the same result. Forbidding numbers would make answers stilted; post-checking would need the
whole text first, which streaming forbids.

**Cut.** Nothing. Numbers copied from passages remain allowed because they are cited.

---

## D35. The three-screen switch is application chrome, present before a workspace exists

**Date:** September 5, 2026 · **Status:** Active inside a workspace. The first-run half is
**superseded by decision D39**, which takes the header off screen 1 entirely.

**Decision.** One `AppHeader` serves all three screens: identity on the left, an optional
workspace chip (label and document count), and a segmented Upload / Chat / Data control on
the right, with "Add documents" beside it inside a workspace. On the first-run screen the
header still renders, showing all three segments with Chat and Data inert.

Which screen is current is passed in as a prop rather than derived from route matching.

**Alternatives considered.** Showing no chrome on the first-run screen, which is what the
screen had before and what a marketing landing page would do. Hiding the Chat and Data
segments until they work. Letting `NavLink` decide the active segment from the URL.

**Reasoning.** D23 cut the product to three screens; the header is where that decision
becomes visible. A first-time visitor who can see the whole product in one glance
understands the shape of it before uploading anything, and the two inert segments are a
better explanation of what happens next than a sentence would be. Hiding them would make the
header change shape on first upload, which reads as the interface rearranging itself.

The inert segments are `span`s, not disabled buttons, so the keyboard skips them rather than
landing on focusable dead ends.

Route matching was rejected because Chat lives at **both** `/w/{id}` and `/w/{id}/chat`
(requirements section 3.2). A `NavLink` pointing at the second does not match the first, so a
shared link landed on the workspace with no segment lit at all — observed in the browser, not
reasoned about. Redirecting `/w/{id}` to `/w/{id}/chat` would have fixed the highlight and
broken something worse: the access token arrives in the URL fragment (D21) and is consumed on
mount, so a redirect before that runs discards the credential. Passing the active screen down
avoids both, and styling keys off `aria-current` so the visual state and the announced state
are one fact rather than two that can drift.

**Cut.** Automatic active-state detection. The caller now has to say which screen it is,
which is one line at each of three call sites.

---

## D36. The upload screen owns the transfer and narrates what happens next

**Date:** September 5, 2026 · **Status:** Active

**Decision.** Files chosen on the first-run screen are not sent from it. The workspace is
minted, the selection is staged, and the person lands on `/w/{id}/upload`, which owns the
transfer and everything after it. Five parts, which are one decision:

1. **Uploading happens here, one request per file**, with a bar per file. `XMLHttpRequest`
   rather than `fetch`, for the one reason below.
2. **The samples path lands here too** rather than going straight to Chat, so the route a
   reviewer is most likely to take is not the one that shows the least.
3. **The screen narrates the whole pipeline**, per document: reading the file, pulling out
   values, making it searchable, ready. A row carries on past "Sent" into what the server is
   doing with it, and the summary above the rows counts documents *ready*, not bytes
   *arrived*.
4. **The way forward is a Continue button, not a redirect.** The screen never moves the
   person on its own. The button opens on the **first** document to become readable, and a
   toast confirms when everything this visit set going has been read.
5. **"This visit" gates both the toast and the button.** One piece of state, set at mount
   when the pending store holds an entry for this workspace and set again when files are
   added from inside it. Opening the Upload tab on a workspace that finished reading an hour
   ago announces nothing and holds nothing.

**Alternatives considered.**

1. _Navigate to Chat as soon as the bytes are sent._ Nothing to watch while a document is
   still being read, and a question asked against a document that is not yet indexed is
   answered from nothing.
2. _Navigate automatically once everything is read_, with a countdown and a cancel.
   Rejected on the asymmetry in the reasoning below.
3. _Open Continue on the last document rather than the first._ Rejected: the next screen is
   a conversation over whatever has been indexed, so one readable document is enough to hold
   one, and waiting for the last file of a batch holds the door shut for no gain.
4. _Keep one multipart request for the whole batch._ Rejected because it cannot produce the
   screen. A single body reports one byte counter, so per-file bars would have to move in
   lockstep — a picture of progress rather than progress.
5. _Keep using `fetch`._ Not possible. `fetch` reports no upload progress at all, in any
   shipping browser. This is the only place in the client that does not use the generated
   `openapi-fetch` client, and the reason is a platform limitation rather than taste.
6. _Show the pipeline only for uploaded files_, leaving the samples path to the processing
   strip on Chat. Rejected: it is the same wait, and hiding it on the shorter route is
   exactly backwards.

**Reasoning.** "Ready" meaning "the server has the bytes" is the wrong place for a progress
row to stop, because nothing useful has happened yet at that point: a document you cannot
ask about is not done in any sense the person cares about. Reporting only the half of the
work that is fast and invisible, and handing over just as the slow half begins, is a screen
that finishes before the work does.

One request per file also isolates failure: a refused scan does not take the other five down
with it, and each row carries its own reason.

Continue rather than a redirect, because any signal for "this person just arrived" is built
on watching the pipeline, and the event stream is durable and resumable from a persisted log
(D6), so reopening a finished workspace can replay documents moving through it. A signal
like that will eventually fire on a visit where nothing new happened, and taking the screen
away from someone who deliberately opened it costs them the thing they came to do. A
disabled button cannot make that mistake: the worst it can do is be shut for a moment on a
screen the person chose to be on. The cost is one click whose answer is rarely in doubt,
which is the cheap side of an asymmetric bet.

**A race this avoids.** "Everything is settled" is trivially true of an empty list, so a
screen that has heard nothing yet would announce completion immediately. The trigger
requires having *watched* at least one document in a non-terminal state first, which is also
the right rule for someone who opens the screen later to look at a finished workspace:
nothing was watched, so nothing is announced.

**Consequences recorded elsewhere.** The Upload tab inside a workspace points at
`/w/{id}/upload` rather than `/`, which closes the footgun where it would have landed a
person on the first-run screen and silently forked a second workspace on drop. Refusals from
the first-run screen travel with the batch, because a notice rendered on a screen being
replaced in the same tick is indistinguishable from no notice at all (FR-03).

**Cut.** A modal or a countdown between the upload and the conversation. Narrating the
reading on the next screen rather than on this one.

---

## D37. The Data screen separates evidence from interpretation, and only one half is client-computed

**Date:** September 5, 2026 · **Status:** Active

**Decision.** Screen 3 is two columns. Left: the distilled table — every extracted cell with
its type, its confidence tier, and an inline editor. Right: the agent's dashboard panels.

The **Document summary** (total, high confidence, needs review, conflicts, unverified) is
computed in the browser. The **dashboard panels** are not, and never will be.

**Alternatives considered.** One column with the dashboard stacked under the table. Computing
the panels client-side from the records already fetched, which would have made the whole
screen work today with no new backend.

**Reasoning.** The split is the trust argument of the screen. On the left is what the
documents said, cell by cell, each traceable to a highlighted region. On the right is what
the agent concluded. A person can always walk from a number in a panel back to the row that
produced it; blending the two would lose that.

The line between what may be computed here and what may not is **who chose the question**.
The summary counts rows by a tier the server derived — nothing planned it, and asking the
server to count what the client can already see would add a round trip and a second place
for "needs review" to drift. A dashboard panel is the opposite: the agent decides that spend
by vendor is worth showing, and product principle 3 with decision D26 require the server to
evaluate that specification and bind the result. Computing those in the browser would
technically produce the same numbers today and quietly break the guarantee the moment a
panel's definition got interesting.

So the panel components ship as frame only — title, one-line rationale, and the states.
The body stays empty until `GET /dashboard` and the A2UI catalog exist.

**What is not built, and is not stubbed.** `GET /workspaces/{id}/dashboard` and
`POST /dashboard/generate` are planned in implementation.md section 5 and do not exist:
`server/app/insights/` has `queryspec.py`, `evaluate.py` and `stats.py`, and no
`dashboard.py` or router. `useDashboard` calls them anyway and turns the 404 into the
`absent` state, which is the honest reading — the agent has not generated panels yet — and a
state the screen has to render properly regardless. The source viewer is likewise left
unwired rather than faked: a cell that looks clickable and does nothing is worse than one
that does not yet.

**Cut.** Column rename and "merge into" (requirements section 3.3). They edit the schema
through `PATCH /schema` and land with that call rather than as menu items that do nothing.

---

## D38. The dashboard is agent-planned, server-computed, server-vetted, and persisted

**Date:** September 4, 2026 · **Status:** Active, implements decision D29

**Decision.** Four separable choices, recorded together because the value is in the
combination:

1. **The agent plans.** One structured call gets the schema and per-field statistics and
   proposes up to six panels, each a title, a visual kind, a `DataQuery`, and a rationale.
2. **The server computes.** Panels hold query specifications, never numbers. Each is
   evaluated in Python and the result written into the A2UI data model, with components
   binding by path. Identical to the chat path, and for the same reason (decision D26).
3. **The server vets, before anything is shown.** Panels whose query returns nothing,
   charts of a single row, metrics over fields below a third coverage, and groupings by a
   field that is really an identifier are dropped.
4. **It is persisted and marked stale, not regenerated.** Generated when the first batch
   settles and on explicit request; adding documents, correcting a value, or merging fields
   sets `stale = true` and the interface offers to refresh.

**Why the agent plans rather than a template.** A fixed dashboard has to assume a schema,
and this product infers the schema per workspace from whatever was uploaded. A template that
knows about vendors and totals is useless for research papers or property listings, which
section 1.4 of the requirements says must get the same experience.

**Why the server vets, which is the half that is easy to skip.** The agent proposes before
anything is evaluated, so it is guessing at the shape of data it has not seen. An empty
chart, a single bar, or a metric over a field two documents filled in all read as "this
product is broken" rather than "this collection is thin", and this is the first screen a
reviewer sees. Vetting is a handful of in-process evaluations and it is what keeps a first
impression honest.

The identifier rule is worth naming because it took two attempts. Grouping by an invoice
number gives one bar per document, and an absolute distinct-count threshold cannot catch it:
a twenty five document corpus gives an invoice number twenty five distinct values, which
passes any sane limit while being exactly as useless as a thousand would be. The signal is
the **ratio**, `distinct == present`. But the ratio alone over-fires: on a five document
fixture where two documents carry a supplier, "every value is distinct" is what a small
sample looks like, and the first version of the rule threw away three good panels including
one grouped by supplier. It now requires a minimum sample of five before the ratio is taken
as evidence.

**Why stale rather than automatic regeneration.** Regeneration is a model call. Doing one per
uploaded document spends the user's tokens on a screen they may not be looking at, which is
not the server's decision to make. This is open question 2 in the requirements, answered as
the requirements lean.

**Alternatives considered.** A fixed set of panels per field type, which is cheaper and
deterministic and cannot know that a collection of bank statements wants different panels
from a collection of invoices. Regenerating on every upload, rejected above. Letting the
agent return the figures directly, which is decision D26 and is the whole thing this
architecture exists to prevent.

**Cut.** Panel-level interactivity, and drilling from a bar into the records behind it.
`record_ids` is carried in every row for exactly that, so the affordance exists when there is
time for it (requirement A2-07 is a Could).

**A shape note worth keeping.** `Panel.rationale` is deliberately not length-capped on the
response model. A `max_length` there REJECTS rather than truncates, so one verbose rationale
would fail validation for the entire plan and lose every panel with it. The rationale is
decorative; the panel is not. It is truncated when the panel is built.

---

## D39. The first-run screen is a front door, not a workspace: no header, and the name is the illustration

**Date:** September 5, 2026 · **Status:** Active, supersedes the first-run half of decision D35

**Decision.** Three changes to screen 1, which are one change:

1. **No `AppHeader`.** The route `/` renders the name, a sentence, the drop zone, the sample
   link, and the accepted formats. The three-screen switch begins at `/w/{id}/…`.
2. **The name is drawn as particles** that scatter away from the cursor and spring back into
   the letterforms — `ui/ParticleText`, adapted from componentry.dev's cursor-driven particle
   typography.
3. **The funnel illustration is deleted**, not moved. `DistillationMark` is gone from the
   tree rather than left unused.

**Alternatives considered.** Keeping the header with Chat and Data inert, which is what D35
argued for. Keeping both the particle name and the funnel illustration. Making the wordmark
in the header the particle effect, so it appears on every screen.

**Reasoning.**

*On the header.* D35's case was that two inert segments teach what happens after you upload
better than a sentence would. Sitting with the built screen, they do not: they are two grey
words a person cannot click, above a page whose only real content is a drop zone. The
sentence beneath the name already says what happens next, in words, and the drop zone is the
answer to "what do I do". Chrome that switches between screens is worth its space when there
are screens to switch between, which is the moment a workspace exists. The shape of the
product being legible from screen 1 was a real goal; the header was the wrong instrument for
it.

*On the illustration.* Both the funnel and the particle name make the same argument — a
scattered pile resolving into something exact. Making it twice on one screen is making it
weakly, and the funnel was 274px tall plus a caption, which put the drop zone and the sample
link against the fold on a laptop (verified in the browser at 800×450: the funnel was cut in
half and the sample link sat at the bottom edge). The name earns the space the illustration
was taking because it is also the thing the page has to say first.

*On not putting the effect in the header wordmark.* At 17px there is nothing to scatter, and
an animation that runs on the chat screen while a person is reading an answer is noise. The
effect belongs where a first impression is the job and nothing else is competing.

**What the adaptation changed, and why.** The upstream component is a shadcn registry entry:
Tailwind utility classes, a `cn` helper, `"use client"`. The physics is kept verbatim —
120px interaction radius, spring return at 0.08, friction at 0.85. Three things are ours:

- **The loop stops.** Upstream runs `requestAnimationFrame` forever, on a landing page
  nobody is touching. Here it halts once the pointer has left and every particle has
  settled, and a pointer moving over the canvas restarts it. Upstream's random jitter near
  origin was dropped to make a settled state reachable; at 1.5px it was not visible.
- **`prefers-reduced-motion` is honoured** by not creating the canvas at all and rendering
  the word as type. `GlobalStyle`'s reduced-motion block zeroes CSS animation durations and
  cannot reach a canvas, so a component that animates in one has to check for itself.
- **Size is measured, not guessed.** Upstream caps the font at 15% of the container width,
  which is really a guess about letter count: it overflows a long word and starves a short
  one. Measuring with `measureText` against a 86% budget is one extra call and is correct
  for any word in any face. It is what makes the same component render "Distill" at 176px on
  a desktop and fit it inside a 375px phone.

The word is always in the DOM as real text with the canvas `aria-hidden`, so the `h1` has an
accessible name, the page is searchable, and the text is selectable.

**Cut.** The `DistillationMark` illustration, with its six sample filenames — the most
concrete statement of *heterogeneous input* the product had, and the thing genuinely lost
here. If screen 1 ever needs it back, the argument for it is in this entry's git history.
Also cut: the assertion in `FirstRunScreen.test.tsx` that the header renders on `/`,
replaced by its inverse.

---

## D40. Server-Sent Events are read with `fetch`, not `EventSource`

**Date:** September 5, 2026 · **Status:** Active, implements decisions D6 and D32

**Decision.** `client/src/lib/sse.ts` is a hand-written SSE client over `fetch` and
`ReadableStream`, with its own frame parser, its own reconnect loop, and its own
`Last-Event-ID` handling. Both streams use it: the per-answer stream and the workspace event
stream.

**Alternatives considered.** The browser's `EventSource`, which is the obvious choice and
does reconnection and resumption for free. A token in the query string, so `EventSource`
could be used. WebSockets, already rejected in D6.

**Reasoning.** `EventSource` sends no request headers. Every route in this API authorises
with `Authorization: Bearer <workspace token>` (decision D7), and there is no query-parameter
fallback — deliberately, because the token is the *only* credential this product has, and a
credential in a URL ends up in server logs, browser history, and `Referer` headers. Adding
one to make a browser API convenient would trade the security property for the convenience.

So the transport is ours, and two things follow that are requirements rather than
consolation prizes. **Reconnection is implementable to spec**: requirement FR-29 asks the
client to resume from the last event it saw, and both server routes number their events with
a resumable sequence for exactly that. **Cancellation is an `AbortSignal`**, which composes
with React effect cleanup and with controller chaining, where `EventSource.close()` composes
with nothing.

**What the parser has to get right.** The two failure modes are silent, which is why they
are pinned by tests rather than left to inspection:

- A frame split across network chunks. The server flushes per token and the network
  coalesces however it likes, so the split routinely lands mid-JSON. A parser that dispatched
  the partial frame would hand `JSON.parse` a truncated object and drop a token — visible as
  a missing word, not as an error.
- A comment line. `sse-starlette` sends its keep-alive as one every fifteen seconds, and a
  parser that dispatched it would deliver an empty event on a timer.

**Cut.** `retry:` field support, since neither route sets one and the backoff is ours. A
generic event-type registry: both consumers switch on the `type` inside the payload, which
is what the server derives the SSE event name from anyway.

---

## D41. The A2UI catalog is rendered by a hand-written renderer, not `@a2ui/react`

**Date:** September 5, 2026 · **Status:** Active. Reversible; see "What it would take to
switch" below.

**Decision.** `client/src/features/a2ui/` renders a surface itself: `model.ts` folds the
message array into a data model plus a component map and resolves path bindings; `Surface.tsx`
renders the four custom components and the five basic layout and text ones with this
project's own styled components; `SurfaceBoundary.tsx` catches a render error and falls back
to a plain table of the same rows. No `@a2ui/react`, no `@a2ui/web_core`, no Recharts.

**Alternatives considered.** `@a2ui/react` 0.11.0 with `@a2ui/web_core` 0.10.7 and Recharts,
which is what implementation.md section 7 specifies and what D28 assumed.

**Reasoning.** D28's own argument is the reason this is defensible: *"the value of the
protocol here is not the renderer, it is the data model"*. The path-binding contract is what
mechanically enforces D26, and it is enforced here — `readProperty` resolves
`{path: "/result/rows/0/value"}` against the model the server wrote, and `model.test.ts`
holds that a component may not carry a figure inline. The safety argument survives the
renderer choice intact.

What the official package would have added on top of that is a message processor and the
basic catalog's layout components. The four components that matter — `Metric`, `BarChart`,
`LineChart`, `ResultTable` — have to be written as project React components either way,
because that is what a catalog *is*; section 7.2 already scheduled writing all four. So the
package's contribution is the processor and five layout primitives, against a dependency
that also pins Zod to `3.25.76` project-wide and pulls Recharts in for two chart shapes of
one series each.

**This is the part to be sceptical of.** The above is a real argument and it is also the
argument someone makes after building the thing. The plan of record said use the package,
the pin for it is already in `package.json`, and "I wrote it myself and it works" is not by
itself a reason to overrule a decision taken deliberately. Recorded here in those terms
rather than as a settled matter.

**What it would take to switch.** The renderer is one module behind one component:
`AnswerBlock` and, later, the dashboard render `<Surface messages={…}>` and nothing else
touches A2UI. Swapping the internals for `MessageProcessor` and `A2uiSurface` changes
`Surface.tsx` and `model.ts` and leaves the four catalog components, the boundary, the
fallback and every call site as they are.

**What is kept from section 7 regardless.** The error boundary and the fallback (section
7.3), the closed catalog as the allow-list — an unknown component name is dropped at parse
time — the `a2ui.fallback` log line, and strings rendering as text and never as markup.

**Cut for now.** The `Inspect.tsx` developer toggle, and Zod schemas per component: the
catalog is closed at parse time and every property read is total, so a malformed property
renders an em dash rather than throwing. Recharts, whose two chart shapes here are a
baseline with columns on it and a polyline.

---

## D42. Flash for extraction, Flash Lite for anything a user waits on

**Date:** September 5, 2026 · **Status:** Active, supersedes the tier half of D11

**Decision.** `LLM_EXTRACT_MODEL=gemini-3.5-flash` and
`LLM_FAST_MODEL=gemini-3.5-flash-lite`, with `LLM_FAST_THINKING_LEVEL=low` applied to the
calls a user waits on (chat planning, chat answering, dashboard planning, suggested
questions) and never to extraction or schema inference, which keep the model's own default
effort.

**Alternatives considered.** Keeping `gemini-2.5-pro` and `gemini-2.5-flash`, which is what
D11 named before a real key existed. `gemini-pro-latest` for
extraction. `gemini-3.6-flash` for both tiers. `gemini-3.5-flash` for both. Two models with no thinking
configuration at all.

**Reasoning.** Three facts, all measured against the real key on September 5, 2026 rather
than reasoned about:

- **The 2.5 identifiers are dead for this key.** Both answer 404 with "no longer available
  to new users". They still appear in `models.list`, which is why listing models is not a
  test and a real call is.
- **The Pro tier is not on the plan.** `gemini-pro-latest` and `gemini-3.1-pro-preview`
  answer 429 with `limit: 0` — a quota of zero requests, not a spike. So the stronger-tier
  half of D11 is not a choice available to make.
- **Thinking level is worth more than the model choice here.** The same structured
  extraction call on a Gemini 3 Flash model took about 25 seconds at the default effort and
  about 2 at `low`. Requirement FR-26 asks for a first prose token within three seconds, so
  the fast path needs `low`; extraction is a background worker call whose errors are baked
  into the table, so it keeps the default.
- **Lite is not a cost choice, it is the latency choice.** On the same question with the
  same passages, `gemini-3.5-flash-lite` produced its first token in 0.68 to 0.85 seconds
  and `gemini-3.5-flash` in 8.8 to 9.8. FR-26's three seconds is not reachable on the
  larger model however the effort is configured, and the answers were equivalent on a
  two-passage citation question. Extraction keeps the larger model, where 15 seconds in a
  background worker costs nobody anything.
- **Free-tier daily caps are per model, and they are tiny.** `gemini-3.6-flash` allows 20
  requests **per day** on this key. So does `gemini-3.5-flash`:
  a single pass over the ten-document sample corpus spent all twenty and left the next run
  failing. Only the Lite models have room, which is why **both tiers are
  `gemini-3.5-flash-lite`**, a choice made by running the whole corpus through them rather
  than a single probe. Lite extracted all six
  sample invoices to the letter (D43), so the cost of the change is unmeasurable here and
  the benefit is a demo that runs twice.

**What this costs, stated plainly.** D11's reasoning for a stronger extraction tier was
sound and is unchanged; it simply cannot be acted on with this key. Extraction quality is
therefore whatever `gemini-3.5-flash` at default effort gives — on the invoice probe, nine
fields with verbatim quotes that all located in the source, which is the behaviour the
grounding stage needs. A paid key would want `LLM_EXTRACT_MODEL` pointed back at a Pro
model, which is a one-line change because model identifiers were kept as configuration.

**Cut.** Any automatic fallback from one model to another. A model that 404s or is not on
the plan is a configuration error the operator must see, and a provider that cannot be
constructed already fails loudly rather than degrading into heuristics.

---

## D43. The sample corpus is generated, and generated to be inconsistent

**Date:** September 6, 2026 · **Status:** Active, replaces the premise of the sample manifest

**Decision.** `samples/` holds ten documents written by `server/scripts/generate_samples.py`,
listed in `manifest.json`, with ground truth in `expected.json`. The generated files are
committed; the script exists so the corpus can be corrected rather than only replaced.

Six formats (Portable Document Format, Word, spreadsheet, comma-separated values, plain
text, and a scanned image), four document kinds (invoice, contract, policy, bank statement,
plus a reference table), and one two-page document. Six invoices across five vendors, three
of them with no purchase order.

**Alternatives considered.** Real documents, which is what the sample manifest assumed and what the project
originally intended. Downloading a public invoice dataset. Two or three documents rather
than ten.

**Reasoning.** Anubhav asked for the corpus to be created rather than supplied, so that
premise is simply gone. What replaces it has to earn the same trust real documents would,
and that means three properties:

- **It is inconsistent on purpose.** The same fact appears as "Total due", "Amount due",
  "Amount now due", "Balance due now" and "AMOUNT DUE"; the party sending the invoice is
  "Vendor", "Seller", "Vendor name" and "MERCHANT"; dates are written five ways. A corpus
  where every document agrees demonstrates nothing, because agreeing is the easy case.
- **Its arithmetic is consistent.** Line items sum to their subtotals, subtotals plus tax
  equal totals, and the generator asserts both before writing a file. It caught a real error
  on the first run: an invoice whose lines came to 4,197 under a stated subtotal of 4,200.
- **It has an answer key.** `expected.json` records every value, the totals by vendor, and
  which invoices lack a purchase order, so extraction can be checked against a stated truth
  instead of against whether the output looks plausible.

**Verified end to end on September 6, 2026.** Ten documents seed and process in 43 seconds.
Every invoice value matches `expected.json`. The five vocabularies unify into one
`vendor_name` and one `invoice_total`, so "total amount by vendor" returns Acme 8,024.00,
Initech 6,510.00, Globex 1,200.00, Umbrella 890.50, Hooli 128.40, and 16,752.90 in total,
which is what the answer key says. "How many invoices are missing a purchase order" returns
3. The contract and policy answer prose questions with located citations, and a question the
corpus cannot answer is refused.

**The uncomfortable part, stated plainly.** The vocabulary is varied but not arbitrary: each
variant was **measured** against the calibrated thresholds before being written into a
document, and phrasings that fail to unify were avoided on the two fields the headline demo
depends on. That is designing the corpus around a known weakness, and it is worth being
honest about. The weakness is D18's margin rule: "Supplier" resembles "Vendor" at 0.910 and
is vetoed because it also resembles "Purchase order" at 0.889, which is noise. Three real
merges are blocked this way. The alternative was a corpus whose headline total is wrong,
which teaches a reviewer something false about the product. The variety that remains is
real — five phrasings for the total, four for the vendor, five date formats — and the
secondary money fields (subtotal, tax, surcharge) are left un-engineered, so the ask
behaviour is still visible in the table.

**Cut.** Multiple currencies, which would make "total by vendor" a sum across incomparable
units and needs a product decision first. A ledger restating invoice amounts, which would
double-count them. More than ten documents: the tenth adds a format, the eleventh would only
add processing time.

---

## D44. The Upload screen is the document library, and the upload is the transient part

**Date:** September 6, 2026 · **Status:** Active, extends requirements section 3.1

**Decision.** `/w/{id}/upload` lists every document in the workspace: the format the server
actually parsed it as, its stage or failure reason, page count, size, and two actions — open
it in the source viewer, or delete it. The upload progress keeps its place above the list
while bytes are moving. `DocumentSummary` gains `source_format` so the list can say what a
file really is.

**Alternatives considered.** A fourth screen for files, which breaks the three-screen rule
that the whole product is organised around (D23). Putting the list on the Data screen beside
the table, where it would compete with the thing the table is for. Leaving it out: the Data
screen has a row per document, so the information is arguably reachable.

**Reasoning.** Anubhav asked where you look at the files you uploaded, and the honest answer
was nowhere. The screen behind the header's "Upload" tab was built for the seconds in which
bytes leave the browser, so arriving at it later — with ten documents indexed and the header
itself saying "10 documents" — produced one sentence, "this browser is not uploading
anything right now", and an empty page.

"Reachable from the Data screen" is the argument to reject. That table is a row per
*extracted record*, in the schema's vocabulary. A document that failed has no row at all, and
a document still being read has an incomplete one, so the two cases a person most wants to
look up are the two the table cannot show. A file list answers a different question — what
did I give this thing, and what became of it — and that question comes first, because the
table is only trustworthy to the extent its inputs are known.

Delete lands here for the same reason: requirement FR-07 has had a server route since the
first week and no way to reach it, and the place you notice a file that should not be in the
workspace is the list of files in the workspace.

**Three details worth stating.**

- **The format is the sniffed one, not the extension.** A `.csv` that is really a
  tab-separated export is exactly the case worth seeing, and the extension hides it.
- **Deleting asks twice, in place.** It cascades through the record, the passages and every
  citation pointing at them, with no undo. A second click on the same button is the whole
  ceremony; a modal would be heavier for the same guarantee.
- **The stage words are the processing strip's words.** One vocabulary for one set of
  states, so "pulling out values" does not become "extracting" on a different screen.

**Deleting writes through the cache.** Invalidating the workspace query is not enough: the
refetch returns the shorter list, but the deleted row stays on screen until a reload, which
reads exactly like the deletion having failed. The row is removed from the cached overview
directly, and the refetch follows for everything derived from it.

**Cut.** Re-extracting a document from here, though the route exists: re-extraction is
interesting after a correction, which happens on the Data screen, and putting it here would
invite re-running the pipeline on a whim. Renaming a document. Sorting and filtering the
list — at twenty-five files, the upload limit, scanning is faster than choosing a sort.

---

## D45. The MVP deployment: one container, one Postgres, nothing else

**Date:** September 6, 2026 · **Status:** Active, except the platform, which D46 changed
from Koyeb to Railway. Closes the gap left by implementation.md section 10

**Decision.** Deploy as a single Docker image on Koyeb's free tier, with a free Neon
Postgres behind it and no third service. Four pieces of work make that possible, all in this
change:

1. **The API serves the built interface** (`app/web.py`). One origin, no CORS, one thing to
   deploy. Requests under the API prefix stay API requests; everything else returns the
   single-page shell so a reload of `/w/{id}/data` works. Hashed assets are cached for a
   year, `index.html` never.
2. **Blobs live in Postgres** (`app/storage/postgres.py`, `blobs` table), selected by
   `STORAGE_BACKEND=postgres`. Local development keeps the directory. The store is built
   once per process rather than per request: a directory does not care, but a connection
   pool per request would exhaust a free tier's connection limit inside one page of the
   document viewer.
3. **A `Dockerfile`** at the repository root: Node builds the client, Python runs the
   application, Tesseract comes from apt, `samples/` is copied in, migrations run on start,
   one uvicorn worker.
4. **A `Makefile`**, which also closes the "no Makefile" gap the README has carried since
   the beginning.

**Alternatives considered.** Render, which sleeps after 15 minutes. Fly.io, which no longer
has a free tier. Cloud Run, which throttles the processor between requests. Object storage
on Cloudflare R2 instead of the database. Keeping `LocalStorage` and accepting an ephemeral
container disk.

**Reasoning.** The constraint that decides everything is D8 and D12: the document queue and
the event bus are in-process, so this deploys as exactly one instance of one process. That
removes every platform whose free tier is built around scaling to zero or scaling out, and
it makes "always on" worth more than raw speed. Koyeb's free instance is one service that
does not sleep, without a credit card.

**Blobs in the database is the interesting one**, because it is the choice a scaling plan
would not make. On a free tier the container's disk does not survive a redeploy, and
`LocalStorage` there would mean the originals and the page images disappearing while their
rows stayed behind: the table would keep showing values, and every attempt to trace one back
to its page would fail. That is the fourth non-negotiable in `CLAUDE.md` breaking silently,
which is worse than it breaking loudly. Putting the bytes in Postgres makes the container
stateless and leaves exactly one thing holding state. R2 is the better answer for a real
corpus and needs a third account and an S3 client; for an MVP measured in megabytes it is
ceremony.

The storage protocol was written for this in the first place: "one new class rather than a
search for every `open()` in the codebase". It took one class, one table, and one setting.

**What it costs, accepted knowingly.** 0.1 vCPU and 512 MB, so processing is slow and OCR
is the memory risk. 0.5 GB of database, page images included. No backups. All named in
`docs/deployment.md` section 6 rather than discovered.

**Cut.** Object storage. A separate worker process, which is the only one of these that is
not just money: it would mean moving the queue and the bus out of the process, and the
single-instance constraint is what pays to avoid that. Any autoscaling. A staging
environment.

---

## D46. Railway, and a connection string that does not need editing

**Date:** September 6, 2026 · **Status:** Active, supersedes the platform half of D45

**Decision.** Deploy to Railway: one service built from the repository's `Dockerfile`, one
Railway Postgres beside it in the same project, `DATABASE_URL` wired as
`${{Postgres.DATABASE_URL}}`. Three things came with it:

1. **`railway.json`**, so the builder, the health check path and the restart policy are in
   the repository rather than in a dashboard nobody can diff.
2. **`docker-entrypoint.sh`**, which retries the migration for about thirty seconds before
   giving up loudly.
3. **`DATABASE_URL` is normalised on the way in** (`app/config.py`): `postgres://` and
   `postgresql://` become `postgresql+asyncpg://`, `sslmode` becomes asyncpg's `ssl`, and
   `channel_binding` is dropped. `app/db/urls.py` translates back for the synchronous
   driver that blob storage uses.

**Alternatives considered.** Koyeb, which D45 chose. Instructing the reader to rewrite the
URL by hand. Using Railway's
public database URL to sidestep the private network's timing.

**Reasoning.** Koyeb is simply not available to us, and Railway is already connected to the
repository. It has no permanent free tier, which was Koyeb's whole appeal, but a trial credit
covers a demo period and the application is unchanged either way: the same image, the same
two variables.

**The URL rewrite is the part worth defending.** Every managed Postgres publishes a
connection string for the standard synchronous client, and this application talks asyncpg,
which needs a different scheme and rejects `sslmode` outright. Asking a person to edit a
pasted secret is asking for the single most likely deployment failure, and the one with the
worst diagnostics: it appears on the first connection, inside a container, as a driver error
with nothing pointing back at the paste. Doing it in a validator means `DATABASE_URL` can be
wired straight from the provider's own variable and the step cannot be got wrong.

TLS intent is translated rather than dropped, which is the detail that would otherwise bite:
deleting `sslmode=require` because asyncpg dislikes the spelling would silently stop
encrypting a connection the provider requires to be encrypted.

**The retry is not superstition either.** Railway's private network comes up shortly after
the container, and on a first deploy the database may still be starting, so the first
connection this process makes is the one most likely to fail for reasons unrelated to the
application. It gives up rather than starting anyway: a server running against an unmigrated
schema fails later, further from the cause, and looks like a bug in the product.

**Cut.** A staging environment. Any use of Railway's public database URL, which costs egress
for no benefit once the retry exists.


---

