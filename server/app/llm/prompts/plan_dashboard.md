Propose the panels for a dashboard over this collection of documents. Someone is about to
scan it for the first time and has asked no questions yet. Decide what is worth showing
them.

# The collection

{document_count} documents.

# The schema

{schema}

# Field statistics

These are computed from the actual extracted values. Ground every proposal in them.

{stats}

# What to return

Up to {max_panels} panels, fewer if fewer are worth showing. Each panel is:

- `title`: a short heading, at most eight words.
- `kind`: `metric` for one figure, `bar` for a comparison across a category, `line` for a
  trend over bucketed dates, `table` for more than a handful of rows.
- `query`: what to compute, in the same form as a chat visual.
  - `aggregate`: `sum`, `count`, `avg`, `min`, or `max`.
  - `measure_field`: the field key to aggregate. Null only when `aggregate` is `count`.
  - `group_by`: the field key to break it down by, or null for a single total.
  - `bucket`: `month`, `quarter`, or `year` for a date `group_by`, otherwise `none`.
  - `filters`: `{{field, op, value}}` conditions. `op` is one of `eq`, `ne`, `gt`, `gte`,
    `lt`, `lte`, `contains`, `missing`, `present`. Omit `value` for `missing` and `present`.
  - `sort` and `limit` if the defaults are wrong.
- `unit_hint`: the ISO currency code when the measure is money, otherwise null.
- `rationale`: one sentence saying why this is worth showing, **citing a number from the
  statistics above**. "Coverage is 96% across 24 documents, so the totals are meaningful"
  is a rationale. "Useful for understanding spend" is not.

# Rules

1. **You never supply numbers for the panels themselves.** You describe what to compute; the
   server computes it from the extracted records and puts the real figures on screen.
2. **Only use field keys from the schema above.**
3. **Propose only what the statistics support.** A panel over a field present in two of
   twenty documents is a panel that will look broken. A `bar` grouped by a field with one
   distinct value is one bar. A `bar` grouped by a field where every value is unique, such
   as an invoice number, is one bar per document. The server drops panels like these before
   anyone sees them, so proposing them wastes a slot you could have used.
4. **Vary the shape.** Six metrics is a worse dashboard than two metrics, a bar, a line, and
   a table. Lead with the one figure that best characterises the whole collection.
5. `metric` requires `group_by: null`. `line` requires a bucketed date `group_by`.
6. Prefer four good panels to six padded ones.
