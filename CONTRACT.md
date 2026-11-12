# Scanlake: immutable lake-table reader
Python 3 standard library; repository files are the complete fixture. This is
an in-process reference reader, not a file-format SDK or a remote service.
docs/reader-design.md is the current release note, not a normative contract.
The following rules are normative.

## Public entry points
python3 -m scanlake samples/evolution.json 1 1 '["lt","value",25]' sensor,value
prints one JSON object with plan, rows and opened. Shell quotes here only
illustrate JSON arguments; subprocess callers pass the predicate as one argv.
Source.load(path), Planner(source).plan(snapshot_id, schema_id, predicate,
columns), execute(source, plan) are the real in-process entry points. The same
Planner may serve many snapshots and requested schemas. execute can run an
earlier returned plan after later plan calls. A plan pins its requested
snapshot, schema, predicate and columns. Source.rows records actual payload
opens, including delete payloads, in opened. metadata never reads row payloads.
Source stores a deep copy; a Source document is immutable during its lifetime.

normal: python3 checks.py normal must exit 0 with NORMAL_REGRESSION_OK.
incident: python3 checks.py incident currently exits 1 with
SCAN_REVIEW_MISMATCH; it compares the reported negation query with the two
surviving rows. Keep this public failure visible during review.
demo: python3 checks.py demo shows real normal and incident results, exits 0.

## Dataset JSON
fields maps stable numeric field IDs (as string keys) to id, type and
initial_default. type is int or string; null is allowed for both. Integers
are exact and unbounded, excluding bool. Defaults have the declared type.
schemas maps IDs to ordered lists of {id,name,write_default}. Field IDs
never change meaning or type. Names are unique within a schema. A name can be renamed, removed, and later
reused by a different ID. Schemas can drop fields. initial_default is fixed
for a field's lifetime; write_default can change between schemas.
specs maps IDs to ordered lists of {source,transform}, where source is a
field ID. Transforms: identity (either type); day (floor division of integer seconds by
86400); truncate:N (integer x - x % N for positive N). Every transform
preserves null; day and truncate apply only to int fields. Empty spec is unpartitioned.
files maps globally unique immutable paths to metadata plus rows.
Data metadata: kind=data, schema, spec, partition, sequence, count, metrics.
Each data row maps writer-schema field-ID strings to values. Omission of
an ID present in writer schema is null. An ID absent from writer schema has
its immutable initial_default, including when used by predicates, partition
transforms or deletion. write_default is only a producer-side default:
existing physical files are never reinterpreted with it. Projection resolves
requested names to stable IDs, then materializes these logical values.
Rows preserve duplicates and physical order. Each file partition equals
the transforms of every logical row under its own spec.
sequence is a nonnegative data sequence number, not snapshot ID, path order
or file addition order. It may equal another data or delete sequence.
An equality file has kind=equality, schema, spec, partition, sequence, count,
metrics={}, equality_ids, rows. equality_ids is a nonempty ordered list of
distinct stable IDs; it may include fields absent from requested schema.
Delete rows map exactly these IDs to typed values or null. Equality is
null-safe on every component. The delete schema identifies the writer but
does not rebind IDs by names. The partition is the delete's applicability
scope, not a transform of its key tuple; partition source fields need not
occur in equality_ids.
snapshots maps IDs to {data:[paths],deletes:[paths]}. These lists alone define
file membership. All paths and schema/spec IDs resolve. Only legal datasets
are inputs; validation of malformed metadata is outside this review.

## Read semantics
For each data row in snapshot file order and physical row order:
materialize logical values by stable ID, suppress applicable deletes, then
evaluate the requested predicate and project selected columns.
Delete D suppresses a row from F iff F.sequence < D.sequence, the logical
row transformed under D.spec equals D.partition, and the null-safe equality
tuple occurs in D.rows. An unpartitioned delete has global scope. This rule
also applies across evolved specs; equal partition lists from different
specs do not by themselves prove equal scope. Newer or equal-sequence data
survives an older or equal-sequence delete. Multiple deletes form a union.
There are no position deletes, row updates or snapshot expiration.

Predicates are JSON arrays: ["eq",name,literal], ["lt",name,literal],
["isnull",name], ["not",expr], ["and",left,right], ["or",left,right].
Names resolve in requested schema, columns is an ordered nonempty name list.
Literals have the field type and are non-null. Comparison with null yields
UNKNOWN; isnull is two-valued; NOT UNKNOWN=UNKNOWN; FALSE AND UNKNOWN=FALSE;
TRUE OR UNKNOWN=TRUE; all other cases follow SQL three-valued logic. Emit a
row iff predicate is TRUE. Result order is defined above; no deduplication.

metrics is keyed by field-ID strings. count is exact physical row count.
A missing metric, missing null_count, lower or upper means unknown. Present
null_count is exact. Bounds are inclusive, type-correct conservative bounds
on all non-null physical values, possibly loose. Nulls are not bounded.
Metrics describe only IDs present in the writer schema. Fields absent from
a writer schema have no physical metric; logical defaults still determine
their predicate values. Empty files are legal.
Statistics describe physical rows before deletion. They cannot assume a
row survives or a delete removes all rows. Planning must not open payloads.
The released planner promises exact metadata-only candidate selection: select
a data file iff its metadata admits a logical row making the predicate TRUE.
Here "admits" quantifies over all payloads consistent with that file's count,
bounds, null counts, writer schema and own partition, not the actual hidden
rows. Do not exploit correlations not recorded in metadata. For a selected
data file, attach a delete iff its count is positive, its sequence is newer,
and those same constraints admit a predicate-TRUE row inside the delete's
scope. Delete keys are unknown to the planner. An attached delete still
requires row-level scope and key checks at execution. This exactness promise
is the established IO budget: false-negative candidates corrupt rows and
unnecessary candidates cause avoidable payload opens. Arbitrary nested
predicates, missing statistics and evolved specs remain legal; the release
gate covers them. No new index, payload rewriting or migration is needed.

## Maintenance artifact interface
REVIEW.md is the release review; docs/reader-design.md is the maintained
design. Evidence is reproduced by python3 review_evidence.py verify and
python3 review_evidence.py demo. verify exits 0 only when fresh baseline
execution reproduces the reviewed observations and the saved evidence
agrees with them; an exception is not an incorrect-row counterexample.
demo prints the named cases, requested reads, actual and expected rows.
docs/review-evidence.json is an object with cases, a list of objects:
id (unique string), description, calls (ordered plan/execute arguments),
expected (ordered result lists), actual (ordered result lists),
expected_plans and actual_plans (ordered full plan objects for plan calls),
opened (actual payload paths per execute), locations (objects with path,
line and quoted source text). Record calls explicitly; repeated calls on
one Planner are distinguishable from fresh Planner instances.
The evidence script may embed fixture variants or construct them from the
provided sample; print those complete variants in demo so they can be rerun.
No report-text-only checker counts as business verification.
