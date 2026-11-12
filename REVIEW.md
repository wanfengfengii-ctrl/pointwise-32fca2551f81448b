# Scanlake reader release review

**Decision: BLOCK — the current reader must not be released.**

The released planner makes an exact metadata-only promise (`CONTRACT.md`
lines 90–102). The implementation does not meet it, and the gap is not
confined to the reported negation query. Two classes of blocking defects
exist:

1. **Row corruption (false negatives):** files that admit a predicate-TRUE
   logical row are pruned, and rows that are outside a delete's scope are
   suppressed or vice versa. The reported `incident` is one instance of a
   general three-valued-logic error.
2. **IO-budget violations (false positives):** files/deletes that cannot
   admit a predicate-TRUE row are opened. Several defects also violate the
   contract by opening empty files, empty deletes, or deletes whose scopes
   cannot overlap a matching row.

The public failure in `checks.py incident` remains visible and unchanged
(`SCAN_REVIEW_MISMATCH`, exit 1). `checks.py normal` still passes.

## Review method

- Business source (`scanlake/`), samples, and the original assertions in
  `checks.py` were **not modified**.
- Every `actual` observation in `docs/review-evidence.json` is produced by
  calling the unchanged `Source`, `Planner`, and `execute`.
- Every `expected` observation is produced by an **independent** oracle in
  `review_evidence.py`: a row-level evaluator plus an exact metadata
  satisfaction solver written from `CONTRACT.md`, not from the reader.
- `python3 review_evidence.py verify` replays every case against a fresh
  baseline, compares the saved evidence to that replay, re-derives every
  expected row/plan with the independent oracle, and checks all recorded
  source locations. It exits 0 only when everything agrees.
- `python3 review_evidence.py demo` prints the named cases, full fixture
  variants, requested calls, and actual/expected rows/plans/opens.

Evidence: 18 cases (13 defects, 5 positive controls).

## Blocking findings

### B1. Planner predicate abstraction is not three-valued or exact

**Root cause.** `possible()` answers only “some value allowed by this
metric can make this subexpression TRUE”. The planner then treats that as a
truth calculus:

- `not` is implemented as `not possible(child)`
  (`scanlake/predicate.py:47`). `NOT x` is TRUE when `x` is **FALSE**, not
  when `x` is merely possible. Possibility of `x` says nothing about
  certainty of `NOT x`.
- `and` is `possible(left) and possible(right)`
  (`scanlake/predicate.py:41-42`). Possibilities need not be jointly
  satisfiable (two contradictory equalities on the same stable ID).
- `or` (`scanlake/predicate.py:44-45`) is adequate for existence but the
  pair of may-TRUE/may-FALSE facts needed by an enclosing `not` is absent.
- A missing metric returns `True` (`scanlake/predicate.py:50-51`), even
  when the requested field is absent from the writer schema and therefore
  has a **fixed** `initial_default` value.
- A missing `null_count` is treated as zero (`scanlake/predicate.py:53`),
  which claims certainty (“no nulls”) where the contract says unknown.
- `lt` uses `expr[2] - 1` when `lower` is missing
  (`scanlake/predicate.py:60`); for a string field this raises `TypeError`.

**Trigger and observation (reported incident).**
`Planner.plan(1, 1, ["not", ["eq", "value", 20]], ["sensor", "value"])`
then `execute`: the planner reasons `eq value 20` is possible in old-a
(10 ≤ 20 ≤ 30), negates that to “impossible”, and emits `scan: []`.
Expected rows are `[{"sensor":"a","value":10}, {"sensor":"c","value":30}]`;
actual is `[]`, and `opened` is `[]` instead of `["old-a"]`.

**More instances.**

| Case | Trigger | Expected | Actual |
|---|---|---|---|
| `exact-and-shared-field` | `and(eq value 10, eq value 20)` on snapshot 1 | `scan: []`, no opens | selects and opens `old-a`; rows `[]` |
| `data-empty-file` | `eq sensor a` over `count: 0` file | `scan: []` | selects and opens `empty-a` |
| `isnull-missing-null-count` | `isnull value` where `null_count` is omitted | selects `null-a`, row `{sensor:a,value:null}` | `scan: []`, opens nothing |
| `data-own-partition` | `lt value 15` where own spec is `truncate:10` partition `[20]` | `scan: []` (values are 20..29) | selects and opens `part-a` |

`possible()` never receives the writer schema, the file's own count, or
the file's own partition; `Planner.plan` passes only the requested schema
(`scanlake/planner.py:18-20`). Consequently it cannot implement the
contract's admissible set at all, including initial defaults for fields
absent from the writer schema and the invariant that every row satisfies
the file's own partition.

**Minimal compatible fix.** Replace the private `possible` decision with an
exact `admits(file, writer_schema, requested_schema, predicate,
extra_scope=None)` implementing the solver in the revised design: build per
stable-ID domains from count/null_count/bounds/initial_default,
intersect the file's own partition preimages, enumerate value cells, and
decide joint 3VL satisfiability of the nested predicate. Keep the public
`Planner.plan` signature and plan shape unchanged. `lt` no longer needs
type-specific arithmetic once the solver is used.

### B2. Planner cache key omits snapshot and schema

**Root cause.** The key is `json.dumps([predicate, columns])`
(`scanlake/planner.py:12-14`). A plan pins its snapshot and requested
schema (`CONTRACT.md` line 15), but a long-lived `Planner` serves many
snapshots and schemas. Identical predicate text and column names therefore
return a plan from the wrong snapshot (or the wrong schema).

**Trigger and observation (single-factor).** One `Planner`:
`plan(1, 1, ["eq","value",21], ["sensor","value"])`, `execute`; then
`plan(2, 1, same predicate/columns)`, `execute`.
Expected second plan is snapshot 2 with
`old-a: deletes [global-b,day-c]` and `new-a: deletes [day-c]`, producing
`[{"sensor":"b","value":21}]`; actual second plan is the cached snapshot-1
plan (`snapshot: 1`, scan only `old-a`, no deletes), producing `[]`.
The second execute opens only `old-a` instead of the snapshot-2 payloads.
A fresh `Planner` for snapshot 2 produces the expected row, so snapshot
staleness is isolated from the projection defects.

**Minimal compatible fix.** Key on the full pinned identity:
`(snapshot_id, schema_id, canonical predicate, tuple(columns))`. Old cache
entries keyed only by predicate/columns cannot be identified with a
snapshot/schema and must be discarded on upgrade, not migrated or reread.

### B3. Delete sequence and scope are evaluated incorrectly

**Root cause 1: non-strict sequence.**
`if delete["sequence"] < data["sequence"]: continue`
(`scanlake/planner.py:25`) attaches a delete when `D.sequence >=
F.sequence`. The contract requires `F.sequence < D.sequence`; equal-sequence
data survives (`CONTRACT.md` lines 65–70).

Trigger `delete-equal-sequence`: data `same-seq` and `global-b` both have
sequence 2. Expected plan attaches no delete and returns
`[{"device":"b","value":100}]`; actual attaches `global-b`, returns `[]`.

**Root cause 2: raw partition-list equality across specs.**
`if delete["partition"] and delete["partition"] != data["partition"]:
continue` (`scanlake/planner.py:27`) compares stored lists and ignores the
specs that define their meaning. `CONTRACT.md` explicitly says equal lists
from different specs do not prove equal scope.

Trigger `delete-scope-evolved-spec`: data partition `[0]` is `day(at)`, while
delete partition `[0]` is `truncate:10(value)`. The data row has `at=100`,
`value=50`. Expected: delete does not attach; row
`[{"device":"x","value":50}]` survives. Actual: attaches, opens
`scope-del`, and returns `[]`.

**Root cause 3: no count/scope-admissibility check.**
The delete loop (`scanlake/planner.py:23-29`) never checks `count > 0` and
never asks whether the file can admit a predicate-TRUE row inside the
delete's scope. `CONTRACT.md` lines 95–98 require both.

Trigger `delete-zero-count`: expected no delete in the plan and `opened`
`["cnt-a"]`; actual attaches and opens `cnt-del` (count 0), violating the
IO promise.

**Minimal compatible fix.** Attach `D` to `F` iff
`D.count > 0`, `D.sequence > F.sequence`, and the same exact solver admits a
predicate-TRUE logical row of `F` also satisfying
`transform_{D.spec}(row) == D.partition`. Do not compare raw partition
lists; derive scope from `D.spec`. Keep plan `scan`/`deletes` shape.

### B4. Execution trusts planner attachment and omits row-level scope

**Root cause.** `execute` checks only whether the data row's key tuple is
in each attached delete's key set (`scanlake/reader.py:17-19`). It does not
re-check the delete sequence, the row-level scope
`transform_{D.spec}(row) == D.partition`, or the key's writer-schema
defaults. `CONTRACT.md` lines 97–99 require row-level scope and key checks
at execution.

**Trigger `delete-scope-execution`.** The planner legitimately attaches a
delete whose scope is `truncate:10(value) = [0]`. Two rows share key `k`,
with `value=5` and `value=50`. Expected: value 5 is suppressed, value 50
survives, rows `[{"device":"k","value":50}]`; actual suppresses both and
returns `[]`. Here expected and actual plans are identical, isolating the
execution defect from the planner.

**Root cause: delete keys ignore writer-schema defaults.**
`reader.py:14` builds delete keys with `row.get(str(fid))` from the raw
delete row. `CONTRACT.md` lines 39–44 say an ID absent from the writer
schema uses its immutable `initial_default`, including for deletion. The
correct key requires `values.logical(delete_row, delete_writer_schema,
field)`.

Trigger `delete-key-initial-default`: equality id 4 is absent from delete
writer schema 1; the delete row maps `4` to null. Expected logical key is
`initial_default` 7, suppressing the data row with id 4 = 7, rows `[]`.
Actual key is `None`, the row survives:
`[{"device":"k","value":10}]`.

**Minimal compatible fix.** In `execute`, for each attached delete:
strict sequence check; check the data row's `D.spec` transform equals
`D.partition`; materialize delete keys through `logical()` with the **delete
writer schema**; then perform the null-safe tuple membership test. Union
the results over deletes. Key order remains `equality_ids`.

### B5. Projection binds writer names and uses `write_default`

**Root cause.** `project` (`scanlake/values.py:15-22`) builds
`by_name` from the **writer** schema (`:16`), looks up the requested name in
that map (`:19`), and falls back to the requested field's `write_default`
(`:21`). The contract is the opposite:

- Names resolve in the **requested** schema to stable IDs
  (`CONTRACT.md` lines 43–44).
- Values are materialized by stable ID from the writer schema.
- An ID absent from the writer schema uses immutable `initial_default`,
  never `write_default` (`CONTRACT.md` lines 39–44, 30–32).

This also ignores renames and name reuse: schema 3 reuses `sensor` for ID 5,
while writer schema 1's `sensor` is ID 1.

**Trigger `projection-historical-default`.** Requested schema 2, predicate
`eq quality 7`, columns `device,quality`, snapshot 1. ID 4 is absent from
writer schema 1, so its logical value is `initial_default` 7. Expected
`[{"device":"a","quality":7},{"device":"b","quality":7},
{"device":"c","quality":7}]`; actual projects `write_default` 9, evaluates
the predicate false, and returns `[]`.

**Trigger `projection-name-reuse`.** Requested schema 3, `isnull sensor`.
`sensor` resolves to ID 5 there; ID 5 is absent from writer schema 1 and is
therefore null for every row. Expected three `{"sensor":null}` rows;
actual binds writer schema 1's name `sensor` to ID 1 and returns `[]`.

**Minimal compatible fix.** Resolve every requested name with
`values.resolve(requested_schema, name)` to a stable ID, then materialize
`logical(raw, writer_ids, field_definition)`; if absent from the writer,
return `fields[id]["initial_default"]`. Do not consult writer names or
`write_default` anywhere in the read path. `logical()` itself
(`values.py:9-12`) already has the correct stable-ID rule for predicates,
transforms, and data delete keys.

### B6. The maintained design document contradicts the contract

`docs/reader-design.md` is not merely incomplete; several statements are
the direct causes of the defects above:

- cache “by predicate and selected columns” → omits snapshot/schema (B2);
- “metric inclusive projection” with no tri-state or exactness condition
  (B1);
- “matching partition lists identify the same scope even if specs evolved”
  → false (B3);
- “delete at or after” → should be strictly after (B3);
- “new columns use requested write default” → should be
  `initial_default` (B5);
- “names are the projection binding” → should be requested-schema name →
  stable ID (B5);
- “sample append-only regression is the release gate” → the gate must cover
  nested predicates, missing statistics, and evolved specs per
  `CONTRACT.md` lines 100–102.

The revised `docs/reader-design.md` delivered with this review replaces it
with exact conditions, pseudocode, a correctness argument, and explicit
plan/cache rules.

### B7. String `lt` can raise

`scanlake/predicate.py:60` computes `expr[2] - 1` whenever `lower` is
missing. When the field type is `string`, this raises `TypeError` during
planning. `CONTRACT.md` permits `lt` with a literal of the field type and
does not restrict it to `int`. This is a release blocker even though it is
not a wrong-row counterexample (per the evidence interface an exception is
not counted as one).

**Trigger.** Construct a variant of the sample with data file `str-a` whose
metric for string field 1 is `{"upper":"z","null_count":0}` (no lower),
`count:1`, row `{"1":"m","2":0,"3":1}`, then call
`Planner(Source(variant)).plan(20, 1, ["lt","sensor","z"],
["sensor","value"])`. Expected: metadata admits a string below `z`, the
file is selected, and execution returns `[{"sensor":"m","value":1}]`.
Actual: `TypeError: unsupported operand type(s) for -: 'str' and 'int'`
from `predicate.py:60` (reproduced with `python3 -I`). The exact solver
from B1 removes the arithmetic. If `possible` is retained as a
compatibility shim, use a type-aware unbounded sentinel instead of
`literal - 1`.

## Evidence index

| Case | Class | Shows |
|---|---|---|
| `incident-not-eq` | defect | reported negation prune: expected `a:10,c:30`, actual `[]` |
| `exact-and-shared-field` | defect | AND of contradictory tests must prune; actual opens `old-a` |
| `projection-historical-default` | defect | `initial_default` 7 vs `write_default` 9; actual `[]` |
| `projection-name-reuse` | defect | name reuse ID 5 vs writer `sensor` ID 1; actual `[]` |
| `cache-snapshot-key` | defect | same Planner returns snapshot-1 plan for snapshot 2 |
| `delete-equal-sequence` | defect | strict sequence; expected one row, actual `[]` |
| `delete-scope-evolved-spec` | defect | day(at) vs truncate(value) scopes; expected row, actual `[]` |
| `delete-scope-execution` | defect | identical plans, execution suppresses out-of-scope row |
| `delete-zero-count` | defect | empty delete must not be attached/opened |
| `data-empty-file` | defect | count-0 data file must not be opened |
| `isnull-missing-null-count` | defect | missing `null_count` is unknown; actual prunes null row |
| `delete-key-initial-default` | defect | delete key must use `initial_default`; actual key `None` |
| `data-own-partition` | defect | own partition narrows admissible values; actual opens `part-a` |
| `positive-prune-lt` | positive | legitimate pruning to `old-a`, reads only it |
| `positive-prune-eq-multifile` | positive | eq 99 prunes to `next` only |
| `positive-not-prune` | positive | complement still prunes using bounds |
| `positive-delete-pre-deletion` | positive | stats are pre-deletion; candidate retained, rows deleted |
| `positive-plan-reexec` | positive | same-key cache reuse and earlier plan re-execution |

The positive controls prove the review does not “pay for correctness by
full scans”: legitimate pruning and plan reuse still occur.

## Single-factor isolation and combination masking

Each defect has a case where the expected and actual **plans and opens are
identical**, leaving one independent failure:

- `delete-scope-execution`: same plan, same opens; only execution differs
  (`[{"device":"k","value":50}]` vs `[]`), isolating the missing row-level
  scope check.
- `projection-historical-default` and `projection-name-reuse`: same plan,
  same opens; only projected rows differ, isolating stable-ID/default
  materialization.
- `delete-key-initial-default`: same plan, same opens; only rows differ,
  isolating delete-key logical materialization.
- `cache-snapshot-key`: a fresh `Planner` on snapshot 2 returns the
  expected row, so the shared-`Planner` failure is the cache key, not
  selection or projection.
- `positive-*` controls show that the negation, pruning, deletion, and
  cache mechanisms still work where their preconditions hold, so the
  failures are not a blanket “planner broken” claim.

Masking is also demonstrated directly. In `delete-scope-evolved-spec` the
planner's wrong raw-list equality (`planner.py:27`) causes an attachment,
and then the execution key check (`reader.py:18-19`) suppresses the row;
fixing only the key logic would still leave the avoidable `scope-del` open
and the wrong plan. Conversely, `delete-scope-execution` has a correct
attachment but wrong execution, proving the two layers have independent
necessary conditions. `exact-and-shared-field` and `data-own-partition`
happen to return zero rows through the residual predicate, which would mask
the planner defect if only output rows were asserted; the evidence compares
full plans and `opened`, so the avoidable payload opens are visible.

## Minimal compatible remediation order

1. Land the exact satisfaction solver and make the planner use it for both
   data selection and delete attachment (B1, B3). Public signatures and
   plan JSON remain unchanged.
2. Include snapshot and schema in the cache key; drop old-keyed entries on
   upgrade (B2). Plans remain self-contained, so executing an earlier plan
   after later `plan` calls remains valid.
3. Fix delete attachment: `count > 0`, strict sequence, and exact
   scope-admissibility derived from `D.spec` (B3).
4. Add execution-side row scope and logical delete-key checks (B4).
5. Project through requested-name → stable-ID → `initial_default` only
   (B5).
6. Remove type-unsafe arithmetic from `lt` (B7) and replace the design
   document (B6).
7. Require `python3 checks.py normal`, keep `python3 checks.py incident`
   visible during review, and require `python3 review_evidence.py verify`
   before release.

No new index, payload rewrite, or snapshot migration is needed; all fixes
are planner/reader logic and cache invalidation.

## Artifact integrity

- `scanlake/`, `samples/evolution.json`, and `checks.py` are unchanged.
- `docs/reader-design.md` is the maintained (non-normative) design.
- `docs/review-evidence.json` and `review_evidence.py` are the reproducible
  evidence required by `CONTRACT.md` lines 104–120.
- `.pointwise-runtime.json` now runs the contract evidence interface for
  `verify` and `demo`; the standalone `checks.py normal` gate is unchanged.
