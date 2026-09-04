You are extracting structured data from a business document. This workspace has no schema
yet, so your job is to find every field that a person filing or querying this document
would care about, and to report each one with the evidence for it.

# The document

Filename: {filename}
Format: {source_format}
Pages: {page_count}

{pages}

# What to return

For every salient field you find, return one entry with:

- `key`: a machine name, lowercase with underscores, such as `vendor_name` or
  `invoice_total`. Prefer the conventional name for the concept over a literal
  transliteration of the document's wording, so a document headed "Bill From" still yields
  `vendor_name`.
- `label`: the field's name **exactly as this document writes it**, such as `Supplier` or
  `Bill To`. Do not normalise it. This is the evidence for a later decision about whether
  two documents mean the same thing by different words, so the original wording matters.
- `value_text`: the value **exactly as the document writes it**, as text. Keep the currency
  symbol, the thousands separators, and the date format the document used. Do not convert,
  round, or reformat anything.
- `value_type`: one of `string`, `number`, `currency`, `date`, `boolean`, `enum`,
  `string_list`.
- `evidence_quote`: a short **verbatim** span copied from the document that contains this
  value. This is the single most important part of your answer. It is checked against the
  document mechanically, and a value whose quote cannot be found is treated as unreliable.
- `page_index`: the zero-based page the value appears on.
- `confidence`: 0.0 to 1.0, your honest estimate.
- `reasoning`: one short sentence on why you chose this value.

Also return `document_kind`: what sort of document this is, such as `invoice`,
`bank statement`, `receipt`, or `purchase order`.

# Rules

1. **Never guess.** If a field is not in the document, leave it out entirely. A missing
   field is a fact we can work with; an invented one is worse than useless.
2. **Quote verbatim.** Copy the evidence span character for character from the text above,
   including its punctuation. Do not paraphrase it, do not tidy it, and do not assemble it
   from two different places.
3. **Cite the right page.** The page number must be the page the quote is actually on.
4. Extract **document-level** fields, not individual line items. One document becomes one
   row, so "the invoice total" is a field and "the price of the third line item" is not.
5. Prefer fewer, better fields. Do not turn prose, notes, or terms and conditions into
   fields.
6. For a currency value, keep the amount and its symbol or code together in `value_text`,
   such as `$12,480.50` or `EUR 3,410.00`.
