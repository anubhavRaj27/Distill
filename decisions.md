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

**Date:** September 2, 2026 · **Status:** Superseded September 4, 2026 by D34. The trust
half stands; the unification-with-a-review-loop half is withdrawn.

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

**Date:** September 2, 2026 · **Status:** Partly superseded September 4, 2026 by D35. The
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

## D6. Agent-to-User Interface for query results and schema proposals only

**Date:** September 2, 2026 · **Status:** Superseded September 4, 2026 by D39. A2UI now
serves chat visuals and dashboard panels; schema proposals no longer exist.

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

**Date:** September 2, 2026 · **Status:** Superseded September 4, 2026 by D35. No SQL is
generated any more, so there is nothing to confine.

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

**Date:** September 3, 2026 · **Status:** Active, model identifiers unverified. Amended
September 4, 2026 by D35: the Flash tier now serves chat answers, dashboard planning, and
suggested questions rather than natural language to SQL, which no longer exists.

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
flag alone loses _what_ the model said, so the interface could tell the user a disagreement
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

**Date:** September 4, 2026 · **Status:** Superseded September 4, 2026 by D38. The two
auto-apply zones stand; the third zone no longer produces a card.

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

_An auto-applied change does not write a `proposals` row._ `schema_versions` is the complete
log of what happened to the schema; `proposals` stays strictly "questions that needed a
human." Collapsing both into one table would make "how many decisions are outstanding" a
filtered count rather than a row count, and the history view already reads from
`schema_versions`, which carries `created_by` and `change_summary` for exactly this purpose.

_An auto-added field enqueues backfill automatically, without offering._ FR-14 says adding a
field "offers" backfill, and that stays true for a field the **user** added — they are
present, mid-decision, and the offer has somewhere to attach. An auto-added field has no such
moment by construction: the entire point is that nothing interrupted the user. Since backfill
only ever adds values and never touches `human_verified` rows, and its progress is visible
and cancelable through `backfill.progress`, running it is the behavior that matches what the
user would have said anyway.

**Alternatives considered.**

1. _Review every field, every time_ (the original spec). Maximizes safety, costs a click per
   field on every document, including cases with only one sane interpretation.
2. _Full auto-trust: apply every schema change silently, no proposal card at all, ever._
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
changes what "reviewable" means: instead of every change requiring a click _before_ it
applies, every change (automatic or not) is inspectable and reversible _after_ it applies,
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

_Auto-map_ requires **all three** of:

1. any one of — normalized-exact or known-alias match (case, separators, and
   `FieldSpec.source_keys` folded); **or** string similarity ≥ 0.90; **or** embedding
   cosine ≥ 0.95;
2. the best candidate beats the runner-up by ≥ 0.05 on whichever signal fired;
3. type compatibility.

_Auto-add as new_ requires `max(string, embedding) < 0.30` against **every** existing field.

Everything else produces the proposal card. The cheap string pass runs first, so a label
that is identical after normalization never spends an embedding call.

**Alternatives considered.**

1. _Embeddings only_ (as implementation.md section 6.5 originally read). Handles synonyms,
   but needs a network call for even `vendor_name` versus `Vendor Name`, and leaves the
   fake provider — which must work with no API key, per D13 — with nothing to score with.
2. _String similarity only._ Free, deterministic, offline, and already half-built in
   `app/llm/fake.py` (`LABEL_MATCH_THRESHOLD`, `difflib.SequenceMatcher`). But it scores
   `Supplier` against `vendor_name` at roughly 0.2, so it fails on precisely the renames
   drift detection exists to catch. Every synonym would become a proposal card, which is
   the tedium D23 set out to remove.
3. _A single weighted blend_, `w1 * string + w2 * embedding`. Rejected because averaging
   destroys the signal: a true synonym scores near-zero on string and high on embedding, and
   the blend lands it in the ambiguous band where it needs a card. The two signals are
   evidence of different things and should not be averaged.
4. _A strict AND of both signals._ Safest against false positives, but it cannot ever
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

Novelty inverts the combinator deliberately. Declaring a field _new_ is a claim about the
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

**Date:** September 4, 2026 · **Status:** Superseded September 4, 2026 by D38. "Stays
split" stands and is now the whole answer; the queued merge question is withdrawn.

**Decision.** D23 originally justified auto-applying the initial schema on the grounds that
"there is nothing to conflict with." That is wrong, and this entry corrects it. The first
batch conflicts with _itself_: eight documents can yield `vendor_name` from five of them,
`Supplier` from two, and `Vendor` from one, and deciding those are one field is exactly the
judgment call D23 says a human should make when the model is unsure.

So:

1. **The initial schema always applies immediately and never blocks.** The 60-second
   first-run in the acceptance criteria depends on this, and a user with no schema at all is
   better served by the model's best guess than by a modal.
2. **Unification within the batch is gated by D24's rule.** Source keys that unify
   confidently are merged into one canonical field, which is the demo path and the common
   case. Source keys the rule finds _uncertain_ are **left as separate fields**, and a
   `initial_schema` proposal is queued asking whether to merge them.
3. **The queued proposal is non-blocking.** The table is already populated and usable; the
   card is a question waiting in the review surface, not a gate.

`Proposal.kind = 'initial_schema'` therefore stays alive rather than being removed as dead,
which was the other option considered during implementation review.

**Alternatives considered.**

1. _Remove `initial_schema` entirely_ — the reading that produced D23's original wording.
   Rejected because it does not eliminate intra-batch ambiguity, it just resolves it silently
   in the model's favour, which is the failure mode D23 exists to prevent.
2. _Merge on uncertainty, then offer to split._ Rejected on asymmetry of harm: a wrong merge
   commingles two genuinely different fields' values under one column, and unpicking it means
   knowing which source key produced each value. A wrong split leaves two clean columns and a
   merge is a cheap, lossless move of values from one to the other. When unsure, prefer the
   error that is cheaper to undo.
3. _Block the first run on a schema confirmation._ Rejected outright: it breaks acceptance
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
real one. It is not — it is a _different_ provider that synthesises values from
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

1. _Raise the single shared ceiling to 0.65._ Rejected: it would loosen the embedding half
   at the same time, and 0.65 on a cosine is close to where genuinely related terms sit, so
   it would start auto-adding fields that should have been mapped.
2. _Replace the string metric with word-level overlap for the novelty test only._ Rejected
   as a second metric to reason about and test, when a per-signal ceiling achieves the same
   separation with a number.
3. _Leave 0.30 and accept that auto-add never fires._ Rejected as shipping a dead code path
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

**Date:** September 4, 2026 · **Status:** Superseded September 4, 2026 by D38. The reason
code survives as the text of `change_summary`; nobody is asked anything.

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

---

## D30. React Router in declarative mode for the interface, not a type-generated router

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
token is deliberately not in the URL query at all (decision D31). Buying a route-generation
build step to type two parameters is a poor trade in a five-day build. Framework mode brings
loaders and a data layer that would duplicate TanStack Query, which already owns server
state. Doing without a router entirely was rejected because a shared workspace link has to
be a real URL that survives a reload.

**Cut.** Typed route parameters, which are asserted at the one call site that reads them
instead. Route-level code splitting, which is not needed until the A2UI chunk arrives; that
is lazy-loaded on its own rather than per route.

---

## D31. The workspace token travels in the URL fragment, never the query string

**Date:** September 4, 2026 · **Status:** Active

**Decision.** A shareable workspace link is `/w/{id}#t={token}`. On arrival the fragment is
read once, written to `localStorage`, and stripped from the address bar with
`history.replaceState`. In-application navigation carries no token at all, because storage
already has it.

**Alternatives considered.** A query parameter, `/w/{id}?t={token}`, which is the obvious
reading of "the token is encoded in a shareable URL" in requirement FR-01. A token in the
path. Storage only, with no shareable link, which would have contradicted FR-01.

**Reasoning.** Decision D8 accepts that anyone holding the link holds the workspace; that
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

## D32. A warm-paper visual language, rebuilt in styled-components rather than adopted as Tailwind

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
decision D11 by the back door. Loading the design's intended webfonts from Google Fonts.
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

## D33. Client scaffold taken as `create-vite` ships it, with the codegen tool kept out of the dependency graph

**Date:** September 4, 2026 · **Status:** Active

**Decision.** Keep what `create-vite` scaffolded — Vite 8.2, React 19.2.8, TypeScript 6.0.3,
oxlint — and add `strict` plus `noUncheckedIndexedAccess` to the TypeScript configuration.
Do **not** declare `openapi-typescript` as a dependency: invoke it pinned through `npx` in
the `api:types` script and commit its output.

**Alternatives considered.** Downgrading the project to TypeScript 5.9 so
`openapi-typescript` installs cleanly. Setting `legacy-peer-deps=true` in `.npmrc`. An npm
`overrides` entry narrowing the tool's peer range. Replacing oxlint with ESLint to match the
wider ecosystem.

**Reasoning.** This settles two items on the day-1 checklist in implementation.md section 13,
and the answer to one of them is no.

`openapi-typescript@7.13.0` peer-depends on `typescript@^5.x` and therefore does **not**
install alongside the scaffolded TypeScript 6 without a flag. Downgrading the whole project's
language to satisfy one code generator is the wrong direction. `legacy-peer-deps` in
`.npmrc` was rejected outright, because the Zod 3 peer range from `@a2ui/react` is
load-bearing (CLAUDE.md, and requirement A2-01) and must keep failing loudly if it is ever
violated — switching off peer checking globally to fix an unrelated tool would disarm the
one check this project most needs. An `overrides` entry was tried and crashed npm 10.9.2
outright with `Cannot read properties of null (reading 'edgesOut')`.

What is left is the observation that a code generator is not a dependency of the application.
`schema.d.ts` is committed, so a fresh checkout builds, tests, and runs without the tool
present. Only someone regenerating the client after a backend change needs it, and they get
a pinned version on demand.

A related npm failure is worth recording because it will recur: `npm install vitest@4` also
crashes the same npm with the same arborist error, over Vitest 4's optional browser-mode
peers. It was installed with `--legacy-peer-deps` **as a one-off command**, which does not
persist into configuration; the committed lockfile makes the result reproducible, since
`npm ci` resolves from the lock rather than re-running the solver.

**Cut.** ESLint, and with it the shared configuration ecosystem — oxlint was already wired
up by the scaffold and is enough for one lint rule set on a five-day build. Reversal is a
day-5 decision at worst, not a foundational one.

**Accepted risk.** `npm install <new package>` may hit the same arborist crash again. The
workaround is known and recorded here rather than rediscovered.

---

## D34. Product pivot: three screens, chat first, no schema review loop

**Date:** September 4, 2026 · **Status:** Active. Supersedes D1 in part and sets the frame
for D35 through D43.

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

## D35. Retrieval over the documents replaces natural language to SQL

**Date:** September 4, 2026 · **Status:** Active. Supersedes D10 and the view half of D4.
Amends D13.

**Decision.** Questions are answered by retrieval-augmented generation (RAG): the question
is embedded, the most similar passages of document text are found by cosine similarity, and
the model answers **only from those passages plus the extracted records**, citing each claim.
When an answer needs a number, the model emits a query specification that the server
evaluates over `field_values` in Python (see D37). No SQL is generated anywhere.

**Alternatives considered.**

1. _Natural language to SQL over a typed per-workspace view_ (v1, D4 and D10). Precise for
   aggregate questions the schema anticipated; blind to everything the schema did not
   capture, which for a contract or a policy document is nearly all of it.
2. _Both: SQL for structured questions, retrieval for the rest, with a router._ The most
   capable option and the most expensive: two query paths, two failure modes, a classifier
   in front, and the four-limit SQL guard still to build and test. Rejected on the remaining
   time.
3. _Retrieval only, with the model computing aggregates from retrieved rows._ Rejected
   because it violates the data-binding rule in D37: a model summing numbers in prose is
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

## D36. Vectors stored as JSONB arrays with in-process cosine, not pgvector

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

## D37. Displayed numbers are computed by the server and bound by path; the model never types them

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
3. _Model writes SQL._ D35.

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

## D38. Uncertain schema drift resolves to a separate field, silently

**Date:** September 4, 2026 · **Status:** Active. Supersedes D23, D25, D28. Narrows D24
and D27, which remain the signals for the auto-map and auto-add zones.

**Decision.** When a new document's field cannot be confidently matched to an existing field
or confidently declared novel, the system **adds it as a separate field** and records why in
`schema_versions.change_summary`. No proposal card, no queued question, no history view. The
user's recourse is a column menu on the Data screen: rename, or "merge into" another field,
which moves values and provenance and is lossless.

**Alternatives considered.**

1. _Proposal cards_ (D23, D25, D28). Fully designed, partly built. Withdrawn with the review
   loop in D34.
2. _Merge on uncertainty._ Rejected on the same asymmetry D25 recorded: a wrong merge pools
   values from two different fields under one column and unpicking it means knowing which
   source key produced each value; a wrong split is two clean columns and a merge is a move.
   When unsure, prefer the error that is cheaper to undo.
3. _Let the model decide with a coin flip when uncertain._ Rejected: it is alternative 2
   half the time.

**Reasoning.** Everything D23 through D28 worked out about _when_ the system is unsure is
still correct and still runs; only the _response_ changes, from asking to defaulting safely.
The auto-map zone keeps `Supplier` landing in `vendor_name` when the embedding says so; the
auto-add zone keeps a clearly new field appearing as a new column; the middle zone now does
the safe thing instead of raising a hand. The user sees one extra column occasionally, with
a summary that says why, and can fix it in two clicks if they care. Most will not need to.

**Cut.** The `proposals` table and routes, `Proposal.kind`, `AskReason` as a user-facing
concept (it survives as text in `change_summary`), the debounce setting, and the merge
question at initial unification.

---

## D39. A2UI for chat visuals and dashboard panels

**Date:** September 4, 2026 · **Status:** Active. Supersedes D6.

**Decision.** The Agent-to-User Interface protocol is used for exactly two surfaces: the
optional visual inside a chat answer, and each panel of the generated dashboard. In both, the
server builds a complete message array (`createSurface`, `updateDataModel`,
`updateComponents`) and the client renders it from a catalog of four custom components
(`Metric`, `BarChart`, `LineChart`, `ResultTable`) plus the basic catalog for layout and
text. The rest of the application, including the unified table, is hand-built React.

**Alternatives considered.** Hand-built result components switched on a `kind` string
returned by the model. This is genuinely close in effort for four component kinds. It was
rejected because the value of the protocol here is not the renderer, it is the **data
model**: the path-binding contract is what enforces D37 mechanically, and the JSON Schema
validation of emitted messages gives the backend a test that the surface is well formed
before a browser ever sees it. Using A2UI for the main table, as considered and rejected in
D6, is still rejected for the same reason: the table does not need the agent to choose its
shape.

**Reasoning.** Both surfaces are "the agent decided what to show", which is the case the
protocol exists for. Keeping them on one mechanism means one builder module, one renderer
module, one fallback, and one inspect toggle serving both the chat and the dashboard.

**Accepted risk.** Renderer churn, as in D6. Exact pins, a four-component catalog, and a
smoke test per component in Vitest.

**Cut.** Streaming A2UI messages piecemeal (a surface arrives whole in one event even
though the answer around it streams; see D44 and D47), the `SchemaProposal` and
`FieldMapping` components, A2UI action round-trips as a Must (a row click in
`ResultTable` is handled on the client; server round-trips are a Could).

---

## D40. Dashboard panels are proposed by the model from field statistics and vetted by evaluation

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
2. _Let the model write the panel data._ D37.
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

## D41. Chat answers are one request and one response, with stage progress over the event stream

**Date:** September 4, 2026 · **Status:** Superseded September 4, 2026 by D44, the same
day. Anubhav's call: this is a frontend-weighted task and a chat that does not stream reads
as unfinished. The structured-object concern below is answered by splitting the answer into
a plan call and a streamed prose call.

**Decision.** `POST /chat/messages` returns the complete assistant message. While it runs,
`chat.progress` events on the existing workspace stream carry the stage (retrieving,
reading, building) so the pending bubble can say what is happening. There is no token-level
streaming of the answer text.

**Alternatives considered.** Streaming the prose token by token, with citations and the
visual arriving at the end. Streaming A2UI messages progressively, as the v1 plan did for
query results.

**Reasoning.** The answer is a structured object: prose with citation markers that must
resolve to validated chunks, citations that must be grounded to boxes, and a visual whose
specification must be evaluated before it can be rendered. None of that can be shown safely
until the object is complete, and Gemini's structured output mode returns the object whole.
Streaming the prose ahead of its citations would show the user claims before the system knew
whether they were supported. A typical answer completes in a few seconds on the Flash tier;
a pending state that names the stage is honest about that wait without pretending to a
streaming experience the content does not have.

**Cut.** The `fetch` plus `ReadableStream` Server-Sent Events parser for `POST` bodies from
v1 section 7.2, and the A2UI streaming transport.

---

## D42. Corrections stay as inline cell edits; the review queue is cut

**Date:** September 4, 2026 · **Status:** Active

**Decision.** A person can still correct a value by editing a cell on the Data screen
(Should), the value becomes human-verified, and re-extraction never overwrites it, with a
disagreeing model value shown as a conflict (D16 stands, FR-51 is a Must). The review queue,
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

## D43. The source viewer shows backend-rendered page images for every format, including PDF

**Date:** September 4, 2026 · **Status:** Active. Extends D18.

**Decision.** The client's source viewer displays `GET /pages/{n}/image` for every document,
PDFs included, and draws highlight rectangles scaled by `renderedWidth / width_pt`. The
client does not embed pdf.js.

**Alternatives considered.** react-pdf (pdf.js) for PDFs with the backend render for other
formats, as v1 section 8.3 planned.

**Reasoning.** D18 already renders every format to page images with word geometry, and the
PDF renders already exist because the OCR path and thumbnails needed them. Two rendering
paths in the viewer means two coordinate systems to keep in agreement, which is the exact
risk D17 was written to contain. One image and one overlay is one unit test. The cost is
that a PDF is shown as a raster at 144 DPI rather than as selectable vector text, which for
a panel whose job is to show where a value came from is acceptable, and the original is one
click away for anyone who wants it.

**Cut.** react-pdf and the pdf.js worker configuration in Vite. Text selection inside the
viewer.

---

## D44. Chat answers stream token by token over a per-message Server-Sent Events stream

**Date:** September 4, 2026 · **Status:** Active. Supersedes D41.

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

1. _Return the whole answer in one response_ (D41). Simplest and safest for a structured
   object. Rejected: a chat that sits on a spinner for eight seconds and then drops a wall of
   text is the one thing a reviewer of a frontend-weighted submission will notice first.
2. _Stream on the `POST` response itself_ with `fetch` plus a `ReadableStream` line parser.
   One round trip fewer, but `EventSource` cannot be used, so resume, backoff, and
   `Last-Event-ID` all have to be hand-written, and a dropped connection kills the generator
   because the response _is_ the generation. Two requests buy the browser's native
   reconnect and a generation that outlives the connection.
3. _Multiplex tokens onto the existing `/events` workspace stream._ One connection, and
   resume already works. Rejected because D14 persists every workspace event to a table,
   which is the wrong contract for hundreds of token frames per answer, and because a
   second tab would receive every token of every answer whether or not it is showing the
   chat.
4. _WebSockets._ Bidirectional transport for a one-directional stream; D7 already rejected
   it for the same reason.

**Reasoning.** The blocker in D41 was real: citations must resolve to validated chunks and
the visual must be evaluated before it can be shown, and neither can be done on a
half-received structured object. The answer is not to give up streaming but to stop asking
one call to produce everything. A short structured **plan** call decides answerability and
the visual; the visual is evaluated and sent whole before the first token; then a streamed
**prose** call writes the text, with markers and placeholders resolved by the server as they
close (D45, D46). Everything the user sees is validated by the time they see it, and it
arrives as it is written.

The buffer is in memory rather than a table because D9 already pins the application to one
process, so there is nowhere else a second subscriber could be. It is released a minute
after completion so a resumer who reconnects late still catches up, after which the
persisted message is the only source and `GET /chat/messages` serves it.

**Cut.** Streaming A2UI messages piecemeal (the surface is one event, D47). Streaming on
the dashboard, which is generated in the background and announced over `/events`.

**Accepted cost.** A second stream type on the client with its own reducer and tests, and
the `LLMClient` protocol growing a `stream_text` method that the fake provider has to
simulate with recorded text in word-sized pieces.

---

## D45. Citations are chunk-level markers resolved while the answer streams

**Date:** September 4, 2026 · **Status:** Active

**Decision.** The prose model cites with `[^chunk:<id>]` markers and writes no quotes. The
stream processor holds back an open marker until it closes, validates the identifier
against the retrieved set, assigns a citation number, and emits a `citation` event carrying
the chunk's page and boxes (its stored `word_start` to `word_end` span) **before** the token
containing the rewritten `[^n]`. Unknown identifiers are dropped silently. The highlight in
the viewer is the whole chunk, so chunks are kept to roughly 80 to 160 words.

**Alternatives considered.**

1. _Verbatim quotes grounded with RapidFuzz_, as the extraction pipeline does and as v2's
   first draft planned. Tighter highlights. Rejected for chat because a quote cannot be
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

## D46. Figures in chat prose are placeholders the server substitutes from the evaluated result

**Date:** September 4, 2026 · **Status:** Active. Extends D37 to prose.

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

**Reasoning.** D37 made displayed numbers in _components_ come from the evaluator. Prose is
also a display. A model that has just been shown `48,200.00` will usually write it
correctly, and "usually" is the problem in a finance product: the one transposition is
invisible. A placeholder is the same idea as a path binding in A2UI, applied to text, and it
is what Anubhav was describing as sending a variable with the data mapped to it. It also
keeps the chart and the sentence about the chart from ever disagreeing, because both read
the same result. Forbidding numbers would make answers stilted; post-checking would need the
whole text first, which streaming forbids.

**Cut.** Nothing. Numbers copied from passages remain allowed because they are cited.

---

## D47. A chat visual is one complete A2UI surface, sent before the prose, rendered at the top of the message

**Date:** September 4, 2026 · **Status:** Active. Client-side handling left to the
implementer by Anubhav; this is the choice.

**Decision.** The visual for a chat answer is built entirely on the server and sent as one
`visual` event containing the complete A2UI message array, after `sources` and before the
first `token`. The client reserves a fixed-height skeleton for the card as soon as
`status: planning` arrives, fills it with a `SurfaceHost` when `visual` arrives (or
collapses it on `visual_skipped`), and streams the prose beneath it. Citations list last.
A2UI messages are never streamed piecemeal.

**Alternatives considered.**

1. _Visual below the prose, appearing at the end._ The conventional chat layout. Rejected
   because the visual is ready first (the plan call finishes before prose starts), so
   holding it back wastes the one thing that is already done, and a card that arrives under
   a growing text block pushes the layout every time the text wraps.
2. _Stream the A2UI messages themselves_ (`createSurface`, then components, then the data
   model) as v1 planned for query results. Rejected because a surface that renders before
   its data model arrives shows an empty chart, and because the server has the whole array
   at once anyway; there is nothing to gain from splitting it.
3. _Render charts client-side from the evaluated rows without A2UI_, switching on `kind`.
   Close in effort for four kinds. Rejected because it would give chat and dashboard two
   rendering paths for the same result shape, and because the A2UI data model is the
   mechanism that makes D37 enforceable in one place.
4. _Inline the visual mid-prose at a marker the model places._ Attractive, but it lets the
   model decide layout, and a marker that never arrives leaves the card orphaned.

**Reasoning.** The order the server produces things is also a good reading order: what was
searched, what the numbers look like, then the explanation, then the evidence. Reserving
the card's space before the plan resolves is what makes the stream feel stable: the prose
never jumps when the chart lands. Sending the surface whole keeps the client's A2UI module
identical for chat and dashboard, one `SurfaceHost` that takes an array, which is the
smallest possible protocol surface for a renderer that has shipped breaking changes in
three consecutive minor versions.

**Cut.** Piecemeal A2UI streaming, model-placed visuals, and more than one visual per
answer.

---

## D48. Retrieval falls back to hashed bag-of-words vectors when no embedding is available

**Date:** September 4, 2026 · **Status:** Active

**Decision.** `app/retrieval/embedding.py` embeds a text with the configured provider and,
for any text the provider returns no vector for, substitutes a deterministic hashed
bag-of-words vector (512 dimensions, sub-linear term weighting, L2 normalised). Each chunk
records which model produced its vector, and a question is embedded in whatever space the
workspace's chunks already occupy.

**Alternatives considered.**

1. *Return `None` and retrieve nothing.* Honest, and useless: with no key the chat retrieves
   zero passages and every question answers "not in these documents", so the entire v2
   product is undemonstrable without a key. Decision D13 exists precisely to prevent that.
2. *Put the fallback in `FakeClient.embed`.* Less code, and a real bug. Decision D24 relies
   on `embed` returning `None` for an unrecorded label, because an invented vector would
   score a confident cosine against every schema field and make drift auto-apply on noise.
   The provider must stay honest about having no vector; the decision to substitute one
   belongs to the layer that knows it is safe.
3. *Random hashed vectors.* Deterministic but meaningless, so retrieval would rank
   arbitrarily. A chat that retrieves confidently and wrongly is worse than one that
   retrieves nothing, because the failure is invisible.

**Reasoning.** A bag-of-words vector makes cosine similarity approximate token overlap,
which is a real if shallow signal. Measured on the fixture corpus it separates cleanly: a
question about "total due for Northwind Traders" scores 0.57 against the passage naming
them and 0.00 against an unrelated one. So an offline clone genuinely retrieves the right
passage, and the chat, the citations, and the highlight path can all be built and
demonstrated before a key exists.

It also answered open question 1 in the requirements as a Should, almost for free: a small
capped lexical bonus is added to every score, because embeddings handle identifiers like
`INV-2026-0042` poorly (they are not words) while an exact token hit on one is strong
evidence. `PO-99814` retrieves its passage at 0.51 as a result.

**The failure this is designed around.** Mixing spaces. A chunk embedded by Gemini and a
question embedded lexically produce cosines that are pure noise, and the symptom is
confident wrong retrieval rather than an error. So `chunks.embedding_model` records the
space per chunk, `vector_space_for` reads back the workspace's majority space, and the
question is embedded to match. A workspace indexed offline and later given a key stays
coherent because new chunks join the space already in use.

**Accepted cost.** An offline workspace retrieves by word overlap, not meaning, so a
question phrased entirely in synonyms retrieves poorly. That is visible in the answer rather
than hidden, and the records digest (implementation section 6.3) mitigates it by restating
every document's values in the schema's own vocabulary.

---

## D49. `awaiting_schema` is an internal status, reported on the wire as `extracting`

**Date:** September 4, 2026 · **Status:** Active

**Decision.** The document state machine keeps seven states; the interface contract names
six. `awaiting_schema` exists in the database and in the worker's logic, and
`DocumentStatus.for_wire` maps it to `extracting` with a `stage_detail` of "waiting for the
rest of the batch".

**Alternatives considered.** Adding a seventh state to the contract, which puts a state on
the client that only ever means "wait" and that the client can do nothing differently
about. Removing the state and inferring "waiting" from the presence of a parked open
extraction, which the worker's own "is anything still busy" check cannot distinguish from
"mid-model-call" and would deadlock the schema inference.

**Reasoning.** The worker genuinely needs the distinction: a document that has finished open
extraction and is waiting for its batch must not count as busy, or the schema is never
inferred. The client genuinely does not: the document is inside the extraction phase and
still working, which is exactly what `extracting` means to a person reading a progress
strip, and the `stage_detail` carries the nuance for anyone who wants it.

So the split is between what the system needs to reason about and what the interface needs
to render, and the mapping lives in one property rather than being repeated at each
publish site.

**Cut.** Nothing. The information is preserved in `stage_detail`.

---

## D50. Chat message timestamps are set in Python, not by the database

**Date:** September 4, 2026 · **Status:** Active

**Decision.** `chat_messages.created_at` is populated by a client-side default
(`datetime.now(UTC)`) rather than by `server_default=func.now()`, and every query that
orders messages breaks ties on `id`.

**Reasoning.** Postgres `now()` returns the **transaction** start time, not the statement
time, so every row written inside one transaction shares a timestamp to the microsecond.
`chat.service.ask` creates the user's question and the pending assistant answer in a single
transaction, so with a server default those two rows tie exactly and their relative order is
whatever the scan happens to produce.

The symptom is not subtle once it appears: a conversation can render an answer above the
question that prompted it. It surfaced as a failing test on a three-message history whose
order came back reversed, and it would have been intermittent and baffling in the interface,
because the ordering depended on physical row order rather than anything a reader could see.

The tiebreak on `id` is belt to that braces. Two messages created in the same microsecond
would still order deterministically, arbitrarily but stably, which is what stops a test from
flaking and a list from reshuffling between refreshes.

**Alternatives considered.**

1. *`clock_timestamp()` as the server default.* Correct, and it puts the fix in the schema
   where it is easy to lose in a future autogenerated migration.
2. *An explicit per-workspace ordinal, like `workspace_events.seq`.* Strictly correct and
   gap-free, and more machinery than a conversation needs: unlike the event log, nothing
   resumes from a message ordinal.
3. *Ordering by `id`.* Identifiers are random version-4 UUIDs, so this orders nothing.

**Cut.** Nothing. No migration was needed either: the column keeps its existing server
default, which is now simply never reached because Python always supplies a value.

**Noted, and not fixed here.** The same latent tie exists on other tables written in
batches, `records` and `field_values` among them. It does not matter there, because nothing
renders those in creation order: records are ordered by `(created_at, id)` for cursor
pagination, where an arbitrary but stable order is exactly what is wanted. Recorded so that
the next person to depend on creation order knows to check.

---

## D51. The three-screen switch is application chrome, present before a workspace exists

**Date:** September 5, 2026 · **Status:** Active

**Decision.** One `AppHeader` serves all three screens: identity on the left, an optional
workspace chip (label and document count), and a segmented Upload / Chat / Data control on
the right, with "Add documents" beside it inside a workspace. On the first-run screen the
header still renders, showing all three segments with Chat and Data inert.

Which screen is current is passed in as a prop rather than derived from route matching.

**Alternatives considered.** Showing no chrome on the first-run screen, which is what the
screen had before and what a marketing landing page would do. Hiding the Chat and Data
segments until they work. Letting `NavLink` decide the active segment from the URL.

**Reasoning.** D34 cut the product to three screens; the header is where that decision
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
broken something worse: the access token arrives in the URL fragment (D31) and is consumed on
mount, so a redirect before that runs discards the credential. Passing the active screen down
avoids both, and styling keys off `aria-current` so the visual state and the announced state
are one fact rather than two that can drift.

**Cut.** Automatic active-state detection. The caller now has to say which screen it is,
which is one line at each of three call sites.

---

## D52. lucide-react for iconography

**Date:** September 5, 2026 · **Status:** Active

**Decision.** Take `lucide-react` as the icon set, as the design itself does.

**Alternatives considered.** Hand-rolled inline SVG for each icon, which is what the first
version of the upload screen did for its single cloud glyph. Heroicons or Radix Icons.

**Reasoning.** The count only goes up from here: file-type marks, the five confidence tiers,
table controls, viewer controls, citation markers, composer actions. Hand-rolling that many
glyphs and keeping them optically consistent is real work that buys nothing, and the design
was drawn against Lucide's specific shapes, so hand-rolling would also drift from it. The
package is tree-shaken per icon; the six icons used here cost about 2 kB, and the production
bundle moved from 322 kB to 326 kB raw.

The wordmark stays hand-drawn, because it is a mark rather than an icon.

**Cut.** Nothing. `lucide-react` installed with `--legacy-peer-deps` as a one-off, for the
npm reason recorded in D33.
