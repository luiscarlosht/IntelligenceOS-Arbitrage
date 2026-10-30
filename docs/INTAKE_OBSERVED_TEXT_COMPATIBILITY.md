# Observed intake text compatibility

Browser `displayed_price` accepts a single unsigned amount, optionally prefixed
with `$` or `Now $`, and compares it numerically with the exported USD price.
Ranges, multiple amounts, promotional arithmetic and unrecognized wording reject.
Shipping charges retain their existing strict contract; missing charges stay unknown.

Availability descriptions accept CR/LF line breaks. A separate whitespace-normalized
string is interpreted with channel-specific rules, including the observed shipping
order deadline suffix. Raw JSON and original description cells are never rewritten
or normalized for equality. Delivery cannot establish shipping. Literal conflicts,
canonical alias conflicts, record duplicates and batch replay checks remain strict.

The offline fixture uses 38 synthetic product rows across seven batches with the
exact rejected text formats from the 2026-10-30 two-pass snapshot. The private
original 38 rows were separately audited across every field; no additional mismatch
was found after these changes. Original runtime observations are not published. Observed formats include six
`Now $…` prices, multiline arrival/order deadlines and pickup time/day text.
This historical audit says nothing about the current Sheet or an ingestion window.

Read-only offline check (no database, credentials or connected services):

```sh
cd /root/IntelligenceOS-Arbitrage && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -c 'import app.sheets_intake as m,json,pathlib; p=pathlib.Path("tests/fixtures/sheets_rejected_20261030.json"); rows=m.table(json.loads(p.read_text())["Walmart_Intake"],m.FIELDS); [m.product(r) for r in rows]; print(m.__file__, "validated",len(rows),"rows in",len({r["batch_id"] for r in rows}),"batches")'
```

VM inspection resolves the manual CLI module to the checkout above. The configured
systemd unit instead runs legacy/discovery orchestrators under `/opt/intelligenceos-arbitrage/current`,
which resolves to release `68230d3fdaef588bb7ba5c8340f49a473e8386b7` and has no intake module.
Service bus access is unavailable in this session; active process state is unverified.
No deployment, ingestion, Sheet edit, credential access, Amazon request or email occurred.
