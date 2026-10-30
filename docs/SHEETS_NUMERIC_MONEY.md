# Exact browser JSON money comparison

Original browser JSON may encode a known monetary observation as a JSON number
or as literal display text. A numeric `displayed_price: 24.86` and text export
`item_price_usd = "24.86"` represent the same amount; rejecting them solely for
JSON type is a parser defect. This compatibility also applies to a known numeric
`shipping_charge`. Exported Sheet cells still must be text.

Browser JSON floating-point tokens are decoded directly to Decimal, and only
string, integer or Decimal monetary values can enter the existing finite,
nonnegative money validator. Boolean values are excluded. Equality remains exact:
no float tolerance, rounding, choosing between prices or string substitution.
A conflicting high-precision JSON decimal remains a conflict. Missing amounts
remain unknown. Item prices remain positive USD, and duplicate canonical aliases
must still agree under their existing strict checks.

`Free`, membership/cart thresholds, checkout-dependent shipping and other
shipping descriptions are not numeric charges. They are not silently converted
to zero or blank. Original browser JSON and exported rows remain unchanged.
Producer mapping errors require evidence-backed correction outside the parser.

Read-only `check` counts valid batches, not new records. It does not consult or
write SQLite. For a read-only database-aware comparison, use
`app.sheets_reconcile --live --database var/sheets-intake.sqlite3` through the
existing dedicated readonly client. Do not interpret validation as ingestion.

Tests cover representative amounts, integer/decimal/string equality, exact
high-precision conflicts, malformed/nonfinite/boolean values, duplicate aliases,
known numeric shipping, missing shipping, descriptive/conditional shipping
rejection and a read-only batch check that cannot acknowledge or mutate rows.
