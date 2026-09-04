# Distill

Zamp take-home, Problem 1: turn unstructured or semi-structured documents into clean,
structured data that can be searched and queried. Build window 4 to 5 days from
September 3, 2026. Author: Anubhav Raj.

## Read these first, every session

| File                     | What it is                                          |
| ------------------------ | --------------------------------------------------- |
| `docs/requirements.md`   | Governing requirements. Cites are `FR-xx`, `A2-xx`. |
| `docs/implementation.md` | Governing technical plan.                           |
| `decisions.md`           | Decision log. **Required deliverable.**             |

These three files are the plan of record. Follow them. When the code has to diverge,
update the document in the same change and add a `decisions.md` entry. Never let code
and spec drift silently.

## Non-negotiables

1. **Every technology chosen and every decision made goes in `decisions.md`**, in the
   format: decision, alternatives considered, reasoning, what was cut. Never delete a
   superseded entry, mark it superseded and link forward.
2. **Clean file structure**, feature-folder based, especially on the client.
3. **Three screens, nothing else: Upload, Chat, Data.** Chat is the main screen and works
   by retrieval over the documents. Data is one unified table plus an agent-generated
   dashboard. There is no schema review loop, no proposal card, no SQL. Decision D34.
4. **Every value on screen traces to a highlighted region of its source document.** Table
   cells and chat citations open the same viewer.
5. **Displayed numbers are computed by the server, never typed by the model.** The agent
   emits a query specification; the server evaluates it and binds the result into A2UI by
   path. Decision D37.
6. **Never lose a human correction.** Re-extraction and schema changes preserve
   human-verified values.
7. **Domain-agnostic core.** Finance documents are the demo corpus, not an assumption.

## Layout

```
Zamp assignment/
├── CLAUDE.md            this file
├── decisions.md         decision log (required deliverable)
├── README.md            one-command setup, architecture, demo script
├── docs/                requirements.md, implementation.md
├── samples/             heterogeneous sample documents + fixtures
├── server/              backend
└── client/              frontend (React + TypeScript)
```

Both docs are v2 (September 4, 2026). The pivot from v1 is recorded in `decisions.md`
D34 through D43 and in requirements section 0; do not reintroduce v1 features.

## Verified environment facts (September 3, 2026)

Node 22.16.0, npm 10.9.2, Homebrew 6.0.19 with nothing installed, arm64 macOS.
No Docker, no Postgres, no Python beyond system 3.9.6, no Tesseract.

## Verified package facts (September 3, 2026)

`@a2ui/react@0.11.0` peer-depends on `react@^19.2.7`, `react-dom@^19.2.7`,
`zod@^3.25.76`. `@a2ui/web_core@0.10.7`. React latest is 19.2.8, so it satisfies.
Zod latest on npm is 4.5.4, which does **not** satisfy the peer range, so Zod must be
pinned to `3.25.76` exactly, project-wide.
