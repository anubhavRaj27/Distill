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

**Date:** September 3, 2026 · **Status:** Active, **the accepted gap below is now closed**.
Amended September 4, 2026 by D35: the Flash tier now serves chat answers, dashboard
planning, and suggested questions rather than natural language to SQL, which no longer
exists. Amended September 5, 2026 by D62: a key exists, the model identifiers named here
turned out to be uncallable, and the Pro tier is not available at all on this key's plan.
The protocol and the fake provider are unchanged, which is the point of them.

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

**Date:** September 3, 2026 · **Status:** Active. The manifest mechanism stands; its premise
does not. This entry assumed real documents were being supplied, and the corpus is instead
generated. See D67, September 6, 2026.

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

**Date:** September 4, 2026 · **Status:** Active. Its embedding thresholds were calibrated
against a real model on September 5, 2026: see D66. The structure of the rule is unchanged;
two of its four numbers were wrong.

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

**Date:** September 4, 2026 · **Status:** Active, refines decision D24. The embedding
ceiling this entry left unmeasured was measured on September 5, 2026: see D66.

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

**Date:** September 5, 2026 · **Status:** Active inside a workspace. The first-run half is
**superseded by decision D57**, which takes the header off screen 1 entirely.

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

---

## D53. An upload screen that gates on arrival, not on indexing

**Date:** September 5, 2026 · **Status:** Active. Amends requirements section 3.1. Amended
September 6, 2026 by D74: the gate is unchanged, but arriving at it no longer requires
pressing **Continue** — the batch dropped on the first run carries on to the conversation by
itself. Alternative 1 below was rejected for navigating *before* the bytes arrived; this
navigates after.

**Decision.** Files chosen on screen 1 are no longer sent from screen 1. The workspace is
minted, the selection is staged, and the person lands on `/w/{id}/upload`, which owns the
transfer and shows a bar per file. **Continue** is disabled until every file has settled.

"Ready" means the server has the bytes. It does **not** mean parsed, extracted, or indexed:
that work continues on the server and its progress belongs to the processing strip on Chat
and Data (FR-04).

Uploading is done with `XMLHttpRequest`, one request per file.

**Alternatives considered.**

1. _Navigate to Chat immediately_ (v2 as written). Nothing to watch while bytes are still
   leaving the browser, and a question asked against a document that has not arrived is
   answered from nothing.
2. _Hold until every document reaches `done`._ Rejected: that is a 60-second pipeline, and
   requirements section 8 asks a judge to watch the strip finish **while suggested questions
   appear**. Holding the door shut for a minute trades a capability for a progress bar.
3. _Keep one multipart request for the whole batch._ Rejected because it cannot produce the
   screen. A single body reports one byte counter, so per-file bars would have to move in
   lockstep — a picture of progress rather than progress.
4. _Keep using `fetch`._ Not possible. `fetch` reports no upload progress at all, in any
   shipping browser. This is the only place in the client that does not use the generated
   `openapi-fetch` client, and the reason is a platform limitation rather than taste.

**Reasoning.** The gate is drawn where the user's own claim actually holds: there is nothing
worth doing with a document the server has not received, and everything worth doing with one
it has. Splitting on that line keeps both halves honest — the upload screen blocks on
something it can measure and finish in seconds, and the processing strip narrates something
slow without blocking anything.

One request per file also isolates failure: a refused scan no longer takes the other five
down with it, and each row can carry its own reason.

**Consequences recorded elsewhere.** The Upload tab inside a workspace now points at
`/w/{id}/upload` rather than `/`, which closes the footgun where it would have landed a
person on the first-run screen and silently forked a second workspace on drop. Refusals from
screen 1 travel with the batch, because a notice rendered on a screen being replaced in the
same tick is indistinguishable from no notice at all (FR-03).

**Cut.** Nothing. The samples path still goes straight to Chat: the server loads those from
its own disk (D15), so no bytes leave the browser and there is nothing to measure.

**Caught while verifying in the browser, not by the suite:** the screen first selected from
its store with `workspaceId === id ? files : []`, allocating a new array per call. Zustand
compares snapshots by reference, so React re-rendered until it threw "Maximum update depth
exceeded" and the page went blank — while all 40 tests passed, because none of them rendered
the component. There is now a test that renders it in both the staged and the empty case.

---

## D54. The Data screen separates evidence from interpretation, and only one half is client-computed

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
by vendor is worth showing, and product principle 3 with decision D37 require the server to
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

## D55. TanStack Table v9's new API, not its v8 compatibility layer

**Date:** September 5, 2026 · **Status:** Active. Confirms the version in implementation.md
section 2.1.

**Decision.** Build the table on `@tanstack/react-table` 9.2.4 using the v9 API: features and
row-model factories composed statically through `tableFeatures`, and `useTable` with explicit
generics.

**Alternatives considered.** The package's own `@tanstack/react-table/legacy` entry point,
which restores the v8 `useReactTable` / `getCoreRowModel` API. Pinning back to v8.

**Reasoning.** v9 is a rewrite, and the v8 API this project's plan was sketched against does
not exist in it — `useReactTable` is gone, `ColumnDef` takes the feature set as a type
parameter, and row models are composed rather than passed as `getXRowModel` options. The
legacy entry point works, but every symbol in it is marked `@deprecated`: adopting it would
be taking on migration debt on the first day of writing the table, for a saving of about an
hour.

The static composition is also a real benefit here. Only sorting is registered, so filtering,
grouping, pagination, and column visibility never enter the bundle. Column hiding is done by
filtering the column definitions instead, which is why `row.getAllCells()` is the right
accessor rather than `getVisibleCells()`.

**Accepted tradeoff.** Less written-down knowledge to lean on: the API had to be read out of
the shipped type definitions. The two non-obvious findings are recorded here — the option is
`features`, not `_features`, and `useTable` needs its generics stated explicitly or `TData`
silently degrades to the library's `RowData` default and every row callback becomes `any`.

**Caught in the browser, not by the suite:** correcting a cell appended instead of replacing
("Freight" plus "Freight & Logistics" gave "FreightFreight & Logistics"). The cause was not
focus but ordering: the draft lived in the cell and was filled by an effect, so the input's
first render was empty, `select()` on focus selected nothing, and the value arrived behind
the caret. The editor is now its own component, mounted with the right value already in
state. `ValueCell.test.tsx` pins it.

---

## D56. The dashboard is agent-planned, server-computed, server-vetted, and persisted

**Date:** September 4, 2026 · **Status:** Active, implements decision D40

**Decision.** Four separable choices, recorded together because the value is in the
combination:

1. **The agent plans.** One structured call gets the schema and per-field statistics and
   proposes up to six panels, each a title, a visual kind, a `DataQuery`, and a rationale.
2. **The server computes.** Panels hold query specifications, never numbers. Each is
   evaluated in Python and the result written into the A2UI data model, with components
   binding by path. Identical to the chat path, and for the same reason (decision D37).
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
agent return the figures directly, which is decision D37 and is the whole thing this
architecture exists to prevent.

**Cut.** Panel-level interactivity, and drilling from a bar into the records behind it.
`record_ids` is carried in every row for exactly that, so the affordance exists when there is
time for it (requirement A2-07 is a Could).

**A shape note worth keeping.** `Panel.rationale` is deliberately not length-capped on the
response model. A `max_length` there REJECTS rather than truncates, so one verbose rationale
would fail validation for the entire plan and lose every panel with it. The rationale is
decorative; the panel is not. It is truncated when the panel is built.

---

## D57. The first-run screen is a front door, not a workspace: no header, and the name is the illustration

**Date:** September 5, 2026 · **Status:** Active, supersedes the first-run half of decision D51

**Decision.** Three changes to screen 1, which are one change:

1. **No `AppHeader`.** The route `/` renders the name, a sentence, the drop zone, the sample
   link, and the accepted formats. The three-screen switch begins at `/w/{id}/…`.
2. **The name is drawn as particles** that scatter away from the cursor and spring back into
   the letterforms — `ui/ParticleText`, adapted from componentry.dev's cursor-driven particle
   typography.
3. **The funnel illustration is deleted**, not moved. `DistillationMark` is gone from the
   tree rather than left unused.

**Alternatives considered.** Keeping the header with Chat and Data inert, which is what D51
argued for. Keeping both the particle name and the funnel illustration. Making the wordmark
in the header the particle effect, so it appears on every screen.

**Reasoning.**

*On the header.* D51's case was that two inert segments teach what happens after you upload
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

## D58. The upload wait is a spiral of the person's own documents, built in CSS rather than WebGL

**Date:** September 5, 2026 · **Status:** Active, refines decision D53

**Decision.** The upload screen (`/w/{id}/upload`) leads with a slowly turning helix of one
card per file being sent, over a single aggregate line — documents arrived of how many,
bytes sent of total. The per-file bars stay, folded behind a disclosure that opens itself
the moment a file fails. Three sub-decisions, each of which was a genuine fork:

1. **The slides are the user's real files, not stock images.**
2. **The helix is CSS 3D transforms, not `three` + `@react-three/fiber`.**
3. **The per-file rows are demoted, not deleted.**

**Alternatives considered.** The upstream componentry.dev "spiral 3D slider" as shipped: a
`three` scene, one textured plane per slide, a shader for the depth blur, filled with
document photographs fetched from the web. A plain progress bar, which is what the screen
had. A generic loading animation unrelated to the documents.

**Reasoning.**

*Why the user's own files.* The obvious build is stock pictures of invoices and
spreadsheets. It would look the same in a screenshot and be wrong in three ways: it puts a
network fetch between a person and their upload on a product whose setup is meant to be one
offline command; it shows a stranger's paperwork on the one screen that is entirely about
yours; and it quietly contradicts the thing the product sells, which is that what you see
traces back to a document you gave it. The browser is already holding every `File`, so an
image can be its own thumbnail through a blob URL before a byte has left, and every other
format gets a drawn sheet — ruled lines for prose, a small grid for a spreadsheet. A sketch
of the shape, not a facsimile.

*Why not `three`.* `three` plus `@react-three/fiber` is roughly 600 kB on a 399 kB bundle,
for a screen a person sees once for as long as their upload takes. The geometry is not the
expensive part: the placement maths in `ui/Spiral.tsx` is the upstream `useFrame` body,
angle step, yaw and falloff constants included, and it drives `translate3d`/`rotateY`/
`blur()` on ordinary DOM nodes instead of meshes. Two things fall out of that which the
shader version cannot have. A slide is **real markup**, so it can carry a filename, a format
badge, a status stamp and a live thumbnail — none of which a WebGL texture can be without
first being rendered to an image. And there is no WebGL context to lose, so the error
boundary and the "interactive content is unavailable on this device" fallback that ship with
the upstream component are not needed at all.

*Why the rows survive.* They are the truth of what happened to each file, they carry the
accessible progress semantics on native `<progress>` elements, and a failure has to be
readable. But eight near-identical bars is not what this wait should look like, and the
aggregate line answers the only question a person waiting actually has. So they are folded
away and pushed back open by failure. A failed file's bytes are also excluded from the
aggregate, because a bar filling to 100% beside a report that a file was lost is the kind of
small lie people notice.

**Two things the adaptation adds.** The helix measures its own stage and narrows on a narrow
one, rather than trusting a constant radius and being clipped down the sides — measured on
resize, never per frame, since `clientWidth` forces layout. And the loop stops when the tab
is hidden; this is precisely the screen people switch away from while they wait, and a
backgrounded `requestAnimationFrame` is throttled rather than stopped.

**Accessibility.** The stage is `aria-hidden`: a screen reader walking ten repeated cards
would learn nothing the list below does not already say, at ten times the length. Under
`prefers-reduced-motion` the spiral is not the moving version with its animation switched
off — that leaves a stack of cards at odd angles with no explanation — but a static
overlapping fan of the same cards. `GlobalStyle`'s reduced-motion block zeroes CSS
durations and cannot reach a `requestAnimationFrame` loop, so `ui/usePrefersReducedMotion`
was extracted from `ParticleText` (decision D57) and both components now ask for themselves.

**Cut.** Scroll-driven control of the spiral, which upstream has and which is meaningless
here: this is a wait, not a gallery, and nobody should have to drive it. Per-card upload
percentages — the card carries arrived-or-not, the row carries the fraction.

**A test-environment note.** jsdom implements neither `ResizeObserver` nor a 2D canvas
context, and both are now constructed by components under test. `test/setup.ts` stubs them
rather than each test working around them; the stubs are honest, since jsdom has no layout
to report and nothing to rasterise.

---

## D59. Server-Sent Events are read with `fetch`, not `EventSource`

**Date:** September 5, 2026 · **Status:** Active, implements decisions D7 and D44

**Decision.** `client/src/lib/sse.ts` is a hand-written SSE client over `fetch` and
`ReadableStream`, with its own frame parser, its own reconnect loop, and its own
`Last-Event-ID` handling. Both streams use it: the per-answer stream and the workspace event
stream.

**Alternatives considered.** The browser's `EventSource`, which is the obvious choice and
does reconnection and resumption for free. A token in the query string, so `EventSource`
could be used. WebSockets, already rejected in D7.

**Reasoning.** `EventSource` sends no request headers. Every route in this API authorises
with `Authorization: Bearer <workspace token>` (decision D8), and there is no query-parameter
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

## D60. The A2UI catalog is rendered by a hand-written renderer, not `@a2ui/react`

**Date:** September 5, 2026 · **Status:** Active, **diverges from implementation.md section
7 as written**. Reversible; see "What it would take to switch" below.

**Decision.** `client/src/features/a2ui/` renders a surface itself: `model.ts` folds the
message array into a data model plus a component map and resolves path bindings; `Surface.tsx`
renders the four custom components and the five basic layout and text ones with this
project's own styled components; `SurfaceBoundary.tsx` catches a render error and falls back
to a plain table of the same rows. No `@a2ui/react`, no `@a2ui/web_core`, no Recharts.

**Alternatives considered.** `@a2ui/react` 0.11.0 with `@a2ui/web_core` 0.10.7 and Recharts,
which is what implementation.md section 7 specifies and what D39 assumed.

**Reasoning.** D39's own argument is the reason this is defensible: *"the value of the
protocol here is not the renderer, it is the data model"*. The path-binding contract is what
mechanically enforces D37, and it is enforced here — `readProperty` resolves
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

## D61. The chat screen holds one live answer beside a cached history

**Date:** September 5, 2026 · **Status:** Active, implements requirements section 3.2

**Decision.** `useConversation` keeps two separate stores. History is a React Query cache of
persisted messages; the answer currently streaming is local component state, folded from
events by a pure reducer. They meet once, at `done`, when the event's persisted message
replaces the live one in the cache.

**Alternatives considered.** Writing every token into the query cache, so there is one list.
Keeping the whole conversation in local state and treating the server as write-only.

**Reasoning.** A token event arrives several times a second and an answer produces hundreds
of them. Writing each into the query cache means invalidating and re-rendering the entire
conversation per token; keeping the whole thread in local state throws away caching, sharing
between screens, and the refetch that recovers from a dropped stream. The split puts the
churn where it is cheap and leaves the durable half alone.

The join is clean because the server made it so: `done` carries the whole persisted message
and its docstring calls it authoritative, so a client that reconnected late replaces its
local state wholesale rather than reconciling a partial buffer against a full one.

**Two things this makes possible, both requirements.** A refresh mid-answer reattaches: a
persisted row saying `streaming` is found in history on load and its stream is tailed, since
generation continues server-side whether or not anyone is listening (D44). And **stop does
not abort the socket** — it posts to the stop route and lets the server publish `stopped`
and then `done` through the normal path, which is what keeps the partial answer that
requirement FR-30 promises to keep. Aborting the stream would drop that final state.

**A correctness note that cost a test.** `citation` is the one event that is not idempotent
under replay. `Last-Event-ID` resumes from the last frame the client *saw*, and a frame in
flight when a socket dropped was seen by nobody, so the server can legitimately redeliver an
event already applied. Appending citations would double the footnote list; the reducer
replaces by number instead.

**Cut.** Asking a second question while one is streaming — the composer is shut for the
duration, because a second question would abandon a stream the server is still paying to
generate. Editing or retrying a question. Conversation-level scroll restoration beyond
sticking to the bottom when the reader is already there.

---

## D62. Flash for extraction, Flash Lite for anything a user waits on

**Date:** September 5, 2026 · **Status:** Active, supersedes the tier half of D13

**Decision.** `LLM_EXTRACT_MODEL=gemini-3.5-flash` and
`LLM_FAST_MODEL=gemini-3.5-flash-lite`, with `LLM_FAST_THINKING_LEVEL=low` applied to the
calls a user waits on (chat planning, chat answering, dashboard planning, suggested
questions) and never to extraction or schema inference, which keep the model's own default
effort.

**Alternatives considered.** Keeping `gemini-2.5-pro` and `gemini-2.5-flash`, which is what
D13 chose and what the plan and `.env.example` said until today. `gemini-pro-latest` for
extraction. `gemini-3.6-flash` for both tiers, which is what this entry said in its first
draft an hour earlier. `gemini-3.5-flash` for both. Two models with no thinking
configuration at all.

**Reasoning.** Three facts, all measured against the real key on September 5, 2026 rather
than reasoned about:

- **The 2.5 identifiers are dead for this key.** Both answer 404 with "no longer available
  to new users". They still appear in `models.list`, which is why listing models is not a
  test and a real call is.
- **The Pro tier is not on the plan.** `gemini-pro-latest` and `gemini-3.1-pro-preview`
  answer 429 with `limit: 0` — a quota of zero requests, not a spike. So the stronger-tier
  half of D13 is not a choice available to make.
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
  requests **per day** on this key. So, it turned out on September 6, does `gemini-3.5-flash`:
  a single pass over the ten-document sample corpus spent all twenty and left the next run
  failing. Only the Lite models have room, which is why **both tiers are now
  `gemini-3.5-flash-lite`** — a correction to this entry's own first draft, made a day later
  by running a real corpus through it rather than a single probe. Lite extracted all six
  sample invoices to the letter (D67), so the cost of the change is unmeasurable here and
  the benefit is a demo that runs twice.

**What this costs, stated plainly.** D13's reasoning for a stronger extraction tier was
sound and is unchanged; it simply cannot be acted on with this key. Extraction quality is
therefore whatever `gemini-3.5-flash` at default effort gives — on the invoice probe, nine
fields with verbatim quotes that all located in the source, which is the behaviour the
grounding stage needs. A paid key would want `LLM_EXTRACT_MODEL` pointed back at a Pro
model, which is a one-line change because model identifiers were kept as configuration.

**Cut.** Any automatic fallback from one model to another. A model that 404s or is not on
the plan is a configuration error the operator must see, and D26 already settled that a
provider that cannot be constructed fails loudly rather than degrading into heuristics.

---

## D63. Embeddings are 768 wide, task-tagged, and the space is labelled

**Date:** September 5, 2026 · **Status:** Active, refines D24 and D36

**Decision.** Three changes to how vectors are produced, all inside the Gemini adapter and
its two callers:

1. **Width.** `LLM_EMBED_DIMENSIONS=768`, rather than `gemini-embedding-001`'s native 3072.
   Vectors below the native width come back un-normalised, so the adapter normalises them.
2. **Task.** `LLMClient.embed` takes a provider-neutral `task`: passages are embedded as
   `document`, a chat question as `query`, and two field labels being compared for drift as
   `similarity`. The adapter maps those to the provider's own task names.
3. **Space label.** A chunk's `embedding_model` now records `model@width`, and `search`
   logs a warning when a workspace's recorded space is not the configured one.

**Alternatives considered.** Leaving the native 3072 and changing nothing. Truncating 3072
vectors locally. Ignoring task types, which is what the code did until today. Recording the
bare model name, as before.

**Reasoning.** 3072 floats per chunk is four times the JSONB storage and four times the
per-question arithmetic, for a corpus of at most a few thousand passages where retrieval is
a Python loop by deliberate choice (D36). 768 is a supported width from the same model
rather than a truncation, so the quality loss is small and the constant factor saved is real.

Task types matter more than the width does. Retrieval is asymmetric: the passage and the
question that should find it are not the same kind of text, and the model has been trained
to embed them differently when told which is which. Not saying was leaving quality on the
table for one keyword.

The space label is the safety net for the other two. A width change silently makes old
chunks incomparable with a new question, and the symptom is the worst kind: a chat that
answers "not in these documents" about a document that plainly says it. `cosine` already
returns zero on a dimension mismatch, so nothing crashes; the label plus the warning is
what makes it visible instead of merely survivable.

**Cut.** Re-indexing existing workspaces automatically on a width change. It is a
destructive-ish background job triggered by a configuration edit, and the warning tells an
operator to do it deliberately. Recording per-task vectors in the fake provider's fixtures,
which would triple the fixture corpus to encode a distinction no recording can honour.

---

## D64. Provider constraints are learned from the provider: `maxItems` is described, not sent, and its retry hint is obeyed

**Date:** September 5, 2026 · **Status:** Active, closes review finding 8.7 and refines D20

**Decision.** Three corrections to the Gemini adapter and the schema converter, each one
prompted by a real failure rather than a reading of the documentation:

1. **`minItems` and `maxItems` are no longer sent.** They are removed from the supported
   subset in `app/llm/jsonschema.py` and restated in the schema's `description` instead
   ("Return at most 80 items."). `minimum`, `maximum` and `title` are removed from the
   documented set too, since they were never emitted.
2. **A 429 carrying `limit: 0` is terminal, not retryable**, and says so: "not included in
   this API key's plan, so retrying will not help".
3. **The provider's own retry delay is obeyed.** When an error says "Please retry in 29.8s"
   or carries a `retryDelay`, the adapter waits that long, capped at 45 seconds, instead of
   its exponential schedule.

**Alternatives considered.** For (1): dropping `max_length` from the response contracts
altogether, which loses local validation as well; or keeping `maxItems` and catching the
failure at runtime. For (3): raising `LLM_MAX_ATTEMPTS`, or lengthening the exponential
schedule for everything.

**Reasoning.** `maxItems` is in the documented provider subset, and `gemini-3.6-flash`
answers a schema containing it with `400 INVALID_ARGUMENT` naming no argument. It reached
the schema from `max_length=80` on `OpenExtraction.fields`, which is on the extraction path,
so **every extraction call this project makes would have failed** — a total outage that the
existing offline test suite could not have predicted, because the suite asserts the
documented subset and the documented subset is wrong. That is precisely review finding
8.7's risk, arriving as predicted and now closed by a test rather than a hope. The bound
still reaches the model as a sentence and still validates locally, so nothing is lost but
the rejected keyword.

The two retry corrections are the same lesson in a smaller register. A 429 that will clear
in thirty seconds and a 429 that will never clear are spelled identically apart from
`limit: 0`; treating both as transient means three attempts inside a closed window and then
a message telling the user to try again shortly about something permanent. Obeying the
stated delay costs one slow document; ignoring it costs a failed one.

**Cut.** Sending `response_json_schema` (the newer full-JSON-Schema field) instead of
`response_schema`, which would make the hand-written converter redundant but is a larger
change than one keyword warrants and would reopen the question D20 settled. Per-model
capability probing at startup: it spends quota on every boot to learn something a test
already encodes.

---

## D65. The schema converter's own two bugs, found by the first real calls

**Date:** September 5, 2026 · **Status:** Active, refines D20 and the mitigation in D64

**Decision.** Two fixes in `app/llm/jsonschema.py`, and one honest correction to the test
that was supposed to prevent both:

1. **Nullable unions are collapsed before references are resolved, not after.** An optional
   nested model arrives as `anyOf: [{$ref: X}, {type: null}]`, and resolving first sees no
   `$ref` at the top level and walks away with it.
2. **`MAX_DEPTH` is raised from 6 to 10.**
3. **`RESPONSE_MODELS` in `tests/unit/test_jsonschema.py` now lists all six response
   models.** It listed three and called itself "every response model".

**Alternatives considered.** For (1): special-casing `$ref` inside `_collapse_nullable`,
which spreads reference knowledge across two functions. For (2): flattening `DashboardPlan`
to fit the existing limit, which is a contract change to satisfy a number that was a guess.

**Reasoning.** Both bugs were invisible offline and total in production, and for the same
underlying reason: the fake provider never converts a schema, so no offline test exercises
the converter against the contracts that use it, and the one test that did exercise it was
parametrised over the half of the contracts that happened to be written first.

The nullable-reference bug is the worse of the two, because it fails *quietly*.
`ChatPlan.visual` converted to `{"nullable": true}` — no type, no properties, a schema that
forbids nothing and describes nothing. The provider accepts it. The model, asked for a
field it has been told nothing about, answered `false`, and the whole chat visual feature
(D47, requirement A2-02) would have failed validation on every call while the schema looked
fine in a debugger. The depth limit at least failed loudly.

Six levels was a reasonable guess with no key to check it against; `DashboardPlan` needs
eight, and eight was sent to the provider and accepted. Ten keeps a guard against runaway
nesting without vetoing a contract that demonstrably works.

**The lesson worth keeping, and it is not about JSON Schema.** A mitigation is only as good
as its coverage, and a test parametrised over a hand-written list silently stops covering
the thing it was written for the moment someone adds a seventh contract. The list is now
the six models; the check for whether it is still all of them is a human one, which is
stated here rather than pretended away.

**Cut.** Deriving `RESPONSE_MODELS` automatically by walking the codebase for every model
passed as a `response_model`. It would keep the list honest without anyone remembering to,
and it is real reflection machinery in a test whose value is being obvious.

---

## D66. The embedding thresholds, measured instead of guessed

**Date:** September 5, 2026 · **Status:** Active, calibrates D24 and D27

**Decision.** `embedding_auto_map` moves from 0.95 to **0.88** and
`novelty_ceiling_embedding` from 0.30 to **0.80**. `margin` stays at 0.05.
`tests/unit/test_similarity_calibration.py` encodes the measurements that justify all
three, using two-dimensional unit vectors placed at exact angles so the calibration is
checkable with no key.

**How they were measured.** Twelve pairs of field labels a person would merge (`Vendor` and
`Supplier`, `Invoice Number` and `Invoice No`, `Tax Amount` and `VAT`, ...) and twelve pairs
a person would not (`Payment Terms` and `Currency`, `Vendor` and `Invoice Number`, ...) were
embedded with `gemini-embedding-001` and scored with the project's own `cosine`.

| class | min | median | max |
| --- | --- | --- | --- |
| should merge | 0.822 | 0.898 | 0.982 |
| should not merge | 0.764 | 0.811 | 0.827 |

**Alternatives considered.** Leaving D24's numbers, which the code itself flagged as the one
thing a key would settle. Normalising the scores by subtracting a corpus mean, so the
thresholds could stay where they were. Dropping the embedding signal and relying on string
similarity alone.

**Reasoning.** This model's cosines are compressed into a narrow band near the top, which is
normal for a modern embedding model and fatal to thresholds chosen by intuition. Both old
numbers were not merely wrong, they were **unreachable**, and each failed silently in a
different direction:

- At 0.95, two of twelve synonyms mapped. Drift auto-mapping effectively did not exist, and
  the live run showed the consequence: two invoices phrasing the same fact as "Total due"
  and "Grand total" produced `total_amount` and `invoice_total`, two columns for one thing.
- At 0.30, no field's best match ever fell below the ceiling, so "clearly novel" never fired
  and the auto-add branch was dead code that the whole suite passed over.

0.88 sits above every unrelated pair observed, with five points of headroom, and catches
nine of the twelve synonyms. 0.80 sits just under the unrelated floor. The band between
them is the ask zone, where honest uncertainty belongs.

**What is deliberately NOT fixed.** The two classes overlap: the lowest synonym (0.822,
`Bill To` versus `Customer`) is below the highest unrelated pair (0.827, `Payment Terms`
versus `Currency`). No threshold separates every case, and the calibration test asserts the
overlap so nobody tunes a number until the examples behave. In the same spirit, the live run
still keeps `total_amount` and `invoice_total` apart, because `Grand total` scored 0.926
against `Total due` and 0.901 against `Subtotal` and the margin rule refuses to guess between
them. Folding a grand total into a subtotal is precisely the silent corruption D24 exists to
prevent, and with the review loop cut (D34, D42) an ask surfaces as two columns rather than
a question — a real cost, recorded rather than tuned away.

**Cut.** Making these four numbers environment variables. `Thresholds.from_settings` already
reads them by name if they exist, so adding them later is a one-line change, and until
somebody needs to vary them per deployment they are calibration constants that belong beside
the evidence for them.

---

## D67. The sample corpus is generated, and generated to be inconsistent

**Date:** September 6, 2026 · **Status:** Active, replaces the premise of D15

**Decision.** `samples/` holds ten documents written by `server/scripts/generate_samples.py`,
listed in `manifest.json`, with ground truth in `expected.json`. The generated files are
committed; the script exists so the corpus can be corrected rather than only replaced.

Six formats (Portable Document Format, Word, spreadsheet, comma-separated values, plain
text, and a scanned image), four document kinds (invoice, contract, policy, bank statement,
plus a reference table), and one two-page document. Six invoices across five vendors, three
of them with no purchase order.

**Alternatives considered.** Real documents, which is what D15 assumed and what the project
originally intended. Downloading a public invoice dataset. Two or three documents rather
than ten.

**Reasoning.** Anubhav asked for the corpus to be created rather than supplied, so D15's
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
variant was **measured** against the calibrated thresholds (D66) before being written into a
document, and phrasings that fail to unify were avoided on the two fields the headline demo
depends on. That is designing the corpus around a known weakness, and it is worth being
honest about. The weakness is D66's margin rule: "Supplier" resembles "Vendor" at 0.910 and
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

## D68. A substituted figure carries its unit, and the model's repeat of it is dropped

**Date:** September 6, 2026 · **Status:** Active, refines D46

**Decision.** `StreamProcessor` remembers the unit on a figure it has just substituted and
removes one immediate repeat of that unit from the following prose, stepping over closing
markup such as a backtick. The planning prompt also states that a placeholder expands to a
figure including its unit.

**Alternatives considered.** The prompt change alone. Formatting figures without their unit
and letting the model supply it. Leaving it, since it is cosmetic.

**Reasoning.** The first real answer over the sample corpus read "16,752.90 USD USD". The
prompt gives the model a bare number and tells it not to retype it; the substitution then
renders the figure with its currency, and the model has already written "USD" after the
placeholder because that is what one does after a number. Prompt-only fixes are a request;
this is a guarantee, and the guarantee is what a demo needs.

Dropping the unit from `format_figure` instead would break D46's actual purpose: the prose
figure has to read exactly like the chart's, and the chart shows a currency.

**Cut.** Any attempt to fix pluralisation, spacing or currency-symbol style in model prose.
This removes a duplicate the server itself caused; the rest of the sentence is the model's.

---

## D69. The planner is told that a workspace holds more than one kind of document

**Date:** September 6, 2026 · **Status:** Active, refines D37

**Decision.** The chat planning prompt gains a rule: when a question is about one kind of
document, restrict the query with a `present` filter on a field only that kind carries.

**Alternatives considered.** Making the document kind a queryable dimension in `DataQuery`,
resolved from `extractions.kind`, which is already stored. Filtering by filename. Leaving it.

**Reasoning.** Asked "how many invoices are missing a purchase order number", the planner
counted every record with no purchase order and answered **7**. It was not wrong about the
data: seven records in the workspace have no purchase order, because four of them are a
contract, a policy, a bank statement and a reference table. The true answer is 3. A
confidently wrong metric on the demo script is the worst possible failure for a product
whose claim is that its numbers can be trusted.

The query language could already express the restriction — `invoice_total present` is
exactly "this record is an invoice" — so the gap was guidance, not capability. With the rule
in place the same question returns 3.

**The better fix, deliberately not taken yet.** Document kind belongs in `DataQuery` as a
first-class filter. `extractions.kind` already holds it, so no migration is needed, but the
evaluator, the query contract, the prompt and the dashboard planner all move together, and
that is a change to make deliberately rather than at the end of a session about sample data.
Recorded here so it is a known gap rather than a surprise. Until then, a question about a
document kind depends on the planner picking a good proxy field, which is a prompt working
as intended and not a guarantee.

---

## D70. Background sessions flush the event bus, like request sessions always did

**Date:** September 6, 2026 · **Status:** Active, completes D14 and D29

**Decision.** `session_scope`, the transactional session every background task uses, now
does what the request dependency in `app.deps` has always done after a successful commit:
`bus.flush_after_commit(session)` and `flush_submissions(session)`, with the matching
discards on the rollback path.

**Alternatives considered.** Publishing events outside the session, which reintroduces the
uncommitted-row problem D14 solved. Having the progress strip poll the documents route
instead of streaming, which is a workaround dressed as a design.

**Reasoning.** Document processing runs entirely in background sessions. Without the flush,
every event the pipeline published was written to `workspace_events` and delivered to
**nobody**: the sequence numbers were allocated, the rows were durable, and the live queue
of every connected subscriber stayed empty. The progress strip therefore showed the upload
request's own `uploaded` event, which a request session did flush, and then sat unchanged
for the entire run while the work completed behind it.

**Why it survived this long.** Because refreshing the page fixed it. A reconnecting client
replays from the table (D14), so every manual check after the fact looked correct, and the
end-to-end tests drive the pipeline directly rather than watching a stream. It took seeding
ten documents and *watching* to see that nothing moved. Measured: a subscriber connected
before a seed received 13 frames, all of them `uploaded`; after the fix, 82 frames covering
parsing, extraction, indexing and completion for all ten documents.

**The general shape of the bug, which is worth more than the fix.** Two paths did the same
work, one of them had an extra responsibility bolted to the request lifecycle, and the
duplicate was invisible because the durable half kept working. `session_scope`'s own
docstring described the request path as the one with "the event-bus and worker-submission
flushing that decision D29 requires" — the gap was written down and read as a description
rather than as a defect.

**Cut.** Merging the two session helpers into one. They differ in how they acquire the
session, and collapsing them means threading a request through background code. The
duplication is now two lines, and a test in `test_event_stream.py` fails if either path
loses them.

---

## D71. The Upload screen is the document library, and the upload is the transient part

**Date:** September 6, 2026 · **Status:** Active, extends requirements section 3.1

**Decision.** `/w/{id}/upload` lists every document in the workspace: the format the server
actually parsed it as, its stage or failure reason, page count, size, and two actions — open
it in the source viewer, or delete it. The upload progress keeps its place above the list
while bytes are moving. `DocumentSummary` gains `source_format` so the list can say what a
file really is.

**Alternatives considered.** A fourth screen for files, which breaks the three-screen rule
that the whole product is organised around (D34). Putting the list on the Data screen beside
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

**A bug this turned up.** Invalidating the workspace query after a delete was not enough:
the refetch returned the shorter list and the deleted row stayed on screen until a reload,
which reads exactly like the deletion having failed. The row is now removed from the cached
overview directly, and the refetch follows for everything derived from it.

**Cut.** Re-extracting a document from here, though the route exists: re-extraction is
interesting after a correction, which happens on the Data screen, and putting it here would
invite re-running the pipeline on a whim. Renaming a document. Sorting and filtering the
list — at twenty-five files, the upload limit, scanning is faster than choosing a sort.

---

## D72. The first run and the workspace's upload screen are one component

**Date:** September 6, 2026 · **Status:** Active, extends D71 and the layout half of D57

**Decision.** `/` and `/w/{id}/upload` render one component, `features/upload/UploadScreen`,
in two states decided by whether the route carries a workspace. The page is the same shape
in both: the name, then the way to put documents in, then what is already in. What changes
is the middle — the drop zone and "Try with sample documents" on the first run; "Add more
files", "Continue" and the document library inside a workspace. The two former screens,
`FirstRunScreen` and `UploadProgressScreen`, are deleted.

**Alternatives considered.** Keeping two components and sharing a layout component between
them. Keeping them separate and simply tightening the workspace screen's spacing. A fourth
route for the library.

**Reasoning.** Anubhav's observation was that the workspace upload screen was mostly empty,
and that the fix was for it to be the first screen with a different middle. The emptiness
had a cause worth naming: that screen's layout was built around a drop zone, and once a
workspace exists there is no drop zone, so it was a page shaped around a hole. Arriving at
it from the header's Upload tab did not read as the same place as the front door, which is
odd for a product with three screens whose whole organising idea is that you can always see
all of them.

Sharing a layout component between two screens would have kept the divergence one file away
and left two places to change when the shape changes. One component with a conditional is
smaller, and it makes the relationship explicit: this is one screen that knows whether it
has a workspace yet.

**The hero is smaller in the workspace state.** The same argument does not need making twice
at full volume, and a 210px canvas above a list of ten files is the empty space this merge
was meant to remove. The particle sampling is denser there to match: the step through the
rasterised word is in pixels, so the same density at half the size puts half as many
particles across a stroke and the letterforms go ragged.

**Two bugs this created, both found by driving the real screen.**

- **The token vanished.** Nearly everything here is read once, on mount: the workspace
  token, the files staged for it, whether the batch has started. Two routes sharing one
  component means React keeps the instance mounted across the navigation between them, so
  dropping files on the first run created the workspace, navigated, and then announced that
  the token was missing — because it had been read on a screen with no workspace. The route
  adapter keys the screen by workspace id, which restores mount-per-workspace, the thing the
  two separate components had for free. Three lines, against auditing every piece of state
  below for a lifecycle that had just changed underneath it.
- **The library did not fill in after the first upload.** It was refreshed by counting
  documents in the cached overview that had reached a terminal stage, and the overview for a
  new workspace is empty, so there was nothing to count and the list stayed empty while the
  document sat there indexed. It now counts from the live event stream, which knows about
  documents the cache has never heard of.

**And one that was already there, now understood.** `invalidateQueries` was not putting new
data on this screen: after a delete (D71) and after an upload, a remount showed the right
thing immediately while the mounted component kept the stale list. Both paths now ask the
query for data directly — `refetch` for the upload, a direct cache edit for the delete —
which works. Why invalidation does not is not yet explained, and that is recorded as an open
question rather than dressed up: something in this client's query configuration or its
provider tree is not doing what the library documents, and the next person to hit it should
suspect that before writing another workaround.

**Cut.** Dropping files anywhere on the workspace state of the screen. The drop zone is the
first run's affordance and "Add more files" is the workspace's; a page-wide drop target that
exists on one state and not the other is a rule nobody can see. Worth reconsidering, since a
page about documents where dropping a document does nothing is a small papercut.

---

## D73. Transient confirmations are toasts held outside the component tree

**Date:** September 6, 2026 · **Status:** Active

**Decision.** A small store (`ui/toastStore.ts`) and one renderer (`ui/Toasts.tsx`), mounted
above the routes in `App`. Messages are raised by whatever knows something happened, live at
most three at a time, dismiss themselves, and can be dismissed by hand.

**Alternatives considered.** An inline notice on the screen that raised it. A notification
library. Passing a callback down from `App`.

**Reasoning.** The thing worth confirming is often the last thing a screen does before it
goes away: "your documents arrived" is raised as the upload screen navigates to the
conversation (D74), so a notice rendered by that screen would unmount in the same tick it
appeared. That is the same problem `pendingUploads` solves for a file selection, solved the
same way and for the same reason.

**What a toast is for here, and what it is not.** It confirms something that already happened
and needs no response. Anything a person has to act on stays on the screen: a refused file
gets `RejectionNotice` under the drop zone, a failed document keeps its row in the library.
A toast carrying the only copy of something important is a message that disappears while you
are reading it.

**Details that are not decoration.** The region is a polite live region, so the confirmation
is announced without stealing focus, and `aria-atomic` is off so a second toast does not
re-read the first. It sits **top right**: a person lands on the chat screen straight from an
upload, the composer is at the bottom centre, and the first two versions of this covered it
and then clipped its corner. Hovering pauses nothing — a toast that will not leave while the
pointer rests nearby reads as stuck.

**Cut.** Actions inside a toast ("Undo"), which would make it the only route to something and
put it back on the critical path. Stacking more than three. Pausing on hover.

---

## D74. A finished upload carries on to the conversation by itself

**Date:** September 6, 2026 · **Status:** Superseded by D81, which keeps the toast and drops
the navigation

**Decision.** When the batch staged on the first run finishes arriving, the screen raises a
toast and navigates to Chat after a short beat. Two cases deliberately do not navigate:

- **Anything failed.** The person stays with the list of what could not be sent.
- **Files added from inside the workspace.** Someone standing in their library who adds a
  file is looking at the library.

The transition between the two states of the upload screen is also smoothed: the intake
recedes while the workspace is being created, the workspace state fades and rises in, and
the hero settles down to its smaller size rather than being redrawn at it.

**Alternatives considered.** Keeping **Continue** as the only way on. Navigating the instant
the last byte lands, with no beat. Navigating for every batch, including later additions.

**Reasoning.** Anubhav asked for this, and D53's own gate is the argument for it: once the
bytes have arrived, the reason for holding someone here is gone, and Continue becomes a click
whose answer was never in doubt. The conversation is where they were heading when they
dropped the files.

The beat before leaving is not politeness. The spiral has just settled every card onto its
tick and the summary has just reached "N of N"; cutting away in the same frame reads as a
glitch rather than as a step forward.

**The exceptions matter more than the rule.** Sliding a failure off-screen a second after it
appears is the interface deciding that bad news is not worth your time, and the toast for
that case is a warning that stays up nearly twice as long. Moving someone who added a file
from inside their own library would be answering a question they did not ask.

**A bug this found.** Landing on Chat straight from an upload showed "0 documents" in the
header, because that screen's overview was fetched while the workspace was still empty and
nothing refetched it. It now refetches when the live stream reports another document settled,
the same fix as on the upload screen and for the same reason (D72).

**Cut.** A countdown or a "cancel" on the navigation, which would put a decision back in
front of someone who has already made it. Auto-navigating from the samples path, which
already goes straight to Chat because there is nothing to upload (D15).

---

## D75. The dashboard renders its panels, which it had been dropping

**Date:** September 6, 2026 · **Status:** Active, completes D39 and D40

**Decision.** `Dashboard.tsx` renders each panel's A2UI surface through the same `Surface`
component that renders a chat visual.

**Alternatives considered.** None worth the name. This is a defect, not a design question.

**Reasoning.** The server has been sending complete A2UI message arrays per panel — chart
type, columns, and an `updateDataModel` carrying server-computed rows — and the client was
rendering the panel's title and rationale and discarding the body. The comment in its place
said the slot stayed empty "until `GET /dashboard` and the A2UI catalog exist". Both existed:
the route was built in the same pass as the panels, and the catalog is the renderer D60
chose to hand-write, with `Metric`, `BarChart`, `LineChart` and `ResultTable` in it.

So the product had a dashboard with no charts in it, and a comment explaining that this was
expected. That is the failure mode worth naming: a placeholder with a plausible reason
attached outlives the reason.

**What it looks like now**, on the sample corpus: a `Metric` reading 16,752.90 USD and a
`BarChart` of five vendors, both matching `samples/expected.json` to the cent, because the
numbers were computed by the evaluator and bound by path (D37).

**Cut.** Nothing. The panel frame, states and rationale are unchanged.

---

## D76. The upload screen waits for documents to be READ, not received

**Date:** September 6, 2026 · **Status:** Active, amends D53 and D74

**Decision.** Four changes, which are one change:

1. **The samples path lands on the upload screen** rather than going straight to Chat.
2. **The screen narrates the whole pipeline**, per document: reading the file, pulling out
   values, making it searchable, ready — for uploaded files and sample documents alike.
3. **A file's row carries on past "Sent"** into what the server is doing with it, and the
   summary above them counts documents *ready*, not bytes *arrived*.
4. **The hand-off to Chat fires when everything has been read**, not when the last byte
   lands.

**Alternatives considered.** Keeping the samples path on its shortcut to Chat, where the
processing strip already narrates. Showing the pipeline only for uploaded files. Keeping the
hand-off on arrival and letting the reading finish on the Chat screen.

**Reasoning.** Anubhav asked for this, and the shape of the screen was arguing for it
already. "Ready" meaning "the server has the bytes" is a strange place for a progress row to
stop, because nothing useful has happened yet at that point: a document you cannot ask about
is not done in any sense the person cares about. The upload screen was reporting the half of
the work that is fast and invisible, and handing over just as the half that takes a minute
began.

The samples path made it starker. It skipped this screen entirely, so the one route a
reviewer is most likely to take was the one that showed the least — a click, a pause, and a
conversation about ten documents that appeared from nowhere.

**This reverses D53's alternative 2, deliberately.** That entry rejected "hold until every
document reaches done" because requirements section 8 asks a judge to watch the strip finish
*while suggested questions appear*, and holding the door shut for a minute trades a
capability for a progress bar. What makes the reversal defensible is that the door is not
shut: **Continue** is enabled the moment the bytes are in, so anyone impatient leaves
immediately and lands exactly where they used to. What changed is the default for someone
who does nothing, and the screen they wait on now has something to say. Requirements section
8 is updated to match.

**A race this had to avoid.** "Everything is settled" is trivially true of an empty list, so
a screen that has heard nothing yet would hand the person straight on. The trigger requires
having *watched* at least one document in a non-terminal state first, which is also the
right rule for someone who opens the screen later to look at a finished workspace: nothing
was watched, so nothing moves them.

**Cut, and reinstated a day later.** The spiral was cut for the samples path on the argument
that it is the person's own files in flight (D58) and nothing is in flight there. That was
wrong, and D79 puts it back: the argument was about where the bytes are, and the person is
watching a wait either way.

---

## D77. The workspace names itself, and the name can be changed

**Date:** September 6, 2026 · **Status:** Active, extends FR-01

**Decision.** When the first batch finishes processing, a small model call names the
workspace from the filenames and the fields that were extracted. The name is written once
and never regenerated. `PATCH /workspaces/{id}` sets it by hand, and the header's title is
the control that does so.

**Alternatives considered.** Naming it from the first document's filename with no model
call. Asking the person for a name up front. Regenerating the name whenever documents are
added.

**Reasoning.** "Untitled workspace" is what the header said for the entire life of every
workspace, which is a wasted line in the chrome of every screen. The material for a good
name is already there by the time the first batch settles — the filenames, and the field
labels the schema inference just agreed on — and it costs one cheap call on the fast tier.

Asking up front is worse than either: it puts a text field between a person and the thing
they came to do, and they cannot answer it well anyway, because they have not seen what the
product made of their documents yet.

**Two rules that matter more than the name itself.**

- **A name a person typed is never overwritten.** The guard is `label is null`, not "label
  looks like a default", which is also why the column starts null rather than starting as
  the string "Untitled workspace": null means nobody has said, and a string cannot be told
  apart from a workspace somebody deliberately called that.
- **A failed naming call is not a failed batch.** It is logged and the workspace keeps its
  null label, because a nameless workspace is a cosmetic problem and a failed upload is not.

**Cut.** Regenerating the name as a workspace grows: the name would change under someone
who had learned it. Naming from the document text rather than the filenames and fields,
which is a much larger prompt for a three-word answer.

---

## D78. One suggested question is guaranteed to draw a chart

**Date:** September 6, 2026 · **Status:** Active, extends D40 and D47

**Decision.** The prompt for suggested questions asks for a **breakdown** — the "X by Y"
shape — as one of its three, and `chat/suggestions.py` guarantees it: if none of the
returned questions splits a measure by a category, one is generated from the field
statistics and put first. The chart figures in `Surface.tsx` are also formatted by the
server's rule, so a bar and the prose citing it read the same.

**Alternatives considered.** The prompt change alone. A hard-coded suggestion for the sample
corpus. Leaving it, since a person can type "total by vendor" themselves.

**Reasoning.** The charts worked and nobody could find them. Asked for three good questions,
the model reliably offered a sum, a lookup and a superlative — "What is the total sum of all
invoice totals?", "What are the payment terms for Globex Corporation?", "Which vendor has
the highest invoice total?" — three answers in prose. Suggested questions are how most
people meet this product's visual half; nobody types "total amount by vendor" into a blank
box on their first visit. So the product looked like it had no charts in it, which is
exactly how it was reported.

A prompt is a request. This is the one place the guarantee can be made, so it is made here,
and the generated question is built from the **statistics** rather than the schema: the
measure has to be a currency field with numbers actually in it, and the category has to have
between two and twelve distinct values and be present in at least a third of the documents.
A suggestion naming a field nine documents left empty is worse than no suggestion, because
the person trusted it.

**Two things learned by watching it run.** The first version offered "the total due by bill
to" — it preferred the customer over the vendor, and it named the category from the
document's own label. Both are fixed: counterparty fields rank above other party fields, and
the category is named from the field key, which is already a normalised noun, rather than
from whatever the document happened to print at the top of a column.

**Cut.** Curating suggestions for the sample corpus specifically, which would make the demo
better and the product no better. More than one guaranteed shape: three suggestions is a
small budget and the other two are earning their place.

---

## D79. The spiral turns for documents being read, not only for files being sent

**Date:** September 6, 2026 · **Status:** Active, reverses a cut in D76

**Decision.** `DocumentCard` takes a small descriptor — a filename, a phase, and a `File`
only when the browser happens to hold one — instead of an `UploadTask`. The upload screen
fills the spiral from whichever it has: the files being sent, or, when nothing is being
sent, the documents the server is reading.

**Alternatives considered.** Leaving the samples path without an animation, which is what
D76 decided. A different, simpler spinner for that path. Synthesising fake upload tasks for
sample documents so the existing card would take them.

**Reasoning.** D76 cut the spiral from the samples path with a tidy-sounding argument: the
cards are the person's own files in flight, and on that path nothing is in flight. The
argument is about where the bytes are. The **wait** is the same wait — forty-odd seconds of
a server reading ten documents — and it is the wait a reviewer is most likely to sit
through, since the sample button is the obvious way in. What they got instead was a list and
a progress bar, and the product's one piece of theatre went missing from the one route that
shows it off. Anubhav noticed within a day.

The cards were welded to `UploadTask` because that is what they were first written for. A
descriptor is what they always needed: an image renders its own thumbnail when the bytes are
here, and a document on the server's own disk gets the same drawn sheet every non-image file
already gets.

**A detail that came free.** Phases map onto the pipeline, so a card takes its tick when its
document is *read*, not when it is received — ten sheets turning and settling one by one as
the batch finishes, which is a better picture of what is happening than the same ten sheets
all ticked at once a second after the click.

**Cut.** Per-card stage words. The card carries a name, a shape and a mark; the rows
underneath carry the words, and a spiral you have to read is not a spiral.

---

## D80. A type the model could not enumerate is a string

**Date:** September 6, 2026 · **Status:** Active, guards D24 and product principle 6

**Decision.** `inferred_type()` in `app/domain/fields.py` is the boundary where a model's
answer becomes our schema. It has one rule: `enum` becomes `string`. Both places that build
a `FieldSpec` from an extraction — the initial proposal and drift — go through it.

**Alternatives considered.** Filling `enum_values` from the values that happened to turn up
in the batch. Relaxing `FieldSpec` to permit an enum with no values. Dropping the field.

**Reasoning.** Found on a live sample run, and total: the model typed a `currency` column as
an enumeration, `FieldSpec` refused to be built — correctly, since an enum with no values
permits nothing — and the exception took down schema inference. That runs **once, for the
first batch**, so ten documents sat at "0 of 10 ready" forever with a `ValidationError` in
the log and nothing on screen. It had not shown up before because whether the model reaches
for `enum` at all is a matter of variance.

Filling the values from the batch is the tempting fix and the wrong one. A schema inferred
from ten documents that all say "USD", which then **rejects** an eleventh saying "EUR", is
the one thing this product must never do: it would be losing real data to defend a guess.
A string accepts everything and loses nothing, and the values observed so far are already
written into the field's description where a person can see them.

**Cut.** Enum inference altogether, for now. A real enumeration needs a person to confirm
the closed set, and there is no screen that asks — the review loop was cut in D34. The type
stays in `FieldType` for a schema someone edits by hand later.

---

## D81. The finished upload holds Continue instead of moving the person

**Date:** September 6, 2026 · **Status:** Active, supersedes D74, keeps D73 and D76

**Decision.** When the documents this visit set going have all been read, the upload screen
raises its toast and no longer navigates to Chat on its own. The way forward is the
**Continue button**, held while this visit's work has produced nothing askable yet. See D82
for exactly when it opens.

"This visit" is the whole of the change. One piece of state, set at mount when the pending
store holds an entry for this workspace and set again when files are added from inside the
workspace, gates both the toast and the button. Opening the Upload tab on a workspace that
finished reading an hour ago announces nothing and holds nothing.

**Alternatives considered.** Keeping the navigation and hardening the "came from the first
run" test. Navigating only on the very first arrival per workspace and remembering that in
storage. A countdown with a cancel.

**Reasoning.** Anubhav reported it: clicking the Upload tab sent him to Chat, every time,
and the toast came with it. Two faults met.

The first was a leak. The pending store was cleared inside the "there are staged files"
branch, so the samples path — which stages an **empty** selection precisely so it still
reads as an arrival (D76) — never cleared it. The entry sat there for the life of the tab
and every later visit to the Upload tab read as a fresh arrival.

The second is why the fix is not just that clear. The screen's other guard, "work was seen
in progress", is read off the workspace event stream, and that stream is durable and
resumable from a persisted log (D7): reopening a finished workspace can replay documents
moving through the pipeline. Any signal built on watching the pipeline will eventually fire
on a visit where nothing new happened. A disabled button cannot make that mistake — the
worst it can do is be shut for a moment on a screen the person chose to be on.

D74 argued that Continue was a click whose answer was never in doubt. That was true of the
first arrival and false of every visit after it, and the cost of being wrong is not
symmetric: a click nobody needed costs a click, while taking the screen away from someone
who deliberately opened it costs them the thing they came to do. The button also now says
something the navigation could not — it holds until the documents are **readable**, not
merely received, which is what D76 established as the moment that matters.

**Cut.** The 1100 ms beat before leaving, which has nothing left to smooth. The copy on both
the note and the summary that promised the reading would be narrated on the next screen; it
is narrated here.

---

## D82. Continue opens on the first document read, not the last

**Date:** September 6, 2026 · **Status:** Active, refines D81

**Decision.** The Continue button is held only until the **first** document this visit set
going becomes askable. One document at `done` opens it, while the rest of the batch carries
on being read behind it. Three things release it, and nothing else holds it:

- A document has been read.
- Everything settled and none of it could be read — there is nothing more coming.
- No file made it off this machine — likewise.

Bytes still in flight no longer hold the button on their own. A batch where the first file
has been read while the tenth is still uploading is a workspace with something to talk
about.

**Alternatives considered.** Holding for the whole batch, which is what D81 shipped.
Holding for a fixed fraction. Holding while any upload is in flight, regardless of what has
already been read.

**Reasoning.** Anubhav asked for it, and the next screen was already built for it. Chat
answers over whatever has been indexed and narrates the rest in its processing strip
(D53, D76), so one read document is a working conversation. Holding the button for the whole
batch let the slowest document in a pile of ten decide when anybody could start — which is
the same mistake as gating the screen on the last byte, one stage further down the pipeline.

The button is not a claim that the workspace is finished, and the screen does not pretend it
is: the summary above it still counts "1 of 10 documents ready" and the toast still waits
for the whole batch. What opens early is the door, not the verdict.

**Cut.** Any minimum count above one. Ten documents where one is ready is a smaller
conversation than ten where all are, not a broken one.

---

## D83. The Data screen's layout, repaired

**Date:** September 6, 2026 · **Status:** Active, amends D71 and D72

**Decision.** Six fixes to one screen, found by measuring it rather than reading it.

**1. The grid tracks are fractions.** `Columns` was `grid-template-columns: 62% 38%` with a
24px gap. Percentages resolve against the container's content box and know nothing about the
gap, so the tracks summed to the full width plus 24px and the dashboard column hung exactly
one gap over the right edge of the page — past the padding, flush against the window. It is
now `minmax(0, 62fr) minmax(0, 38fr)`, which divides what is left after the gap. This is what
Anubhav reported; everything below was found while looking at it.

**2. The table scrolls in a window of its own.** The frame scrolled sideways and grew
downwards without limit, which put both of the table's controls out of reach at once: the
horizontal scrollbar sat at the bottom of a 1,258px-tall table, a page-scroll away from the
columns it moves, and the header row was gone by the third row. It now caps at `70vh` and
scrolls in both directions.

**3. The header row and the document column are sticky.** Only possible because of 2 —
sticky positions against the nearest scrolling ancestor, so a table with no scrollport of its
own has nothing to stick to. With a thirty-two column schema, a row of values with no name on
it, thirty columns to the right, is unreadable.

**4. Columns take their natural width.** At `width: 100%` the browser must fit every column
into the frame, and with thirty-two columns that means squeezing each to its minimum — which,
next to `overflow-wrap: anywhere` in the cells, is one character. "Northwind Trading Company"
was rendering as "North wind Tradin g Comp any" in a 130px column, in a table that was
4,000px wide and scrolling sideways anyway. The table is now `max-content` with a `min-width`
of 100%, cells are capped at a readable measure, and the cells' wrap rule is `break-word`,
which does not count break opportunities when the browser computes a minimum width.

**5. The application header can shrink.** Every child of the bar was `flex-shrink: 0`, so
below about 820px wide the bar overflowed the window, took "Add documents" off the right edge,
and gave the whole document a horizontal scrollbar. The workspace name is the one thing that
can be shortened without losing a control, and it already ellipsises.

**6. The two columns have matching headings.** The page's own heading said "Dashboard" over a
screen that is 62% table, with a second thing also called Dashboard beside it. The page is
now "Data" and the right-hand column has a heading of its own, which also starts the panels
and the table at the same height — a 32px strip of buttons against a 38px heading was starting
them 6px apart, which reads as a mistake rather than as a column.

**Alternatives considered.** For 2 and 3: making the whole screen a fixed-height shell with
two independently scrolling columns, which is what Chat does. Rejected for this screen — the
left column's legend, edit hint and document summary come to 330px of fixed furniture, which
would have left about three rows of table on a laptop.

**Reasoning.** Each of these is a defect rather than a preference, and each was invisible in
the code and obvious in the browser. The grid one in particular cannot be seen by reading the
rule; it needs the gap and the percentage in the same thought.

**Cut.** Clamping a long cell value to a fixed number of lines, which would make rows even at
the price of hiding extracted values — the opposite of what this screen is for.

---

## D84. A dashboard panel does not print its title twice

**Date:** September 6, 2026 · **Status:** Active, refines D39 and D75

**Decision.** `build_surface` takes `include_title`, and the dashboard passes it as false.
The panel card renders the title; the surface no longer renders a heading of its own. The
title stays in the surface's data model either way.

**Alternatives considered.** Dropping the card's title and letting each surface name itself.
Detecting a heading in the client and hiding the card's title when one is present.

**Reasoning.** A dashboard panel's title IS `visual.title` — literally the same string,
assigned from the same field in `dashboard.py` — so every panel printed its name twice, one
line under the other. A chat visual is the opposite case and keeps its heading: it arrives
loose in a stream of prose with nothing else to name it.

Detecting it in the client would mean the client inspecting a surface's component tree to
decide what to draw around it, which is exactly the coupling the A2UI boundary exists to
avoid.

**Cut.** Nothing. The title is still in the data model for anything that reads the result.

---

## D85. The wordmark is a link home, and home is Upload

**Date:** September 6, 2026 · **Status:** Active, extends D57

**Decision.** The wordmark in the application header is a link. Inside a workspace it goes to
that workspace's Upload screen; with no workspace it goes to the front door. Its accessible
name stays the visible one, "Distill".

**Alternatives considered.** Linking to Chat, which is the main screen (D34). Linking to the
front door in every case. Leaving it inert.

**Reasoning.** Anubhav asked for it, and a logo in the top left is a home link everywhere
else — leaving it inert spends a convention people already have. Upload rather than Chat
because Upload is where the documents are, and it is the one screen of the three that is also
the way to add more.

Inside a workspace it must not go to the bare front door: that screen mints nothing and would
show a drop zone for a workspace the person is already standing in.

**Cut.** A separate home icon, which would be a second control for a job the mark already
does.

---

## D86. The MVP deployment: one container, one Postgres, nothing else

**Date:** September 6, 2026 · **Status:** Active, except the platform, which D87 changed
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

**Reasoning.** The constraint that decides everything is D9 and D14: the document queue and
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

## D87. Railway, and a connection string that does not need editing

**Date:** September 6, 2026 · **Status:** Active, supersedes the platform half of D86

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

**Alternatives considered.** Koyeb, which D86 chose. Instructing the reader to rewrite the
URL by hand, which is what the previous version of `docs/deployment.md` did. Using Railway's
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

