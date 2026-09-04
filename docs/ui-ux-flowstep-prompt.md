# UI/UX generation prompt — for Flowstep

Paste everything below the line into Flowstep as one prompt.

---

## Product

**Distill** turns messy, heterogeneous documents (invoices, receipts, purchase orders,
bank statements — PDFs, scans, spreadsheets) into one clean, queryable table. The hard
problem it solves isn't extraction, it's **unification** (many documents that disagree
with each other, forced into one coherent schema) and **trust** (every value on screen
must be traceable to the exact region of the source document it came from, and a person
must be able to correct it in seconds).

Primary user: a finance operations person who currently retypes numbers into a
spreadsheet by hand. They are not a technical user. They are skeptical of anything that
looks "too automatic," because automation that's wrong costs them more than automation
that's slow.

## Creative direction

Design a visual language around **distillation**: taking something crude and mixed and
narrowing it down to something pure and legible. That's a metaphor, not a mood board
instruction — don't literally draw beakers. Let it show up structurally instead: messy
input (a pile of documents) visibly narrowing into ordered output (a clean table), a
sense of *filtering* and *settling*, gradients or layering that read as "clarifying."

Explicitly avoid the default AI-tool-dashboard look: generic card grids, indigo-on-white
SaaS chrome, a sidebar of icons nobody remembers the meaning of. This product's whole
value proposition is trust and precision — the interface should feel like a **precision
instrument**, closer to a well-made lab tool or a cockpit than a marketing dashboard.
Confident whitespace, a strong type hierarchy, restrained motion that has a *reason*
(data settling into place as it streams in, a highlight animating onto a document region)
rather than decorative animation.

One hard constraint that must survive the creative direction: **confidence can never be
conveyed by color alone** (accessibility requirement — some users can't distinguish the
color signal). Every confidence tier (high / medium / low / conflict / human-verified)
needs a second channel too: an icon, a border treatment, a pattern, a label. Make that
constraint part of the visual system rather than an afterthought bolted on.

Be genuinely creative with layout and detail — this is a chance to make document review
feel less like data entry and more like something a finance person would enjoy using. Take
real risks on the visual metaphor, density, and the transitions between panels. The one
thing that should never feel experimental is trust: provenance links, confidence signals,
and error states must always read as unambiguous and calm, even inside a bold layout.

## Pages / screens to design

### 1. First run / empty state
No workspace yet. One-sentence explanation of what the product does, a large drop zone
for files, and a "Try with sample documents" button that's equally prominent — a
first-time visitor should understand the product in 30 seconds without reading anything
else. This screen is the trust pitch: it should visually hint at "mess in, clarity out"
before the user has done anything.

### 2. Workspace shell (the core screen)
The main app. Needs to hold, without feeling crowded:
- A **data table** as the dominant element — virtualized, sortable, filterable columns,
  resizable, columns can be hidden/reordered. Cells are typed (currency, date, boolean as
  a mark, list as chips) and each cell visibly carries its confidence tier.
- A **schema panel** (collapsible) showing the current fields, their types, and coverage
  (what % of documents have that field populated).
- An **upload / processing list** — each file as a row with a live stage
  (Uploaded → Parsed → Extracting → Done/Failed), streaming without a page refresh.
- A **review queue** entry point — a count badge is enough here; the queue itself can be
  its own panel (see screen 4).
- A **query entry point** — a persistent, always-visible input (think command bar, not a
  buried menu item) that takes the user into the full Query console (screen 7) on submit.

Think about how these panels relate spatially — tabs, a resizable multi-pane layout, a
command-palette-style overlay for query — rather than assuming a fixed sidebar+table
template.

### 3. Document viewer / provenance panel
Opens when a user clicks any cell. Shows the original source document (PDF page, or the
relevant spreadsheet range / DOCX paragraph for other formats) with the **exact source
region highlighted**, plus the model's short reasoning and the raw text it read. This is
the single most important trust moment in the product — clicking a number and *seeing*
where it came from — so give it real design attention: how the highlight draws the eye,
how the reasoning text is presented alongside the highlighted region, how this panel
opens (slide-over, split view, modal) without losing the user's place in the table.

### 4. Review queue
A focused, keyboard-first flow for burning down low-confidence and conflicting cells,
ordered by impact (most consequential first). Each item shows the value, its confidence
tier, and one-key actions: accept, edit, mark "not present." Design this like a triage
inbox, not a settings form — the person using it wants to move fast through dozens of
items without touching the mouse.

### 5. Schema proposal / drift card
Most schema changes never reach the user — a confident field match or an obviously novel
field just applies on its own (see screen 6). This card only appears for the cases the
system is genuinely unsure about: a plausible-but-uncertain rename, several candidate
fields it could be, or a type mismatch. Because it's reserved for real judgment calls, it
should feel deliberate and a little weightier than a passing notification — closer to a
diff review than a toast. Shows the proposed field, a similarity match against an existing
one where relevant ("this looks like `vendor_name`, 92% match"), and three clear actions:
map to existing, add as new, ignore.

### 6. Schema history
This is where the *other* schema changes live — the ones applied automatically without
asking, alongside every change a user decided in a proposal card. Design it as a version
timeline / changelog, and make the auto-applied entries visually distinct but not alarming
(a quiet "applied automatically" tag, not a warning), each with a one-click revert. This
screen is what makes the auto-apply behavior trustworthy: nothing that happened is hidden,
it just didn't have to interrupt the user first. Worth surfacing a lightweight version of
this (a toast or an inline note) right in the workspace shell the moment an auto-apply
happens, so a user who's paying attention still sees it in the moment, not just in a log
they have to go find.

### 7. Query console
The dedicated screen for asking questions across every document — this is the product's
"wow" moment for a judge, so it earns its own full page, not just a bar plus a results
strip.

**Follow the Claude.ai pattern for the two states of this screen:**
- **New query state.** No question asked yet: the input sits centered on an otherwise
  near-empty page — generous whitespace, no history clutter, no results scaffolding
  waiting around it. Below or around the centered input, show the three **suggested
  questions** generated from the current schema (e.g. "Total spend by vendor", "Invoices
  over $10,000 with no PO number") as clickable chips/cards — these double as onboarding
  for what's even askable. This is a deliberate reset moment, the same feeling as opening
  a fresh Claude conversation.
- **Thread state.** The moment a question is submitted, the layout transitions: the input
  docks to the bottom of the screen (persistent, always ready for the next question) and
  the page becomes a vertical thread, question and answer stacked top to bottom, most
  recent at the bottom. Each answer is one of the rendered result shapes (table, single
  metric with context, bar chart, or short list — chosen by the agent, not hard-coded per
  query type), so design a family of result "shapes" that all clearly belong to one
  system and read well stacked in sequence. A **follow-up question** ("now only Q2")
  appends as a new turn in the same thread rather than replacing the previous result —
  this should visually read as a continuation, exactly like a chat reply, and the agent
  can use earlier turns as context.

Per answer/turn, include:
- A **generated SQL panel**, collapsed by default, showing exactly what ran — this is
  where a skeptical user's trust gets earned or lost, so treat it as a real feature, not
  a debug footnote.
- A visible link on every value that came from an extracted field, back to its source
  document — opens the provenance panel (screen 3) the same way a table cell does.

Elsewhere on this screen:
- A developer-only **"inspect surface" toggle** showing the raw JSON driving the current
  result.
- **Query history** — past questions in the session — can live as a collapsible sidebar
  (like Claude's conversation list), letting the user jump back and re-run one with a
  click, without competing with the centered/threaded main area.
- An **unanswerable-question state** as its own turn in the thread: explains what field is
  missing and offers to add it, rather than failing silently.

### 8. System / degraded states
Design the unhappy paths as first-class screens, not afterthoughts: a file that fails to
parse (with a specific reason, not a generic error), a scanned page running OCR, a model
call retrying, a query that can't be answered (explains what's missing, suggests a
rephrase), and a "backend unreachable" banner that leaves the last-known table visible
and read-only. These should look like they were designed by the same hand as the rest of
the product — calm, specific, never a raw error dump.

## Deliverable

For each screen: primary layout, key states (empty / loading-streaming / populated /
error), and how confidence tiers and provenance are visually represented consistently
across all of them. Desktop-first (this is a data-dense professional tool), tablet
usable, phone can be a simplified read-only view.
