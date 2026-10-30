# Candidate failure diagnostics

The CSV candidate runner previously replaced its last attempt status with
`failed_or_parser_rejected`, losing HTTP status, Amazon error codes and parser
labels. It also relabeled a completed response when later matching failed.
Future runs retain allowlisted response metadata as soon as a response is received,
and distinguish `request_failed`, `parser_rejected`, and later matching/checkpoint
failures. Each failure has a fixed operation stage; parser codes are selected from
fixed internal labels. Unknown Amazon codes map to OTHER. Raw response bodies,
exception messages, tokens, credentials and headers are never persisted.

HTTP failures retain available status and sanitized codes. Transport failures
remain uncertain. A parser rejection records that the response arrived and retains
its HTTP status when supplied by the transport. A later matching or presentation
checkpoint error leaves the successful request's status as response_received.
The existing attempt ceilings, reserve-before-I/O behavior and exclusive report
reservation remain unchanged; there are no retries or refreshes.

The historical nine-attempt five-product report remains immutable. Its uncertain
Scotch detail operation (Walmart 47070933 / ASIN B0000AQOAB) has no retained HTTP
status, error code or failed response body. This fix cannot reconstruct them or
prove a parser cause. Do not repeat that operation, rerun the original CSV or
clear/change the source reservation to bypass it. Existing completed evidence,
source rows, observation times and SQL history are not rewritten.

Synthetic regressions cover HTTP 429 with sanitized QuotaExceeded/unknown codes,
HTTP 200 with wrong-ASIN parser rejection, timeout uncertainty, later matching
failure, response and search checkpoint failures, secret exclusion, retention of
all original rows, and exclusive replay refusal. No test accesses real credentials
or network endpoints. This focused change adds no recovery runner and performs
no historical evidence migration.
