# Scanlake reader design (maintained)

`CONTRACT.md` is normative. This document is the maintained design and
release note; where they differ, the contract wins. The design below
describes the required behaviour of the reader, not the current
implementation. The release review of the current implementation is in
`REVIEW.md`.

## 1. Invariants

- Field IDs are stable forever. A field's type and `initial_default` never
  change. A name may be renamed, removed, and later reused by a different
  stable ID.
- `write_default` is producer-side only. The read path never reads it.
- Every logical value is materialized by stable ID. A requested name is
  resolved in the requested schema to a stable ID; writer-schema names are
  never used as projection bindings.
- If a stable ID is present in the writer schema and omitted from a physical
  row, its value is `null`. If it is absent from the writer schema, its
  value is `initial_default`, including for predicates, partition
  transforms, and deletion keys.
- Metadata reads never open payloads. `Source.rows` records every actual
  data or delete payload open in `opened`.
- Statistics describe physical rows before deletion. They never imply that
  a row survives a delete.

## 2. Logical row materialization

For a raw row `r` of file `F` with writer schema `W`:

```
value(fid) =
    r[str(fid)]                 if fid ∈ W
    initial_default(fid)        otherwise
```

All planner and execution logic below operates on these logical values.
Transforms preserve `null`; `day` and `truncate:N` apply only to `int`.

## 3. SQL three-valued predicate semantics

Atom evaluation:

| atom | value | result |
|---|---|---|
| comparison (`eq`, `lt`) | null | UNKNOWN |
| comparison | non-null | TRUE/FALSE |
| `isnull` | any | TRUE/FALSE |

Boolean combination:

| expression | result |
|---|---|
| `NOT UNKNOWN` | UNKNOWN |
| `NOT TRUE` / `NOT FALSE` | FALSE / TRUE |
| `FALSE AND x` | FALSE |
| `TRUE AND x` | x |
| otherwise `AND` | UNKNOWN if either is UNKNOWN, else TRUE |
| `TRUE OR x` | TRUE |
| `FALSE OR x` | x |
| otherwise `OR` | UNKNOWN if either is UNKNOWN, else FALSE |

A row is emitted iff the requested predicate is **TRUE**. UNKNOWN is not a
match. This distinction is why a planner needs both *may be TRUE* and *may
be FALSE*; “may be TRUE” alone is insufficient under `NOT`.

## 4. Admissible logical rows of a data file

The planner's promise is exact metadata-only selection: a data file is a
candidate iff its **metadata admits a logical row whose predicate is
TRUE**, quantifying over all payloads consistent with:

- the file's exact count `n`,
- per-field bounds and null counts,
- the writer schema,
- the file's own spec and partition.

No cross-field correlation is recorded, so any tuple of individually
admissible per-field values is jointly admissible.

### 4.1 Per-field domain

For data file `F`, writer schema `W`, count `n > 0`:

```
D(fid):
  if fid ∉ W:
      return { initial_default(fid) }            # a single fixed value

  m = F.metrics.get(fid)
  if m is missing:
      return nullable × (-∞, +∞)                 # entirely unknown

  null_ok  = m.null_count is missing or m.null_count > 0
  nonnull_ok = m.null_count is missing or n - m.null_count > 0
  interval = [m.lower if present else -∞,
              m.upper if present else +∞]        # inclusive
  return null_ok ? interval : interval only
```

A present `null_count` is exact; a missing `null_count`, `lower`, or
`upper` is unknown. `n = 0` admits no row at all. `count` is exact.

### 4.2 Partition constraint

Every logical row of `F` satisfies `transform_{F.spec}(row) ==
F.partition` (`CONTRACT.md`). For a spec entry at position `i` with source
field `s` and transform `T`, intersect `D(s)` with the preimage of
`F.partition[i]`:

```
preimage(identity, t)   = {t}                       # t may be null
preimage(day, t)        = [t*86400, t*86400+86399]  # t non-null int
preimage(truncate:N, t) = [t, t+N-1]                # t non-null
                          if t % N == 0; else ∅
                          # t null -> {null}
```

`day` and `truncate:N` only constrain `int` fields. Multiple entries on the
same source field are intersected.

Let `A(F)` be the product of the resulting per-field domains. By the
no-correlation rule every tuple in `A(F)` is realizable by some payload
consistent with the metadata, and every payload row belongs to `A(F)`.

### 4.3 Delete scope

For an equality delete `D`, its scope is a predicate on a logical row, not
a stored-key list:

```
scope_D(row) := transform_{D.spec}(row) == D.partition
```

An empty spec gives the global scope (`[] == []`). Partition lists from
different specs are never compared directly; only the transformed values
are.

## 5. Exact selection conditions

### 5.1 Candidate data file — necessary and sufficient

For requested schema `S_req` and predicate `P`:

```
select F  ⟺  F.count > 0
             ∧ ∃ row ∈ A(F) : eval3(P, row) = TRUE
```

No other constraint is allowed. In particular, any strategy that selects a
file whenever it *might* contain any predicate-TRUE value, without enforcing
joint satisfiability of nested `and`/`not`, is not exact.

### 5.2 Attached delete — necessary and sufficient

For a data file `F` already selected:

```
attach(F, D) ⟺
    D.count > 0
    ∧ F.sequence < D.sequence
    ∧ ∃ row ∈ A(F) :
          eval3(P, row) = TRUE
          ∧ scope_D(row)
```

Delete keys are unknown to the planner, so key equality is deliberately not
part of this condition. It is checked at execution. A delete whose scope
cannot contain any predicate-TRUE admissible row must not be attached; it
would only cause an avoidable payload open. A delete with count 0 has no
keys and must not be attached.

### 5.3 Execution

For each data file in snapshot order and each physical row in order:

```
logical   = materialize the row by stable ID (section 2)
suppress  = ∃ attached D :
      F.sequence < D.sequence
      ∧ scope_D(logical)
      ∧ key_D(logical) ∈ keys(D)
emit iff not suppress and eval3(P, logical) = TRUE
project requested columns by requested-name -> stable ID -> logical value
```

`key_D(row)` is the tuple, in `equality_ids` order, of logical values from
`row` under `D`'s writer schema. `keys(D)` is the set of tuples
materialized the same way from every delete row. Equality is null-safe
component-wise: `null` equals `null`; Python tuple equality provides this.
Multiple deletes are a union. Execution must repeat the scope and key
checks even when the planner attached the delete, because the planner
does not see keys and quantifies over all admissible payloads, not the
hidden rows.

## 6. Executable-level pseudocode

The following is the required planner decision procedure. It is exact for
arbitrary legal nested predicates, including missing statistics, initial
defaults, and evolved specs.

```
def plan(snapshot_id, schema_id, P, columns):
    key = (snapshot_id, schema_id, canonical(P), tuple(columns))
    if key in cache: return deepcopy(cache[key])

    S_req = requested_schema(schema_id)
    name_to_id = {f.name: f.id for f in S_req}
    scan = []

    for path in snapshot(snapshot_id).data:
        F = metadata(path)
        if not admits(F, S_req, name_to_id, P): continue

        attached = []
        for dpath in snapshot(snapshot_id).deletes:
            D = metadata(dpath)
            if D.count <= 0: continue
            if not (F.sequence < D.sequence): continue
            if not admits(F, S_req, name_to_id, P, scope=D): continue
            attached.append(dpath)
        scan.append({"path": path, "deletes": attached})

    plan = {"snapshot": snapshot_id, "schema": schema_id,
            "predicate": deepcopy(P), "columns": list(columns),
            "scan": scan}
    cache[key] = deepcopy(plan)
    return plan


def admits(F, S_req, name_to_id, P, scope=None):
    if F.count == 0: return False
    W = [f.id for f in schema(F.schema)]           # writer schema IDs

    dom = {}
    needed = atom_fields(P, name_to_id) ∪ spec_sources(F.spec)
    if scope is not None: needed |= spec_sources(scope.spec)
    for fid in needed:
        dom[fid] = logical_domain(F, W, fid)       # section 4.1
        if empty(dom[fid]): return False

    for i, (source, transform) in enumerate(F.spec):
        dom[source] = dom[source] ∩
            preimage(transform, F.partition[i], type(source))
        if empty(dom[source]): return False

    if scope is not None:
        for i, (source, transform) in enumerate(scope.spec):
            dom[source] = dom[source] ∩
                preimage(transform, scope.partition[i], type(source))
            if empty(dom[source]): return False

    cells = {}
    for fid in atom_fields(P, name_to_id):
        literals = {literal | ("eq" or "lt", name) in P, resolved to fid}
        cells[fid] = enumerate_cells(dom[fid], literals, type(fid))
        if cells[fid] is empty: return False

    return SAT3(P, sorted(atom_fields(P, name_to_id)), cells, name_to_id)


def logical_domain(F, W, fid):
    # section 4.1, including:
    #   fid ∉ W  -> singleton initial_default
    #   metric missing -> nullable × unbounded
    #   null_count present is exact
    #   bounds are inclusive; missing side is unbounded


def preimage(transform, required, field_type):
    # section 4.2; null required -> {null};
    # day/truncate on non-int -> empty; bad truncate remainder -> empty


def enumerate_cells(domain, literals, field_type):
    # Each field is represented by finitely many values that cover every
    # distinct truth vector of the field's atoms:
    #   * null, if the domain admits null;
    #   * a singleton fixed default;
    #   * the inclusive bounds;
    #   * each literal in the domain;
    #   * for int: literal-1 and literal+1 when in the domain (the order on
    #     ints is discrete);
    #   * for string: the empty string, literal + "\x00", and a constructed
    #     strict between value for a non-empty gap between adjacent literals
    #     (the lexicographic order on strings is not dense).
    # Any other allowed value has the same atom truth vector as one cell.


def SAT3(P, fields, cells, name_to_id):
    # Backtracking over fields with concrete representative values.
    # A partial assignment can be pruned with 3VL/abstract evaluation when
    # the formula can no longer become TRUE; the complete assignment is
    # evaluated with section 3.  A DPLL/Tseitin implementation is an
    # acceptable optimization with the same semantics.
    for assignment in product(cells[f] for f in fields):
        if eval3(P, assignment, name_to_id) is TRUE: return True
    return False
```

## 7. Correctness argument

**Lemma 1 (per-field domains).** For `n > 0`, a value `v` can appear in a
payload consistent with the field metadata iff `v ∈ D(fid)` as defined in
4.1. For a field absent from the writer schema, the only value is
`initial_default`. For a present field, a null occurrence is possible iff
`null_count` is missing or positive; a non-null occurrence is possible iff
`null_count` is missing or `n - null_count > 0`; any non-null value in the
inclusive bound interval is allowed because bounds are conservative. This
proves both directions.

**Lemma 2 (partition preimage).** The equalities in 4.2 are algebraic
consequences of the three transforms; `null` is preserved by all of them.
Thus `row` satisfies its file/delete partition equation iff every spec
source field lies in the intersected preimage set, and the intersection is
empty exactly when no row can satisfy it.

**Lemma 3 (joint admissibility).** No metadata records a cross-field
correlation. For any tuple in the product of the per-field domains that
respects each field's own null/non-null possibility, choose the required
null positions and values; the per-field null counts are independently
satisfiable and no constraint couples two fields. Therefore the tuple is
realizable by a payload row, and conversely every payload row lies in the
product. This is exactly `A(F)`.

**Lemma 4 (cell exhaustiveness).** The cells in `enumerate_cells` partition
each domain into regions on which every atom on the field has constant
truth. For ints, the atoms change only at literals, and `literal±1` covers
the adjacent regions; for strings, the constructed between values cover
every non-empty lexicographic gap and the empty string/`literal+"\x00"`
cover the unbounded sides. A cell that is empty is omitted. Therefore every
value has an atom-truth-equivalent representative in the cell set.

**Theorem 1 (data selection).** If `admits` returns True, its SAT witness
gives a tuple in `A(F)` by Lemmas 1–3, and `eval3(P)=TRUE` by construction;
Lemma 3 realizes that tuple as an admissible row, so the metadata admits a
TRUE row. Conversely, if an admissible TRUE row exists, each of its field
values lies in a cell with the same atom truth (Lemma 4), so the
corresponding cell tuple is also TRUE and the search finds it. Hence
`select F` is exactly the condition in 5.1.

**Theorem 2 (delete attachment).** Apply Theorem 1 with the extra partition
constraints of `D`; Lemma 2 identifies those constraints with
`scope_D(row)`. Thus `admits(..., scope=D)` holds exactly when some
predicate-TRUE admissible row lies in `D`'s scope, which is the condition
in 5.2. Count and strict sequence are explicit guards. Since delete keys
are not in metadata, no key condition may be added here; including one
would be unsound.

**Theorem 3 (execution).** A row is suppressed by `D` exactly when the
three conditions of 5.3 hold: strict sequence, row-level scope derived from
`D.spec`, and null-safe key membership. The planner's exactness does not
replace these checks because it reasons about all admissible payloads and
does not read delete keys. Materializing keys and values by stable ID with
`initial_default` is the contract's logical-value definition.

## 8. Projection and historical defaults

Projection never uses names from the writer schema.

```
def project(raw, writer_W, requested_S, columns):
    out = {}
    for name in columns:
        fid = resolve(requested_S, name).id
        out[name] = value(fid)     # section 2, stable ID
    return out
```

`write_default` is not consulted. Consequently, reading an old file through
a newer requested schema yields `initial_default` for fields that did not
exist when the file was written, and reading a renamed/reused name yields
the value of the requested schema's stable ID, not the writer's same-named
field.

## 9. Plan pinning and cache disposition

A plan pins:

```
snapshot_id, schema_id, the predicate tree, the requested columns,
and the resulting scan (data paths with attached delete paths)
```

`execute(source, plan)` uses only these pinned fields plus source metadata
and payloads. It never consults the Planner's current cache or “latest”
snapshot. Therefore an earlier plan may be executed after later `plan`
calls, and two plans for different snapshots/schemas are different objects
even when the predicate text and column names are identical.

Cache rules:

- Cache key = `(snapshot_id, schema_id, canonical predicate, tuple(columns))`.
- Cache is per `Planner` (or per immutable `Source`); never share across
  sources.
- Same key is safe to reuse because source metadata is immutable.
- **Old cache entries** keyed only by predicate and columns are invalid on
  upgrade: a value cannot be assigned the snapshot/schema it was planned
  for. They must be discarded, not migrated, and no cached plan may be
  reinterpreted for another snapshot/schema.
- Return deep copies so callers cannot mutate cached plans.

## 10. Release gate and evidence

The release gate covers, at minimum:

- arbitrary legal nested predicates (`not`, `and`, `or`, `isnull`,
  comparisons), including shared fields and UNKNOWN;
- files with missing metrics, missing `null_count`, missing bounds,
  count 0, and writer schemas lacking predicate/partition/equality IDs;
- initial defaults and name rename/reuse across schemas;
- partition evolution and unpartitioned/global deletes;
- strict delete sequence, equal-sequence survival, count-0 deletes,
  null-safe keys, and row-level scope.

The exact contract evidence interface is:

```
python3 review_evidence.py verify
python3 review_evidence.py demo
python3 checks.py normal     # NORMAL_REGRESSION_OK
python3 checks.py incident   # remains SCAN_REVIEW_MISMATCH during review
```

`verify` must replay a fresh baseline and independently re-derive the
expected rows/plans; it must fail if evidence and baseline disagree.

No new index, payload rewrite, or migration is required: the fixes are in
planner logic, execution checks, projection, and cache keying.
