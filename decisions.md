# Distill: Decision Log

Every technology chosen and every design decision made on this project is recorded here, in
the format the brief asks for: **decision**, **alternatives considered**, **reasoning**, and
**what was cut** or the accepted tradeoff.

Rules for this file:

- A decision that is not written here did not happen. Write the entry in the same change as
  the code that depends on it, never at the end of the project.
- A superseded entry is **never deleted**. It is marked superseded and links forward, so the
  reasoning trail stays intact.
- Every entry is dated. Where a decision could not be verified, the gap is stated rather
  than hidden.

Legend: **Active** the decision stands. **Re-affirmed** it was challenged and held.
**Superseded** it was replaced, see the forward link.

---

## D1. Frame the problem as unification and trust, not extraction

**Date:** September 2, 2026 · **Status:** Active

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

1. *Nothing in the chosen stack was installed on the development machine.* Python was system
   3.9.6 only, with no Postgres, no Tesseract, and no `uv`. Resolved by installing Python
   3.12.14, Postgres 16.15, Tesseract 5.5.3, and `uv` 0.12.9 through Homebrew. Cost about
   twenty minutes, so this objection did not survive contact with the facts.
2. *A Node backend would let one Zod schema per Agent-to-User Interface catalog component
   serve both sides.* This is a genuine loss. The backend now validates emitted messages
   against the protocol's JSON Schema while the client validates with Zod, so requirements
   A2-02 and A2-06 are enforced twice from two sources of truth. **Accepted, and mitigated**
   by generating the backend's component contracts from a single declarative table in
   `app/a2ui/catalog.py` and asserting message validity in tests, so a divergence fails the
   build rather than the demo.
3. *A Node backend extracting geometry with pdf.js would share a coordinate space with the
   pdf.js-based viewer by construction.* Also a genuine loss, and the sharper of the two.
   The provenance overlay now depends on pdfplumber and pdf.js agreeing about the coordinate
   origin, which is an assumption rather than an identity. **Accepted, and mitigated** by
   promoting it to the first checkpoint in the build: an executable test asserts the
   coordinate convention against a real PDF fixture before any overlay mathematics is
   written. See review finding 8.1 in `docs/backend-plan.md` and decision D17.

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

**Date:** September 2, 2026 · **Status:** Active

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

## D6. Agent-to-User Interface for query results and schema proposals only

**Date:** September 2, 2026 · **Status:** Active

**Decision.** Use the Agent-to-User Interface protocol (A2UI, Google's open protocol in
which an agent emits declarative JSON describing the interface it wants and the client
renders it from its own trusted component catalog) for two surfaces: query results and
schema proposal cards. Not for the rest of the application.

**Alternatives considered.** Hand-built result components behind a presentation-hint switch.
CopilotKit's renderer over the Agent-User Interaction protocol.

**Reasoning.** The genuine value is letting the agent choose the presentation when the right
shape depends on the content. Using the protocol everywhere would make the core data table
depend on a specification that has shipped breaking changes in three consecutive minor
releases. CopilotKit adds a runtime layer this project does not need.

**Accepted risk.** Renderer churn, mitigated by exact version pins, confining all protocol
knowledge to one frontend module, and a deterministic fallback renderer.

---

## D7. Server-Sent Events, not WebSockets

**Date:** September 2, 2026 · **Status:** Active

**Decision.** Server-Sent Events for all streaming.

**Reasoning.** The streaming is one-directional, which is all Server-Sent Events do.
Resumption after a dropped connection comes free through the `Last-Event-ID` header, and the
transport works through every proxy without upgrade negotiation.

**Cut.** Live cursors and multi-user presence.

---

## D8. Anonymous workspaces with a bearer token, no accounts

**Date:** September 2, 2026 · **Status:** Active

**Decision.** Each browser gets an anonymous workspace and a bearer token, stored locally and
encoded in a shareable link. No sign-up, no accounts.

**Reasoning.** Five day window, and authentication demonstrates nothing about this problem.

**Accepted risk.** Anyone with the link can see the workspace. Stated plainly in the
interface rather than left implicit.

---

## D9. In-process asyncio job queue, not Redis with a separate worker

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

## D10. Generated SQL is confined by four independent limits

**Date:** September 2, 2026 · **Status:** Active

**Decision.** Every generated query passes an `sqlglot` parse-level allow-list permitting a
single `SELECT` against this workspace's view only, gets `LIMIT 500` injected, and executes
through a Postgres role holding `SELECT` alone with a five second statement timeout.

**Reasoning.** The model writes the SQL, so assume it will eventually write something
dangerous. Four independent limits mean any single one failing is not a breach.

**Cut.** A user-editable SQL editor. Showing the generated SQL is in scope; letting a person
write their own is not.

---

## D11. styled-components with Radix Primitives, not Tailwind with shadcn/ui

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

## D12. `uv` for Python dependency and interpreter management

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

## D13. Gemini behind a provider protocol, with a fake provider as a first-class implementation

**Date:** September 3, 2026 · **Status:** Active, model identifiers unverified

**Decision.** Gemini is the intended Large Language Model provider: the Pro tier for
extraction and schema inference, the Flash tier for translating natural language into SQL.
Both sit behind an `LLMClient` protocol, selected by configuration, alongside a **fake
provider** that is a first-class implementation rather than a test double.

**Alternatives considered.** Calling a provider software development kit directly, which is
simpler but welds the project to one vendor. Claude, per the original implementation
document. Using the Flash tier throughout, or the Pro tier throughout.

**Reasoning.** Extraction and schema inference are the accuracy-critical calls and sit
exactly where the hard sub-problem lives, so they get the stronger tier. Translating a
question into SQL is short and tightly constrained, so the faster tier keeps the query
experience responsive, which matters because query latency is felt directly in the demo.

The provider is explicitly **not finalised** and no key exists yet. The protocol makes
switching a configuration change. The fake provider is what makes that acceptable rather
than reckless: the entire pipeline is buildable and testable today with no key and no
network, and the same fake is the recorded fixture that section 9 of the implementation
document requires for a deterministic end-to-end test.

**Accepted gap, stated rather than hidden.** Real Gemini call quality, current model
identifiers, and Instructor's Gemini client signature cannot be verified without a key. None
of them block any other work. When a key arrives, the fake's record mode captures real
interactions and the existing tests run unchanged against them.

---

## D14. The Server-Sent Events log is a database table, not in-memory state

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

## D15. Sample documents are discovered through a manifest

**Date:** September 3, 2026 · **Status:** Active

**Decision.** The seed route reads `samples/manifest.json` and loads whatever it lists,
rather than referencing hard-coded filenames.

**Alternatives considered.** Generating a synthetic sample set. Hard-coding the filenames of
a fixed set.

**Reasoning.** Anubhav is supplying real documents, which are more convincing to a reviewer
than synthetic ones. A manifest means dropping files into `samples/` is the only step
required, and it keeps the expected-extraction fixtures beside the documents they describe.

**Accepted risk.** Real documents are not guaranteed to trigger a schema drift proposal,
which is the centrepiece of the demo. Mitigation: once the real set arrives, verify that at
least one document disagrees with the others about field naming, and if none does, add one
synthetic document whose only job is to trigger drift.

---

## D16. `field_values` retains the disagreeing model value beside the human one

**Date:** September 3, 2026 · **Status:** Active

**Decision.** `field_values` carries `model_value` and `model_value_at` in addition to
`value`. A human-verified value stays in `value`, and a later re-extraction that disagrees
records its result in `model_value` and sets the tier to conflict.

**Alternatives considered.** A single `value` column, per section 4 of the implementation
document, with the conflict recorded as a boolean flag.

**Reasoning.** Requirement FR-34 says re-extraction may add a "model now disagrees" flag. A
flag alone loses *what* the model said, so the interface could tell the user a disagreement
exists but not show them the two candidates, which makes the flag unactionable. Keeping both
values is what turns a conflict from a warning into a decision the user can make.

**Cut.** Full version history of every value. Only the current human value and the most
recent disagreeing model value are retained, which is enough to resolve a conflict and far
cheaper than an audit table.

---

## D17. The pdfplumber coordinate convention is asserted before any overlay is written

**Date:** September 3, 2026 · **Status:** Active

**Decision.** The first executable test in the project asserts, against a real PDF fixture,
where pdfplumber places its coordinate origin and how its point dimensions relate to the
pixel dimensions of a pypdfium2 render.

**Alternatives considered.** Writing the overlay mathematics against the assumption stated in
section 8.3 of the implementation document, that pdfplumber already flips the bottom-left
origin the PDF format uses, and correcting it if highlights appeared in the wrong place.

**Reasoning.** This assumption is load-bearing for the entire provenance feature, which is
the product's central trust claim, and it is shared across two codebases that must agree.
Discovering it is wrong after both the backend geometry and the frontend overlay exist means
debugging a visual symptom across a language boundary. Discovering it in a test that runs in
one second costs nothing. This is also the sharpest cost of choosing Python over Node, as
recorded in D2, so it is the cost that deserves the check.

**Cut.** Nothing. This adds a test.

---

## D18. One provenance shape for every format, by rendering every format to a page

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

## D19. A flat extraction response shape, with every value sent as text

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

## D20. Call google-genai directly, not through Instructor

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

## D21. Unambiguous reformatting does not reduce a confidence tier

**Date:** September 3, 2026 · **Status:** Active

**Decision.** Tier ceilings are applied when the system made a **judgement**, not when it
merely reformatted. Recognising a currency symbol, dropping thousands separators, and
reading `14 March 2026` as an ISO date leave the tier untouched. Reading `03/04/2026` as
day-before-month, or assuming a currency for an unlabelled amount, cap the tier at low.

**Alternatives considered.** Treating every normalisation as a reason to reduce the tier,
which is how the table in implementation.md section 6.4 could be read.

**Reasoning.** Capping on reformatting would put essentially every real invoice amount and
date into the medium tier, because that is how invoices are written. The high tier would
become unreachable for precisely the field types that matter most, and the review queue
would fill with values nobody needs to check, which is how a review queue gets ignored. A
tier only means something if it is sometimes clean.

Capping on judgement is the opposite trade and the right one. An ambiguous date order is a
coin flip on a value a finance operations person is accountable for. It costs the user one
glance to confirm and it buys correctness.

Note that the implementation document's own example for its "minor normalisation" row is
"date format inferred", which is a judgement in this taxonomy rather than a reformatting, so
this is closer to that document's intent than to a departure from it.

**Cut.** Nothing. This is a threshold choice, recorded because it materially changes what
the user sees in the review queue.

## D22. Single repository for client and server, not separate repos

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

## D23. Confidence-gated auto-apply for schema changes, not review-every-field

**Date:** September 4, 2026 · **Status:** Active

**Decision.** A schema change only blocks on a user decision when the model is genuinely
uncertain. Concretely, when a document's fields are compared against the current schema:

- an **unambiguous match** to exactly one existing field, type-compatible → auto-mapped, no
  prompt.
- **clearly novel** against every existing field → auto-added as a new field, no prompt.
- **everything in between** — a plausible-but-uncertain match, several close candidates, or
  a type mismatch — produces the `SchemaProposal` card (map to existing / add as new /
  ignore) exactly as originally specced.

How "unambiguous" and "clearly novel" are computed is **decision D24**. This entry owns the
policy (when the user is asked); D24 owns the signal (how similarity is measured). The
thresholds originally written here assumed embedding cosine similarity alone and were
replaced by D24's hybrid rule the same day, before any of it was implemented.

The very first schema is always applied without blocking. It is not, however, free of
ambiguity — see decision D25, which corrects an error in the first version of this entry.

Every path, automatic or user-decided, writes a `schema_versions` row and a `schema.version`
event, so schema history and one-click revert (FR-15) cover 100% of changes regardless of
which path produced them.

**Two consequences, resolved September 4, 2026 during implementation review.**

*An auto-applied change does not write a `proposals` row.* `schema_versions` is the complete
log of what happened to the schema; `proposals` stays strictly "questions that needed a
human." Collapsing both into one table would make "how many decisions are outstanding" a
filtered count rather than a row count, and the history view already reads from
`schema_versions`, which carries `created_by` and `change_summary` for exactly this purpose.

*An auto-added field enqueues backfill automatically, without offering.* FR-14 says adding a
field "offers" backfill, and that stays true for a field the **user** added — they are
present, mid-decision, and the offer has somewhere to attach. An auto-added field has no such
moment by construction: the entire point is that nothing interrupted the user. Since backfill
only ever adds values and never touches `human_verified` rows, and its progress is visible
and cancelable through `backfill.progress`, running it is the behavior that matches what the
user would have said anyway.

**Alternatives considered.**

1. *Review every field, every time* (the original spec). Maximizes safety, costs a click per
   field on every document, including cases with only one sane interpretation.
2. *Full auto-trust: apply every schema change silently, no proposal card at all, ever.*
   Fastest, but removes the review step even for genuinely ambiguous cases — a coin-flip
   match between two candidate fields would get resolved by the model with no human in the
   loop, which is exactly the silent-wrong-merge failure mode section 1.3 of
   `requirements.md` exists to prevent. Also guts a demo step the evaluation criteria
   name explicitly (section 9, "proposal cards instead of silent schema changes").

**Reasoning.** The original always-review design conflated two different situations under
one UI: "there is one obvious answer" and "there is a real judgment call." Those deserve
different amounts of friction. Gating on confidence keeps the review loop exactly where it
earns its keep — the cases where a wrong auto-decision would actually cost the user
something (a real ambiguous rename, a type mismatch) — while removing it from the cases
where it was pure tax (a 98%-confidence field match, or the very first schema with nothing
to disagree with yet).

This does not weaken CLAUDE.md's non-negotiable #3 ("a review loop the user can trust"). It
changes what "reviewable" means: instead of every change requiring a click *before* it
applies, every change (automatic or not) is inspectable and reversible *after* it applies,
via schema history. Reversibility, not a confirmation click, is the trust mechanism for the
auto-apply zones. The originally-specced review-every-field behavior is fully preserved for
the zone that actually needs it.

**Cut.** A blanket "no review step, ever" design (alternative 2). The thresholds in D24 are
a first pass, not tuned against real data; if the sample corpus shows them producing wrong
auto-applies, they should move, not the mechanism.

## D24. Field similarity is string similarity OR embedding similarity, with a margin rule

**Date:** September 4, 2026 · **Status:** Active

**Decision.** Drift matching scores a candidate field against each existing field with two
independent signals, and gates D23's auto-apply zones on them as follows.

*Auto-map* requires **all three** of:

1. any one of — normalized-exact or known-alias match (case, separators, and
   `FieldSpec.source_keys` folded); **or** string similarity ≥ 0.90; **or** embedding
   cosine ≥ 0.95;
2. the best candidate beats the runner-up by ≥ 0.05 on whichever signal fired;
3. type compatibility.

*Auto-add as new* requires `max(string, embedding) < 0.30` against **every** existing field.

Everything else produces the proposal card. The cheap string pass runs first, so a label
that is identical after normalization never spends an embedding call.

**Alternatives considered.**

1. *Embeddings only* (as implementation.md section 6.5 originally read). Handles synonyms,
   but needs a network call for even `vendor_name` versus `Vendor Name`, and leaves the
   fake provider — which must work with no API key, per D13 — with nothing to score with.
2. *String similarity only.* Free, deterministic, offline, and already half-built in
   `app/llm/fake.py` (`LABEL_MATCH_THRESHOLD`, `difflib.SequenceMatcher`). But it scores
   `Supplier` against `vendor_name` at roughly 0.2, so it fails on precisely the renames
   drift detection exists to catch. Every synonym would become a proposal card, which is
   the tedium D23 set out to remove.
3. *A single weighted blend*, `w1 * string + w2 * embedding`. Rejected because averaging
   destroys the signal: a true synonym scores near-zero on string and high on embedding, and
   the blend lands it in the ambiguous band where it needs a card. The two signals are
   evidence of different things and should not be averaged.
4. *A strict AND of both signals.* Safest against false positives, but it cannot ever
   auto-map a synonym, since a synonym fails the string test by definition. That is
   alternative 2 with extra steps.

**Reasoning.** The two signals fail on disjoint cases, which is what makes OR the right
combinator rather than AND or a blend: string similarity catches formatting and typo
variants that embeddings waste a call on, embeddings catch semantic renames that string
matching cannot see at all. Requiring either to fire, rather than both, is what lets both
classes of obvious match skip the card.

The margin rule is what keeps OR from being reckless. A high absolute score is not evidence
of an unambiguous match when a second field scores nearly as high — `Supplier` at 0.96 to
`vendor_name` and 0.94 to `supplier_id` is a genuine judgment call, and the margin test is
what routes it to a human instead of a coin flip. This is the same instinct as D5: the
useful question is rarely "how confident is the score," it is "is there a competing answer."

Novelty inverts the combinator deliberately. Declaring a field *new* is a claim about the
absence of a match, so both signals have to agree nothing resembles it; if either sees a
resemblance, it is not clearly novel and the user decides.

**Test and no-key behavior.** `LLMClient` gains `embed()`. `GeminiClient` calls the real
embeddings endpoint — the assumption for actual usage is a working API key, per D13, and
this decision is not designed around the model being unavailable in production. `FakeClient`
replays recorded vectors keyed the same content-derived way its other fixtures are, which is
what keeps the test suite and a no-key reviewer clone deterministic and network-free; that
is D13's concern, not a production fallback. If a live call genuinely fails (network error,
rate limit), that is handled by the existing `LLMUnavailable`/retry path in `app/llm/base.py`
like any other model call — it is a failure to surface and retry, not a silent
degrade-to-string-only mode.

**Cut.** A locally-hosted embedding model, on exactly the grounds D3 rejected Docling: a
multi-gigabyte dependency defeats the one-command setup. Also cut: tuning either threshold
before the sample corpus exists to tune against.

**Accepted cost.** Roughly half a day — the protocol method, the Gemini implementation,
recorded fixtures for the sample corpus, a label-keyed cache so a schema's labels are not
re-embedded once per document, and the two thresholds in configuration.

## D25. The first batch can be ambiguous with itself; uncertain unification stays split

**Date:** September 4, 2026 · **Status:** Active

**Decision.** D23 originally justified auto-applying the initial schema on the grounds that
"there is nothing to conflict with." That is wrong, and this entry corrects it. The first
batch conflicts with *itself*: eight documents can yield `vendor_name` from five of them,
`Supplier` from two, and `Vendor` from one, and deciding those are one field is exactly the
judgment call D23 says a human should make when the model is unsure.

So:

1. **The initial schema always applies immediately and never blocks.** The 60-second
   first-run in the acceptance criteria depends on this, and a user with no schema at all is
   better served by the model's best guess than by a modal.
2. **Unification within the batch is gated by D24's rule.** Source keys that unify
   confidently are merged into one canonical field, which is the demo path and the common
   case. Source keys the rule finds *uncertain* are **left as separate fields**, and a
   `initial_schema` proposal is queued asking whether to merge them.
3. **The queued proposal is non-blocking.** The table is already populated and usable; the
   card is a question waiting in the review surface, not a gate.

`Proposal.kind = 'initial_schema'` therefore stays alive rather than being removed as dead,
which was the other option considered during implementation review.

**Alternatives considered.**

1. *Remove `initial_schema` entirely* — the reading that produced D23's original wording.
   Rejected because it does not eliminate intra-batch ambiguity, it just resolves it silently
   in the model's favour, which is the failure mode D23 exists to prevent.
2. *Merge on uncertainty, then offer to split.* Rejected on asymmetry of harm: a wrong merge
   commingles two genuinely different fields' values under one column, and unpicking it means
   knowing which source key produced each value. A wrong split leaves two clean columns and a
   merge is a cheap, lossless move of values from one to the other. When unsure, prefer the
   error that is cheaper to undo.
3. *Block the first run on a schema confirmation.* Rejected outright: it breaks acceptance
   criterion 1 and re-introduces exactly the friction D23 removed.

**Reasoning.** The asymmetry in alternative 2 is the whole argument. Both directions are
recoverable in principle, but merge-then-split requires reconstructing provenance for values
that have already been pooled, while split-then-merge is a move. Defaulting to the cheaper
undo is what lets the system be aggressive about auto-applying elsewhere.

The demo is not at risk from this. `vendor_name` versus `Supplier` is a strong semantic match
and clears D24's embedding bar comfortably, so it merges automatically and the unified-table
moment still lands. Only genuinely marginal pairs stay split, and those come with a card
explaining why.

**Consequence for requirements.** FR-16 ("manually merge two fields into one") moves from
**Could** to **Should**. It stops being a convenience and becomes the resolution path for
every uncertain unification this decision produces.

**Cut.** A field-splitting operation. Not needed, because this decision never auto-merges
under uncertainty, so there is nothing to split back apart.

## D26. A configured Gemini provider that cannot be built is a hard failure

**Date:** September 4, 2026 · **Status:** Active

**Decision.** `app/llm/registry.build_client` no longer catches a `GeminiClient`
construction failure and return `FakeClient` in its place. With `LLM_PROVIDER=gemini`, a
provider that cannot be constructed raises and the server does not start. The offline
provider remains fully supported and is still the default; it is reached by asking for it
with `LLM_PROVIDER=fake`.

**Alternatives considered.** The original behaviour, recorded in that function's own
docstring: fall back to the offline provider and log loudly, on the reasoning that a missing
key should degrade a deployment rather than take the whole interface down.

**Reasoning.** The original argument treats the fake provider as a degraded version of the
real one. It is not — it is a *different* provider that synthesises values from
label-and-value heuristics, and those values flow downstream wearing exactly the same
confidence tiers and provenance links as real extraction. There is no point after that where
the interface, or the user, can tell the difference. An operator who set a key and mistyped
the model name would get a running system quietly presenting heuristic guesses as model
output, in a product whose entire claim is that every value on screen can be trusted and
traced back. A server that refuses to start is a five-minute problem with an obvious cause.
A server serving heuristics as extraction is a credibility problem that surfaces during the
demo, if at all.

Noted while implementing this: the common case never reached that fallback anyway. `Settings`
already rejects `LLM_PROVIDER=gemini` with no `GEMINI_API_KEY` at configuration time, so the
missing-key path fails before a client is built. What the fallback actually covered was the
rarer construction failure — a broken software development kit import, or a client
constructor that throws — which is precisely the class of failure an operator is least likely
to have anticipated, and so the worst one to swallow.

This follows the standing direction not to design production behaviour around the model being
unavailable. A real key is the assumption for real usage; a failure to reach the provider is
an incident to surface, not a mode to accommodate.

**Cut.** Nothing the offline provider could previously do. `LLM_PROVIDER=fake` still runs the
entire pipeline with no key and no network, which is what D13 asked for.

---

## D27. The novelty ceiling is per signal, and the string value is measured not guessed

**Date:** September 4, 2026 · **Status:** Active, refines decision D24

**Decision.** Decision D24's single novelty test, `max(string, embedding) < 0.30` against
every existing field, becomes two tests against two separately configured ceilings:

```
string_similarity  < 0.65   (measured)
embedding_cosine   < 0.30   (unmeasured, needs a live model)
```

against **every** existing field. The "both signals must agree nothing resembles it"
structure that D24 chose deliberately is unchanged; only the calibration is.

Decision D24's string signal also moves from the filler-word fold to the
case-and-separator fold (`fold_label`). That is a correctness fix, not a tuning change, and
it is the more serious half of this entry.

**Why the shared ceiling was wrong.** A character ratio and a cosine are not comparable
numbers, so holding them to one threshold is a category error. Measured across the fixture
corpus, the highest string similarity between two genuinely different field labels is
**0.59** (`Currency` versus `Reference`), with `Invoice No` versus `Vendor` at 0.50 and a
p90 of 0.38. Every candidate field therefore exceeded
a 0.30 ceiling against something, no field was ever "clearly novel", and **the auto-add zone
was unreachable** — a third of D23's design was silently not implemented.

**Why the string fold was wrong, which matters more.** The filler-word fold drops "id",
"number", and "reference", which scores `Supplier` against `Supplier ID` at **1.00**. At
1.00 that clears D24's 0.90 auto-map bar, so a company name would have been silently merged
into an identifier column, with no card and no user involvement. That pair is almost word
for word D24's own example of a case that must go to a human. On the case-and-separator fold
it scores 0.84, lands below the bar, and asks. The lossy fold remains in use only by the
offline provider's loose value matching, where a wrong match surfaces as a visible,
correctable value in a cell rather than as a schema change.

**What the measurement also showed, and what it implies.** String similarity cannot separate
same-field from different-field pairs in this corpus at all. `Supplier` versus `Vendor`
scores 0.29 and `Amount` versus `Total Due` scores 0.27, both **below** the 0.59 that two
unrelated labels reach. This is direct evidence for D24's core claim that the two signals
are evidence of different things and must not be averaged: on renames, the string signal is
not weak, it is actively misleading. Embeddings are doing all the semantic work, and the
string signal's only honest job is catching formatting and typo variants, which is exactly
the 0.90-and-above band it is now confined to.

**Alternatives considered.**

1. *Raise the single shared ceiling to 0.65.* Rejected: it would loosen the embedding half
   at the same time, and 0.65 on a cosine is close to where genuinely related terms sit, so
   it would start auto-adding fields that should have been mapped.
2. *Replace the string metric with word-level overlap for the novelty test only.* Rejected
   as a second metric to reason about and test, when a per-signal ceiling achieves the same
   separation with a number.
3. *Leave 0.30 and accept that auto-add never fires.* Rejected as shipping a dead code path
   while D23 claims three zones. Better to have the zone work and the threshold be honest
   about needing calibration.

**Cut.** Nothing. Both mechanisms are unchanged; the numbers and one fold moved.

**Outstanding, and it needs a key.** `drift_novelty_ceiling_embedding` is the only threshold
in the system still set by assertion rather than measurement. Real text embeddings score
unrelated business terms at roughly 0.4 to 0.7, so 0.30 is probably too strict and auto-add
may stay rare until it is calibrated. Erring strict costs extra proposal cards and never a
wrong merge, so the direction is safe, but this should be measured the day a key exists:
embed every field label in the corpus, take the cosine distribution over pairs a human calls
different, and set the ceiling above its upper range.

---

## D28. An "ask" carries a reason code, and callers act on it differently

**Date:** September 4, 2026 · **Status:** Active, refines decision D23

**Decision.** `classify` returns an `AskReason` alongside the `ASK` outcome:
`COMPETING_CANDIDATES`, `BORDERLINE`, `TYPE_MISMATCH`, or `UNCONFIRMED_NOVELTY`. The
initial-schema proposer raises a merge question only for the first three. Drift assessment
treats all four as questions.

**Why this is not cosmetic.** Decision D24 makes a missing embedding block auto-add, on the
sound reasoning that novelty is a claim about absence and string similarity alone cannot
support it. But "nothing resembles this and we could not confirm it" is a completely
different situation from "two fields both plausibly match", and collapsing them into a bare
`ASK` produced a real failure: unifying the fixture batch with no recorded vectors generated
a merge question for **13 of 14 fields**, pairing unrelated things like `vendor` with
`invoice_no`. Those are not judgment calls, they are the best of a bad lot, and asking about
them is worse than useless. It would also have broken acceptance criterion 1, since a first
run that opens with thirteen cards is not a populated table in sixty seconds.

The asymmetry is that the two callers face different risks. For **drift**, against an
established schema, a wrong auto-add creates a duplicate column holding half the values, so
refusing to guess is right. For **initial unification**, every observation becomes a field
regardless, so there is no duplicate-column risk and "resembles nothing" simply means "its
own field". With the reason code, the same signal serves both correctly. After the fix the
batch produces exactly one question, `Invoice No` versus `Invoice Number` at 75%, which is
the one genuine judgment call in it.

**Alternatives considered.** Lowering the novelty bar during initial unification, which
would have fixed the symptom by making the gate less safe everywhere it is also used.
Suppressing questions below a score threshold in the proposer, which is the same thing with
a magic number instead of a name.

**Cut.** Nothing.

---

## D29. Background work is queued after the transaction commits, never inside it

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
