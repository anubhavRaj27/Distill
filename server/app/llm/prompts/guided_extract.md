You are extracting structured data from a business document into an **existing schema** that
the user has already agreed to. Fill that schema, and separately report anything important
the schema cannot hold.

# The document

Filename: {filename}
Format: {source_format}
Pages: {page_count}

{pages}

# The schema to fill

{schema}

# What to return

`values`: one entry for **every field in the schema above**, in the same order, even the
ones this document does not contain. For a field the document does not contain, set
`value_text` to null and give a short `reasoning` saying it is absent. Use the schema's
`key` exactly as given.

`extra_fields`: any value in the document that a person would want to query but which does
not correspond to any schema field above. Use the same entry shape, with `key` as a
lowercase machine name and `label` as the document's own wording.

Each entry, in both lists, carries:

- `value_text`: the value **exactly as the document writes it**, as text. Keep the currency
  symbol, the separators, and the date format. Do not convert or reformat.
- `value_type`: for a schema field, use the type the schema declares. For an extra field,
  your best judgement.
- `evidence_quote`: a short **verbatim** span from the document containing the value. It is
  checked mechanically against the document, and a value whose quote cannot be located is
  treated as unreliable. Leave it null only when the value is absent.
- `page_index`, `confidence`, `reasoning` as usual.

# Rules

1. **Never force a fit.** If this document genuinely has no value for a schema field, say
   so with a null. Putting an unrelated value into a field because the field exists is the
   single worst thing you can do here: it corrupts a column other documents share.
2. **Never guess a value**, and never carry one over from your general knowledge of what
   such documents usually say.
3. **Quote verbatim**, character for character, from the text above.
4. `extra_fields` is how the system learns that the schema is incomplete. Use it rather than
   discarding a value, and rather than bending it into a field where it does not belong.
5. Extract document-level fields, not line items.
