# Usage snapshot protocol, version 1

This private protocol uses the existing Unix socket and `/v1/call` envelope.
It does not add a public upload endpoint or an authentication credential.
All three snapshot operations require `actor_kind="producer"` and `user_id=""` in the trusted identity.
Each call needs a fresh, operation-specific identity with a lifetime of at most five seconds.
A user identity cannot call these operations. A producer cannot call `usage.summary`.

## Activation and daily coverage

1. Call `usage.begin` before reading the source database.
2. Supply `coverage={"from": ..., "to": ...}` with whole UTC days, using `[from,to)`.
3. The first accepted call stores `activated_at` and `collection_start` in PostgreSQL.
4. `collection_start` is the next UTC midnight, strictly the following day, including activation at midnight.
5. Before that boundary, the result has `status="waiting"`, `revision=0`, `coverage=null`, and `expires_at=null`.
6. Do not read or stage a source snapshot for a waiting result.
7. After that boundary, Go clips the requested start to `collection_start` and returns the effective coverage.
8. Read only that returned coverage. Do not infer increments from the activation day's aggregate.

The result survives a process restart. Python must not maintain a separate activation boundary.
The ready lease lasts 45 seconds. Only one active lease exists per organization.
Revisions increase durably. There is no lease renewal endpoint.
After expiry, begin a new revision and read the source again.
An exact repeated begin request returns its active lease while the lease remains valid.
A different begin request conflicts while that lease is active.
The lease controls concurrent publication. It is not an authentication secret.

Both boundaries must be UTC midnight. Coverage can include the current day through next midnight.
It cannot include a later day or a date earlier than the most recent 90 UTC dates.
The producer must not upload a row outside the returned coverage.

## Source rows and batches

The source row ID is a positive signed 64-bit integer. It is independent of `user_id`.
All four token counts are nonnegative signed 64-bit integers.
The wire stores USD cents as a string with exactly six fractional digits.
The source range is `0.000000` through `999999999999.999999`.
Reject overflow, non-finite values, and extra decimal places. Never convert through a float.
Read a Decimal-preserving SQL value in the future source adapter.

Source `actor_kind` is `USER` or `SYSTEM`. It is separate from the transport actor.
A `USER` row has null `system_attribution`. Its `user_id` may be null after user deletion.
A `SYSTEM` row has null `user_id`, `incognito=false`, and `ATTRIBUTED` or `UNATTRIBUTED` attribution.
Incognito is a separate privacy dimension. It does not change USER into SYSTEM.
The model and flow are nonempty strings. Provider may be empty.
Each has at most 512 Unicode characters. NUL and invalid UTF-8 are rejected.

Send `usage.stage` with the returned lease and `{index,rows,digest}`.
Batch indexes start at zero. The complete manifest must list contiguous indexes in order.
Do not send empty batches. Use an empty complete manifest to represent a source reset.
Row order within each batch is significant for the digest.
A source row ID must be unique across the full revision.
An exact stage retry returns the original acknowledgment without adding rows.
A conflicting stage or a receiver-detected limit violation invalidates that revision.

Each batch has at most 1,000 rows and 1 MiB of canonical batch JSON.
Every complete transport envelope also has the existing 1 MiB limit.
Leave room for the envelope and lease when choosing a batch size.
A full revision has at most 100,000 rows and 64 MiB of canonical batch JSON.
The acknowledgment's `byte_count` is authoritative for the manifest.
It includes the batch digest and JSON field names, not the transport envelope.
Oversized transport bodies are rejected before dispatch. The producer must abandon that revision on any failed stage.
Never omit failed batches and label the remaining subset complete.

## Canonical batch digest

Use SHA-256. Emit lowercase hexadecimal.
The preimage starts with these literal ASCII bytes, including the final NUL:

`orgmesh.usage.batch.v1\x00`

Encode every subsequent field as a four-byte unsigned big-endian UTF-8 byte length, followed by its UTF-8 bytes.
A null field is exactly `ff ff ff ff`, with no following bytes.
An empty string is exactly `00 00 00 00`. It is distinct from null.
There is no BOM, delimiter, newline, Unicode normalization, or JSON escaping in this preimage.
Use decimal integers without a sign or leading zeros. Zero is `0`.
Booleans are the ASCII strings `true` and `false`.
UTC timestamps are exactly `YYYY-MM-DDTHH:MM:SSZ`, with no fraction. All row windows are midnight.
Costs retain exactly six fractional digits, with no leading integer zeros except zero itself.

First encode `index`, then the number of rows.
For each row, in the supplied row order, encode these fields:

1. `source_row_id`
2. `actor_kind`
3. `user_id`, nullable
4. `system_attribution`, nullable
5. `window_start`
6. `model`
7. `flow`
8. `provider`
9. `incognito`
10. `input_tokens`
11. `output_tokens`
12. `cache_read_tokens`
13. `cache_creation_tokens`
14. `cost_cents`

The batch's `digest` field is not part of its preimage.

### Canonical byte accounting

The receiver measures the compact JSON representation of the typed batch, including its digest.
The outer field order is `index`, `rows`, `digest`.
The row field order is the 14-field order above.
Keys and strings use JSON double quotes. There is no whitespace between JSON tokens or trailing newline.
Integers use base-10 JSON integer literals; booleans and null use standard JSON literals.
Timestamps use the exact UTC spelling above. Nullable UUIDs are lowercase strings or null.

Match Go's standard JSON string escaping:
- Escape quote and backslash, and use `\b`, `\f`, `\n`, `\r`, `\t` for those controls.
- Encode other U+0000–U+001F controls as lowercase `\u00xx`.
- Escape `<`, `>`, `&`, U+2028, and U+2029 as lowercase six-byte `\uxxxx` sequences.
- Keep all other Unicode characters as their original UTF-8 bytes. Do not escape `/`.

In Python, construct dictionaries in the stated field order, then use
`json.dumps(batch, ensure_ascii=False, separators=(",", ":"), allow_nan=False)`.
Replace the five characters `<`, `>`, `&`, U+2028, and U+2029 with their `\uxxxx` spelling.
Measure the resulting UTF-8 bytes. Do not measure the binary digest preimage or the transmitted envelope.
Alternatively, use the receiver's acknowledgment directly without calculating this size locally.

## Canonical manifest digest and publication

Send `usage.commit` with the lease and a manifest containing:
`complete`, `batches`, `total_rows`, `total_bytes`, and `digest`.
Only `complete=true` permits replacement.
Each `batches` item is the exact stage acknowledgment: `index`, `digest`, `row_count`, `byte_count`.
For an empty snapshot, use `batches=[]`, `total_rows=0`, and `total_bytes=0`.

The manifest preimage starts with literal ASCII `orgmesh.usage.manifest.v1\x00`.
Use the same length-prefixed field encoding.
Then encode, in order:

1. Lease `revision`
2. Effective coverage `from`
3. Effective coverage `to`
4. `true`
5. `total_rows`
6. `total_bytes`
7. Number of batch acknowledgments
8. For each acknowledgment in index order: `index`, `digest`, `row_count`, `byte_count`

The manifest digest does not include itself. It does not include the lease expiry or identity timestamps.
The tenant is enforced separately by every database key, lookup, and trusted context.
The supplied lease still must exactly match the persisted lease.

Publication holds the organization state row lock. It rechecks the lease and all staged row digests.
It verifies batch order, counts, sizes, and the whole manifest digest.
It replaces only the complete covered projection and updates the publication receipt and cursor in one transaction.
A crash or failed transaction leaves the prior projection intact.
A complete empty snapshot removes covered rows. It does not remove other days.
A source ID cannot move a row out of an uncovered day through an upsert.
An exact retry of the latest issued, already published revision returns its original receipt, even after expiry.
Once a newer revision starts, an older commit is fenced out.
A changed digest for the same published revision conflicts.
Staged data and batch receipts are retained. No retention cleanup job is introduced.

## Shared fixture

`fixtures/usage-digest.json` fixes both preimages, both digests, a lease, batch, acknowledgment, and manifest.
It includes Chinese text, an emoji, an accented character, HTML-sensitive characters, U+2028, nulls, an empty provider, and large numbers.

- Batch SHA-256: `4033481101752459c8ae6026a8f848fba74ae4bdff4a345460074f47de2d3b39`
- Canonical batch JSON size: `742` bytes
- Manifest SHA-256: `4481da090ed44fa49b3135c7aedeed1da293427ccb8bf0f4753939814987ba55`

Go tests verify the independently constructed fixture. Python tests verify the same bytes and named wire models.
Task 5 must use this fixture before it writes source-reading or scheduling code.

## Summary and UI handoff

`usage.summary` accepts whole UTC dates with `[start,end)` boundaries.
The BFF default selects today minus 29 dates through next UTC midnight.
The maximum selects the most recent 90 UTC dates.
Current-day values are daily source aggregates as of publication. They are not exact intraday event intervals.

The response discloses activation, collection start, effective coverage, publication time, and revision.
It clips only a leading unpublished prefix. An internal gap or uncovered trailing day is unavailable.
Before collection starts, the status is waiting. Before a valid publication, it is unavailable.
A complete published empty interval yields `groups=[]` with valid published coverage.
Waiting and unavailable results have no groups or fabricated totals.
For a range with several publications, `published_at` is the oldest contributing publication time.
The status is stale only when that time is more than 120 seconds old.
Refreshing one day cannot make an older day appear fresh.

The optional `group_by` query selects `day`, `model`, or `flow`. The default is `day`.
Each group includes `value`, `category`, `incognito`, and its exact `totals`.
For day grouping, `value` is `YYYY-MM-DD`. Other values are the source model or flow string.
Groups separate USER, SYSTEM_ATTRIBUTED, and SYSTEM_UNATTRIBUTED.
USER has a separate `incognito` boolean group.
There is no grand total across USER and SYSTEM. Their source money may overlap.
Do not add those categories together in the UI before source overlap has been verified.
The response has at most 1,000 groups and at most 1 MiB of JSON.
If either limit is exceeded, the whole response is unavailable. It is never truncated.
Narrow the date range or choose day grouping. Diagnostics record only a bounded limit reason.
Summary token totals are decimal integer strings. Total tokens equal input plus output only.
Cache-read and cache-creation counts remain separate and are not added again.
Costs are exact six-place USD-cents strings. They are source estimates, not settled charges.
The response always says that zero may mean missing pricing.
The Chinese UI must display “0可能表示缺少定价”. Do not label a zero estimate free or settled.
Summary responses contain no source row IDs, user IDs, or email fields.
`fixtures/usage-summary.json` fixes the grouped response contract for Python, Go, and the UI.

The current user-facing Python client still rejects producer identities.
Task 5 supplies the authorized producer path and source adapter. This task does not implement them.
