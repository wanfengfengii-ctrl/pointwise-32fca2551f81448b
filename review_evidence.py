"""Release-review evidence for the Scanlake reader.

The script never repairs the business code.  ``actual`` observations are
produced by calling the unchanged reference reader/planner in ``scanlake``;
``expected`` observations are produced by an independent row-level and
metadata-level oracle implemented here from CONTRACT.md.

Modes:
    python3 review_evidence.py verify   baseline replay + evidence consistency
    python3 review_evidence.py demo     named cases, requests, actual/expected
    python3 review_evidence.py record   regenerate docs/review-evidence.json
"""

import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from scanlake.source import Source              # noqa: E402
from scanlake.planner import Planner            # noqa: E402
from scanlake.reader import execute             # noqa: E402

EVIDENCE_PATH = os.path.join(ROOT, "docs", "review-evidence.json")
SAMPLE_PATH = os.path.join(ROOT, "samples", "evolution.json")


# ---------------------------------------------------------------------------
# Fixtures.  Every non-sample fixture is constructed from the provided sample
# and printed in full by ``demo`` so that it can be rerun.
# ---------------------------------------------------------------------------

def load_sample():
    with open(SAMPLE_PATH, encoding="utf-8") as stream:
        return json.load(stream)


BASE = load_sample()


def _data_file(schema, spec, partition, sequence, count, metrics, rows):
    return {"kind": "data", "schema": schema, "spec": spec,
            "partition": partition, "sequence": sequence, "count": count,
            "metrics": metrics, "rows": rows}


def _equality_file(schema, spec, partition, sequence, count, equality_ids,
                   rows):
    return {"kind": "equality", "schema": schema, "spec": spec,
            "partition": partition, "sequence": sequence, "count": count,
            "metrics": {}, "equality_ids": equality_ids, "rows": rows}


def fx_equal_sequence():
    """A data file at the same sequence as a matching delete must survive."""
    doc = copy.deepcopy(BASE)
    doc["files"]["same-seq"] = _data_file(
        2, 0, [], 2, 1,
        {"1": {"lower": "b", "upper": "b", "null_count": 0},
         "2": {"lower": 100, "upper": 100, "null_count": 0},
         "3": {"lower": 100, "upper": 100, "null_count": 0},
         "4": {"lower": 7, "upper": 7, "null_count": 0}},
        [{"1": "b", "2": 100, "3": 100, "4": 7}])
    doc["snapshots"]["4"] = {"data": ["same-seq"], "deletes": ["global-b"]}
    return doc


def fx_scope_evolved():
    """Equal partition lists under day(at) and truncate(value), different scopes."""
    doc = copy.deepcopy(BASE)
    doc["files"]["scope-a"] = _data_file(
        2, 1, [0], 1, 1,
        {"1": {"lower": "x", "upper": "x", "null_count": 0},
         "2": {"lower": 100, "upper": 100, "null_count": 0},
         "3": {"lower": 50, "upper": 50, "null_count": 0},
         "4": {"lower": 7, "upper": 7, "null_count": 0}},
        [{"1": "x", "2": 100, "3": 50, "4": 7}])
    # scope-del has spec 2 = truncate:10 on field 3, partition [0].
    doc["files"]["scope-del"] = _equality_file(
        2, 2, [0], 2, 1, [1], [{"1": "x"}])
    doc["snapshots"]["5"] = {"data": ["scope-a"], "deletes": ["scope-del"]}
    return doc


def fx_scope_execution():
    """One key matches two rows; only the row inside the delete scope dies."""
    doc = copy.deepcopy(BASE)
    doc["files"]["scope-b"] = _data_file(
        2, 1, [0], 1, 2,
        {"1": {"lower": "k", "upper": "k", "null_count": 0},
         "2": {"lower": 100, "upper": 100, "null_count": 0},
         "3": {"lower": 5, "upper": 50, "null_count": 0},
         "4": {"lower": 7, "upper": 7, "null_count": 0}},
        [{"1": "k", "2": 100, "3": 5, "4": 7},
         {"1": "k", "2": 100, "3": 50, "4": 7}])
    doc["files"]["scope-del2"] = _equality_file(
        2, 2, [0], 2, 1, [1], [{"1": "k"}])
    doc["snapshots"]["6"] = {"data": ["scope-b"], "deletes": ["scope-del2"]}
    return doc


def fx_delete_zero_count():
    doc = copy.deepcopy(BASE)
    doc["files"]["cnt-a"] = _data_file(
        2, 0, [], 1, 1,
        {"1": {"lower": "z", "upper": "z", "null_count": 0},
         "2": {"lower": 1, "upper": 1, "null_count": 0},
         "3": {"lower": 1, "upper": 1, "null_count": 0},
         "4": {"lower": 7, "upper": 7, "null_count": 0}},
        [{"1": "z", "2": 1, "3": 1, "4": 7}])
    doc["files"]["cnt-del"] = _equality_file(
        2, 0, [], 2, 0, [1], [])
    doc["snapshots"]["7"] = {"data": ["cnt-a"], "deletes": ["cnt-del"]}
    return doc


def fx_empty_data():
    doc = copy.deepcopy(BASE)
    doc["files"]["empty-a"] = _data_file(1, 0, [], 1, 0, {}, [])
    doc["snapshots"]["8"] = {"data": ["empty-a"], "deletes": []}
    return doc


def fx_missing_null_count():
    doc = copy.deepcopy(BASE)
    doc["files"]["null-a"] = _data_file(
        1, 0, [], 1, 2,
        {"1": {"lower": "a", "upper": "a", "null_count": 0},
         "2": {"lower": 0, "upper": 0, "null_count": 0},
         "3": {"lower": 10, "upper": 10}},          # null_count unknown
        [{"1": "a", "2": 0, "3": 10},
         {"1": "a", "2": 0, "3": None}])
    doc["snapshots"]["9"] = {"data": ["null-a"], "deletes": []}
    return doc


def fx_delete_key_default():
    doc = copy.deepcopy(BASE)
    doc["files"]["dk-a"] = _data_file(
        2, 0, [], 1, 1,
        {"1": {"lower": "k", "upper": "k", "null_count": 0},
         "2": {"lower": 100, "upper": 100, "null_count": 0},
         "3": {"lower": 10, "upper": 10, "null_count": 0},
         "4": {"lower": 7, "upper": 7, "null_count": 0}},
        [{"1": "k", "2": 100, "3": 10, "4": 7}])
    # Delete writer schema 1 has no field 4.  Field 4 is still an equality id,
    # so its logical value is field 4's immutable initial_default (7), not the
    # null written in the delete row.
    doc["files"]["dk-del"] = _equality_file(
        1, 0, [], 2, 1, [4], [{"4": None}])
    doc["snapshots"]["10"] = {"data": ["dk-a"], "deletes": ["dk-del"]}
    return doc


def fx_own_partition():
    doc = copy.deepcopy(BASE)
    doc["files"]["part-a"] = _data_file(
        2, 2, [20], 1, 1,
        {"1": {"lower": "a", "upper": "a", "null_count": 0},
         "2": {"lower": 100, "upper": 100, "null_count": 0},
         # deliberately loose bounds; own partition restricts value to 20..29
         "3": {"lower": 10, "upper": 50, "null_count": 0},
         "4": {"lower": 7, "upper": 7, "null_count": 0}},
        [{"1": "a", "2": 100, "3": 25, "4": 7}])
    doc["snapshots"]["11"] = {"data": ["part-a"], "deletes": []}
    return doc


FIXTURES = {
    "sample": lambda: copy.deepcopy(BASE),
    "equal_sequence": fx_equal_sequence,
    "scope_evolved": fx_scope_evolved,
    "scope_execution": fx_scope_execution,
    "delete_zero_count": fx_delete_zero_count,
    "empty_data": fx_empty_data,
    "missing_null_count": fx_missing_null_count,
    "delete_key_default": fx_delete_key_default,
    "own_partition": fx_own_partition,
}


def fixture(variant_id):
    return FIXTURES[variant_id]()


# ---------------------------------------------------------------------------
# Independent oracle helpers: stable-id materialization, transforms, 3VL.
# ---------------------------------------------------------------------------

def transform_value(value, transform_name):
    if value is None:
        return None
    if transform_name == "identity":
        return value
    if transform_name == "day":
        return value // 86400
    if transform_name.startswith("truncate:"):
        width = int(transform_name.split(":")[1])
        return value - value % width
    raise ValueError("UNKNOWN_TRANSFORM")


def logical_value(doc, writer_ids, raw, field_id):
    if field_id in writer_ids:
        return raw.get(str(field_id))
    return doc["fields"][str(field_id)]["initial_default"]


def writer_ids(doc, schema_id):
    return [f["id"] for f in doc["schemas"][str(schema_id)]]


def requested_by_name(doc, schema_id):
    return {f["name"]: f for f in doc["schemas"][str(schema_id)]}


def row_partition(doc, spec_id, raw, writer):
    return [transform_value(
                logical_value(doc, writer, raw, entry["source"]),
                entry["transform"])
            for entry in doc["specs"][str(spec_id)]]


def tri_not(value):
    return None if value is None else not value


def tri_and(left, right):
    if left is False or right is False:
        return False
    return None if left is None or right is None else True


def tri_or(left, right):
    if left is True or right is True:
        return True
    return None if left is None or right is None else False


def eval_pred(expr, values, name_to_id):
    op = expr[0]
    if op == "and":
        return tri_and(eval_pred(expr[1], values, name_to_id),
                       eval_pred(expr[2], values, name_to_id))
    if op == "or":
        return tri_or(eval_pred(expr[1], values, name_to_id),
                      eval_pred(expr[2], values, name_to_id))
    if op == "not":
        return tri_not(eval_pred(expr[1], values, name_to_id))
    field_id = name_to_id[expr[1]]
    value = values.get(field_id)
    if op == "isnull":
        return value is None
    if value is None:
        return None
    if op == "eq":
        return value == expr[2]
    if op == "lt":
        return value < expr[2]
    raise ValueError("UNKNOWN_PREDICATE")


def oracle_rows(doc, snapshot_id, schema_id, predicate, columns):
    snapshot = doc["snapshots"][str(snapshot_id)]
    requested = requested_by_name(doc, schema_id)
    name_to_id = {f["name"]: f["id"] for f in requested.values()}
    out = []
    for path in snapshot["data"]:
        data = doc["files"][path]
        writer = writer_ids(doc, data["schema"])
        delete_keys = {}
        for delete_path in snapshot["deletes"]:
            delete = doc["files"][delete_path]
            dwriter = writer_ids(doc, delete["schema"])
            delete_keys[delete_path] = {
                tuple(logical_value(doc, dwriter, drow, fid)
                      for fid in delete["equality_ids"])
                for drow in delete["rows"]}
        for raw in data["rows"]:
            suppressed = False
            for delete_path in snapshot["deletes"]:
                delete = doc["files"][delete_path]
                if not (data["sequence"] < delete["sequence"]):
                    continue
                if row_partition(doc, delete["spec"], raw, writer) != \
                        delete["partition"]:
                    continue
                key = tuple(logical_value(doc, writer, raw, fid)
                            for fid in delete["equality_ids"])
                if key in delete_keys[delete_path]:
                    suppressed = True
                    break
            if suppressed:
                continue
            values = {fid: logical_value(doc, writer, raw, fid)
                      for fid in writer}
            # Fields absent from the writer schema are still logical values.
            for field in doc["fields"].values():
                fid = field["id"]
                if fid not in values:
                    values[fid] = logical_value(doc, writer, raw, fid)
            if eval_pred(predicate, values, name_to_id) is True:
                out.append({name: values[requested[name]["id"]]
                            for name in columns})
    return out


def oracle_opened(plan):
    opened = []
    for task in plan["scan"]:
        opened.extend(task["deletes"])
        opened.append(task["path"])
    return opened


# ---------------------------------------------------------------------------
# Exact metadata oracle.
#
# A logical row of a data file is admissible iff it respects:
#   * presence in the writer schema (absent -> immutable initial_default),
#   * the file count (count == 0 has no row),
#   * per-field null_count (present exact, missing unknown),
#   * per-field inclusive lower/upper bounds on non-null values,
#   * the file's own partition under its own spec.
# The contract records no cross-field correlations, so any tuple of
# individually admissible per-field values is jointly admissible.  The
# solver below therefore enumerates, per predicate field, the finitely many
# value cells that matter and then searches the formula exactly.
# ---------------------------------------------------------------------------

EMPTY = ("empty",)


def nn_nonempty(nn):
    if nn[0] == "empty":
        return False
    if nn[0] == "point":
        return True
    lo, hi = nn[1], nn[2]
    return lo is None or hi is None or lo <= hi


def nn_contains(nn, value):
    if nn[0] == "empty":
        return False
    if nn[0] == "point":
        return value == nn[1]
    lo, hi = nn[1], nn[2]
    return (lo is None or lo <= value) and (hi is None or value <= hi)


def nn_intersect(left, right):
    if not nn_nonempty(left) or not nn_nonempty(right):
        return EMPTY
    if left[0] == "point" and right[0] == "point":
        return left if left[1] == right[1] else EMPTY
    if left[0] == "point":
        return left if nn_contains(right, left[1]) else EMPTY
    if right[0] == "point":
        return right if nn_contains(left, right[1]) else EMPTY
    lo = right[1] if left[1] is None else (
        left[1] if right[1] is None else max(left[1], right[1]))
    hi = right[2] if left[2] is None else (
        left[2] if right[2] is None else min(left[2], right[2]))
    return EMPTY if (lo is not None and hi is not None and lo > hi) \
        else ("interval", lo, hi)


def initial_domain(doc, data, write_ids, field_id, count):
    if count == 0:
        return None
    field = doc["fields"][str(field_id)]
    if field_id not in write_ids:
        default = field["initial_default"]
        return {"null": default is None,
                "nn": EMPTY if default is None else ("point", default)}
    metric = data["metrics"].get(str(field_id))
    if metric is None:
        return {"null": True, "nn": ("interval", None, None)}
    null_count = metric.get("null_count")
    return {"null": null_count is None or null_count > 0,
            "nn": ("interval", metric.get("lower"), metric.get("upper"))
                  if (null_count is None or count - null_count > 0)
                  else EMPTY}


def transform_constraint(field_type, transform_name, required):
    if required is None:
        return {"null": True, "nn": EMPTY}
    if transform_name == "identity":
        return {"null": False, "nn": ("point", required)}
    if transform_name == "day":
        if field_type != "int":
            return {"null": False, "nn": EMPTY}
        return {"null": False,
                "nn": ("interval", required * 86400,
                       required * 86400 + 86399)}
    if transform_name.startswith("truncate:"):
        if field_type != "int":
            return {"null": False, "nn": EMPTY}
        width = int(transform_name.split(":")[1])
        if required % width != 0:
            return {"null": False, "nn": EMPTY}
        return {"null": False,
                "nn": ("interval", required, required + width - 1)}
    raise ValueError("UNKNOWN_TRANSFORM")


def apply_partition_constraints(doc, domains, data, write_ids, count,
                                spec_id, partition):
    spec = doc["specs"][str(spec_id)]
    for position, entry in enumerate(spec):
        field_id = entry["source"]
        if field_id not in domains:
            domains[field_id] = initial_domain(
                doc, data, write_ids, field_id, count)
        domain = domains[field_id]
        if domain is None:
            return False
        required = partition[position] if position < len(partition) else None
        constraint = transform_constraint(
            doc["fields"][str(field_id)]["type"],
            entry["transform"], required)
        domain["null"] = domain["null"] and constraint["null"]
        domain["nn"] = nn_intersect(domain["nn"], constraint["nn"])
        if not domain["null"] and not nn_nonempty(domain["nn"]):
            return False
    return True


def collect_atoms(expr, name_to_id):
    fields = set()
    literals = {}
    stack = [expr]
    while stack:
        node = stack.pop()
        op = node[0]
        if op in ("and", "or"):
            stack.extend([node[1], node[2]])
        elif op == "not":
            stack.append(node[1])
        else:
            field_id = name_to_id[node[1]]
            fields.add(field_id)
            if op in ("eq", "lt"):
                literals.setdefault(field_id, set()).add(node[2])
    return fields, literals


def between_rep(left, right):
    for width in range(1, len(right) + 2):
        candidate = left + "\x00" * width
        if left < candidate < right:
            return candidate
    return None


def candidates_for(field_type, domain, literals):
    if domain is None:
        return []
    values = []
    nn = domain["nn"]
    if nn[0] == "point":
        values.append(nn[1])
    elif nn[0] == "interval":
        lo, hi = nn[1], nn[2]
        if field_type == "int":
            for value in (lo, hi):
                if value is not None and nn_contains(nn, value):
                    values.append(value)
            for literal in literals:
                if not isinstance(literal, int) or isinstance(literal, bool):
                    continue
                for delta in (-1, 0, 1):
                    value = literal + delta
                    if nn_contains(nn, value):
                        values.append(value)
            if not values and nn_nonempty(nn):
                values.append(0 if nn_contains(nn, 0)
                              else (lo if lo is not None else hi))
        else:
            for value in (lo, hi):
                if value is not None and nn_contains(nn, value):
                    values.append(value)
            ordered = sorted(literals)
            for literal in ordered:
                if nn_contains(nn, literal):
                    values.append(literal)
                if literal != "" and nn_contains(nn, ""):
                    values.append("")
                above = literal + "\x00"
                if nn_contains(nn, above):
                    values.append(above)
            for left, right in zip(ordered, ordered[1:]):
                rep = between_rep(left, right)
                if rep is not None and nn_contains(nn, rep):
                    values.append(rep)
            if not values and nn_nonempty(nn):
                probe = lo if lo is not None else (hi if hi is not None else "")
                if nn_contains(nn, probe):
                    values.append(probe)
    if domain["null"]:
        values.append(None)
    unique = []
    for value in values:
        if value is None or nn_contains(nn, value):
            if value not in unique:
                unique.append(value)
    return unique


def formula_satisfiable(expr, field_list, candidate_map, name_to_id):
    values = {}

    def search(index):
        if index == len(field_list):
            return eval_pred(expr, values, name_to_id) is True
        field_id = field_list[index]
        for candidate in candidate_map[field_id]:
            values[field_id] = candidate
            if search(index + 1):
                return True
        values.pop(field_id, None)
        return False

    return search(0)


def admits_row(doc, data, schema_id, predicate, delete=None):
    count = data["count"]
    if count <= 0:
        return False
    write_ids = writer_ids(doc, data["schema"])
    name_to_id = {f["name"]: f["id"]
                  for f in doc["schemas"][str(schema_id)]}
    domains = {}
    if not apply_partition_constraints(doc, domains, data, write_ids, count,
                                       data["spec"], data["partition"]):
        return False
    if delete is not None:
        if not apply_partition_constraints(doc, domains, data, write_ids,
                                           count, delete["spec"],
                                           delete["partition"]):
            return False
    for field_id, domain in domains.items():
        if domain is None or not (domain["null"] or nn_nonempty(domain["nn"])):
            return False
    fields, literals = collect_atoms(predicate, name_to_id)
    candidate_map = {}
    for field_id in fields:
        domain = domains.get(field_id)
        if domain is None:
            domain = initial_domain(doc, data, write_ids, field_id, count)
            domains[field_id] = domain
        choices = candidates_for(doc["fields"][str(field_id)]["type"],
                                 domain, literals.get(field_id, set()))
        if not choices:
            return False
        candidate_map[field_id] = choices
    return formula_satisfiable(predicate, sorted(fields), candidate_map,
                               name_to_id)


def oracle_plan(doc, snapshot_id, schema_id, predicate, columns):
    snapshot = doc["snapshots"][str(snapshot_id)]
    selected = []
    for path in snapshot["data"]:
        data = doc["files"][path]
        if not admits_row(doc, data, schema_id, predicate):
            continue
        deletes = []
        for delete_path in snapshot["deletes"]:
            delete = doc["files"][delete_path]
            if delete["count"] <= 0:
                continue
            if not (delete["sequence"] > data["sequence"]):
                continue
            if not admits_row(doc, data, schema_id, predicate, delete):
                continue
            deletes.append(delete_path)
        selected.append({"path": path, "deletes": deletes})
    return {"snapshot": snapshot_id, "schema": schema_id,
            "predicate": copy.deepcopy(predicate), "columns": list(columns),
            "scan": selected}


# ---------------------------------------------------------------------------
# Calls / replay.
# ---------------------------------------------------------------------------

def plan_call(planner, snapshot, schema, predicate, columns):
    return {"action": "plan", "planner": planner, "snapshot": snapshot,
            "schema": schema, "predicate": predicate,
            "columns": columns}


def exec_call(plan_index):
    return {"action": "execute", "plan_index": plan_index}


def plan_calls(calls):
    return [c for c in calls if c["action"] == "plan"]


def replay(doc, calls):
    source = Source(doc)
    planners = {}
    plans = []
    rows = []
    opened = []
    for call in calls:
        if call["action"] == "plan":
            tag = call["planner"]
            if tag not in planners:
                planners[tag] = Planner(source)
            plans.append(planners[tag].plan(
                call["snapshot"], call["schema"], call["predicate"],
                call["columns"]))
        elif call["action"] == "execute":
            start = len(source.opened)
            rows.append(execute(source, plans[call["plan_index"]]))
            opened.append(source.opened[start:])
        else:
            raise ValueError("UNKNOWN_CALL")
    return plans, rows, opened


def expected_outputs(doc, calls):
    pcalls = plan_calls(calls)
    plans = [oracle_plan(doc, c["snapshot"], c["schema"], c["predicate"],
                         c["columns"]) for c in pcalls]
    rows = []
    opened = []
    for call in calls:
        if call["action"] == "execute":
            args = pcalls[call["plan_index"]]
            rows.append(oracle_rows(doc, args["snapshot"], args["schema"],
                                    args["predicate"], args["columns"]))
            opened.append(oracle_opened(plans[call["plan_index"]]))
    return plans, rows, opened


# ---------------------------------------------------------------------------
# Cases.
# ---------------------------------------------------------------------------

def loc(path, line):
    return {"path": path, "line": line}


CASES = [
    {
        "id": "incident-not-eq",
        "kind": "defect",
        "variant": "sample",
        "description": "Reported negation query on snapshot 1; NOT(eq value 20) "
                       "must keep 10 and 30.",
        "calls": [plan_call("P1", 1, 1, ["not", ["eq", "value", 20]],
                            ["sensor", "value"]),
                  exec_call(0)],
        "locations": [loc("scanlake/predicate.py", 47),
                      loc("scanlake/planner.py", 20),
                      loc("scanlake/reader.py", 22)],
    },
    {
        "id": "exact-and-shared-field",
        "kind": "defect",
        "variant": "sample",
        "description": "AND of two contradictory tests on one field admits no "
                       "TRUE row; exact metadata selection must prune, not read.",
        "calls": [plan_call("P1", 1, 1,
                            ["and", ["eq", "value", 10],
                             ["eq", "value", 20]], ["sensor", "value"]),
                  exec_call(0)],
        "locations": [loc("scanlake/predicate.py", 40),
                      loc("scanlake/planner.py", 20)],
    },
    {
        "id": "projection-historical-default",
        "kind": "defect",
        "variant": "sample",
        "description": "Field 4 is absent from writer schema 1; its logical "
                       "value is initial_default 7, not schema 2 write_default 9.",
        "calls": [plan_call("P1", 1, 2, ["eq", "quality", 7],
                            ["device", "quality"]),
                  exec_call(0)],
        "locations": [loc("scanlake/values.py", 16),
                      loc("scanlake/values.py", 19),
                      loc("scanlake/values.py", 21)],
    },
    {
        "id": "projection-name-reuse",
        "kind": "defect",
        "variant": "sample",
        "description": "Schema 3 reuses name sensor for stable id 5; writer "
                       "schema 1's sensor is id 1 and must not bind the name.",
        "calls": [plan_call("P1", 1, 3, ["isnull", "sensor"], ["sensor"]),
                  exec_call(0)],
        "locations": [loc("scanlake/values.py", 16),
                      loc("scanlake/values.py", 19)],
    },
    {
        "id": "cache-snapshot-key",
        "kind": "defect",
        "variant": "sample",
        "description": "One long-lived Planner plans snapshot 1 then snapshot 2 "
                       "with the same predicate/columns; cache must not leak the "
                       "snapshot-1 scan.",
        "calls": [plan_call("shared", 1, 1, ["eq", "value", 21],
                            ["sensor", "value"]),
                  exec_call(0),
                  plan_call("shared", 2, 1, ["eq", "value", 21],
                            ["sensor", "value"]),
                  exec_call(1)],
        "locations": [loc("scanlake/planner.py", 12),
                      loc("scanlake/planner.py", 13),
                      loc("scanlake/planner.py", 14)],
    },
    {
        "id": "delete-equal-sequence",
        "kind": "defect",
        "variant": "equal_sequence",
        "description": "Data and delete both at sequence 2: data survives an "
                       "equal-sequence delete.",
        "calls": [plan_call("P1", 4, 2, ["eq", "device", "b"],
                            ["device", "value"]),
                  exec_call(0)],
        "locations": [loc("scanlake/planner.py", 25),
                      loc("scanlake/reader.py", 18)],
    },
    {
        "id": "delete-scope-evolved-spec",
        "kind": "defect",
        "variant": "scope_evolved",
        "description": "Delete partition [0] under truncate:10(value) is not "
                       "the same scope as data partition [0] under day(at).",
        "calls": [plan_call("P1", 5, 2, ["eq", "device", "x"],
                            ["device", "value"]),
                  exec_call(0)],
        "locations": [loc("scanlake/planner.py", 27),
                      loc("scanlake/values.py", 38)],
    },
    {
        "id": "delete-scope-execution",
        "kind": "defect",
        "variant": "scope_execution",
        "description": "Planner legitimately attaches a delete; execution must "
                       "still check row-level scope, so value 5 dies, value 50 "
                       "survives.",
        "calls": [plan_call("P1", 6, 2, ["eq", "device", "k"],
                            ["device", "value"]),
                  exec_call(0)],
        "locations": [loc("scanlake/reader.py", 18),
                      loc("scanlake/reader.py", 19)],
    },
    {
        "id": "delete-zero-count",
        "kind": "defect",
        "variant": "delete_zero_count",
        "description": "A delete with count 0 has no keys and must not be "
                       "attached or opened.",
        "calls": [plan_call("P1", 7, 2, ["eq", "device", "z"],
                            ["device", "value"]),
                  exec_call(0)],
        "locations": [loc("scanlake/planner.py", 23),
                      loc("scanlake/planner.py", 29)],
    },
    {
        "id": "data-empty-file",
        "kind": "defect",
        "variant": "empty_data",
        "description": "A data file with count 0 has no row and cannot admit a "
                       "TRUE predicate; it must not be opened.",
        "calls": [plan_call("P1", 8, 1, ["eq", "sensor", "a"],
                            ["sensor", "value"]),
                  exec_call(0)],
        "locations": [loc("scanlake/predicate.py", 50),
                      loc("scanlake/predicate.py", 51)],
    },
    {
        "id": "isnull-missing-null-count",
        "kind": "defect",
        "variant": "missing_null_count",
        "description": "Missing null_count means unknown; a file with a null "
                       "row can admit isnull(value).",
        "calls": [plan_call("P1", 9, 1, ["isnull", "value"],
                            ["sensor", "value"]),
                  exec_call(0)],
        "locations": [loc("scanlake/predicate.py", 52),
                      loc("scanlake/predicate.py", 53)],
    },
    {
        "id": "delete-key-initial-default",
        "kind": "defect",
        "variant": "delete_key_default",
        "description": "Equality id 4 is absent from delete writer schema 1, so "
                       "the delete key uses initial_default 7 and suppresses the "
                       "data row.",
        "calls": [plan_call("P1", 10, 2, ["eq", "device", "k"],
                            ["device", "value"]),
                  exec_call(0)],
        "locations": [loc("scanlake/reader.py", 14),
                      loc("scanlake/values.py", 9),
                      loc("scanlake/values.py", 12)],
    },
    {
        "id": "data-own-partition",
        "kind": "defect",
        "variant": "own_partition",
        "description": "Loose metric bounds admit value 10, but the file's own "
                       "partition truncate:10=[20] restricts values to 20..29, "
                       "so lt 15 has no TRUE row.",
        "calls": [plan_call("P1", 11, 2, ["lt", "value", 15],
                            ["device", "value"]),
                  exec_call(0)],
        "locations": [loc("scanlake/predicate.py", 59),
                      loc("scanlake/predicate.py", 60),
                      loc("scanlake/planner.py", 20)],
    },
    # ------------------------------------------------------------------
    # Positive controls: legitimate pruning, 3VL and plan pinning still work.
    # ------------------------------------------------------------------
    {
        "id": "positive-prune-lt",
        "kind": "positive",
        "variant": "sample",
        "description": "Legitimate metadata pruning: lt value 15 prunes to "
                       "old-a and reads only old-a.",
        "calls": [plan_call("P1", 1, 1, ["lt", "value", 15],
                            ["sensor", "value"]),
                  exec_call(0)],
        "locations": [loc("scanlake/predicate.py", 59),
                      loc("scanlake/predicate.py", 60)],
    },
    {
        "id": "positive-prune-eq-multifile",
        "kind": "positive",
        "variant": "sample",
        "description": "Legitimate multi-file pruning: eq value 99 selects only "
                       "next; old-a and new-a bounds exclude 99.",
        "calls": [plan_call("P1", 3, 2, ["eq", "value", 99],
                            ["device", "value"]),
                  exec_call(0)],
        "locations": [loc("scanlake/predicate.py", 56),
                      loc("scanlake/predicate.py", 57),
                      loc("scanlake/predicate.py", 58)],
    },
    {
        "id": "positive-not-prune",
        "kind": "positive",
        "variant": "sample",
        "description": "Legitimate complement pruning: NOT(eq value 99) is "
                       "certainly TRUE inside old-a's bounds.",
        "calls": [plan_call("P1", 1, 1, ["not", ["eq", "value", 99]],
                            ["sensor", "value"]),
                  exec_call(0)],
        "locations": [loc("scanlake/predicate.py", 47)],
    },
    {
        "id": "positive-delete-pre-deletion",
        "kind": "positive",
        "variant": "sample",
        "description": "Statistics describe physical rows before deletion: "
                       "old-a is still a candidate even though every matching "
                       "row is deleted.",
        "calls": [plan_call("P1", 2, 1, ["eq", "value", 20],
                            ["sensor", "value"]),
                  exec_call(0)],
        "locations": [loc("scanlake/planner.py", 25),
                      loc("scanlake/reader.py", 18)],
    },
    {
        "id": "positive-plan-reexec",
        "kind": "positive",
        "variant": "sample",
        "description": "Same-planner cache reuse for identical arguments and "
                       "re-execution of an earlier plan after a later plan call "
                       "must remain pinned.",
        "calls": [plan_call("P1", 1, 1, ["lt", "value", 25],
                            ["sensor", "value"]),
                  plan_call("P1", 1, 1, ["lt", "value", 25],
                            ["sensor", "value"]),
                  plan_call("P1", 1, 1, ["lt", "value", 45],
                            ["sensor", "value"]),
                  exec_call(0),
                  exec_call(1),
                  exec_call(0)],
        "locations": [loc("scanlake/planner.py", 11),
                      loc("scanlake/planner.py", 13),
                      loc("scanlake/reader.py", 5)],
    },
]


# ---------------------------------------------------------------------------
# Evidence construction / verification / demo.
# ---------------------------------------------------------------------------

def source_line(path, line):
    with open(os.path.join(ROOT, path), encoding="utf-8") as stream:
        lines = stream.read().splitlines()
    return lines[line - 1]


def resolved_locations(case):
    result = []
    for item in case["locations"]:
        result.append({"path": item["path"], "line": item["line"],
                       "text": source_line(item["path"], item["line"])})
    return result


def build_case(case):
    doc = fixture(case["variant"])
    calls = copy.deepcopy(case["calls"])
    actual_plans, actual_rows, actual_opened = replay(doc, calls)
    expected_plans, expected_rows, expected_opened = expected_outputs(
        doc, calls)
    evidence = {
        "id": case["id"],
        "kind": case["kind"],
        "variant": case["variant"],
        "description": case["description"],
        "calls": calls,
        "expected": expected_rows,
        "actual": actual_rows,
        "expected_plans": expected_plans,
        "actual_plans": actual_plans,
        "opened": actual_opened,
        "expected_opened": expected_opened,
        "locations": resolved_locations(case),
    }
    if case["kind"] == "positive":
        assert actual_rows == expected_rows, (case["id"], actual_rows,
                                              expected_rows)
        assert actual_plans == expected_plans, (case["id"], actual_plans,
                                                expected_plans)
        assert actual_opened == expected_opened, (case["id"], actual_opened,
                                                  expected_opened)
    else:
        assert (actual_rows != expected_rows or
                actual_plans != expected_plans or
                actual_opened != expected_opened), case["id"]
    return evidence


def build_evidence():
    return {"cases": [build_case(case) for case in CASES]}


def _compare(saved, fresh, label, case_id):
    if saved != fresh:
        raise AssertionError("%s mismatch in case %s" % (label, case_id))


def verify():
    with open(EVIDENCE_PATH, encoding="utf-8") as stream:
        saved_evidence = json.load(stream)
    saved_by_id = {case["id"]: case for case in saved_evidence["cases"]}
    problems = []
    for case in CASES:
        doc = fixture(case["variant"])
        calls = case["calls"]
        try:
            actual_plans, actual_rows, actual_opened = replay(doc, calls)
            expected_plans, expected_rows, expected_opened = expected_outputs(
                doc, calls)
            saved = saved_by_id[case["id"]]
            _compare(saved["actual_plans"], actual_plans, "actual_plans",
                     case["id"])
            _compare(saved["actual"], actual_rows, "actual", case["id"])
            _compare(saved["opened"], actual_opened, "opened", case["id"])
            _compare(saved["expected_plans"], expected_plans,
                     "expected_plans", case["id"])
            _compare(saved["expected"], expected_rows, "expected", case["id"])
            _compare(saved["expected_opened"], expected_opened,
                     "expected_opened", case["id"])
            _compare(saved["locations"], resolved_locations(case),
                     "locations", case["id"])
            if case["kind"] == "positive":
                if not (actual_rows == expected_rows and
                        actual_plans == expected_plans and
                        actual_opened == expected_opened):
                    problems.append("%s: positive control diverged" %
                                    case["id"])
            else:
                if (actual_rows == expected_rows and
                        actual_plans == expected_plans and
                        actual_opened == expected_opened):
                    problems.append("%s: defect no longer reproduced" %
                                    case["id"])
        except Exception as exc:  # keep checking the remaining cases
            problems.append("%s: %s: %s" % (case["id"], type(exc).__name__,
                                            exc))
    if problems:
        for problem in problems:
            print("EVIDENCE_PROBLEM " + problem)
        print("REVIEW_EVIDENCE_FAILED")
        return 1
    print("cases=%d defects=%d positives=%d" % (
        len(CASES),
        sum(1 for c in CASES if c["kind"] == "defect"),
        sum(1 for c in CASES if c["kind"] == "positive")))
    print("REVIEW_EVIDENCE_OK")
    return 0


def demo():
    print("BASE_FIXTURE samples/evolution.json")
    emitted = set()
    for case in CASES:
        if case["variant"] == "sample" or case["variant"] in emitted:
            continue
        emitted.add(case["variant"])
        print("FIXTURE %s %s" % (
            case["variant"],
            json.dumps(fixture(case["variant"]), sort_keys=True,
                       ensure_ascii=False)))
    for case in CASES:
        doc = fixture(case["variant"])
        actual_plans, actual_rows, actual_opened = replay(doc, case["calls"])
        expected_plans, expected_rows, _ = expected_outputs(doc,
                                                            case["calls"])
        print("CASE %s [%s] %s" % (case["id"], case["kind"],
                                   case["description"]))
        print("  calls %s" % json.dumps(case["calls"], sort_keys=True,
                                        ensure_ascii=False))
        print("  actual_rows %s" % json.dumps(actual_rows, sort_keys=True,
                                              ensure_ascii=False))
        print("  expected_rows %s" % json.dumps(expected_rows, sort_keys=True,
                                                ensure_ascii=False))
        print("  actual_plans %s" % json.dumps(actual_plans, sort_keys=True,
                                               ensure_ascii=False))
        print("  expected_plans %s" % json.dumps(expected_plans,
                                                  sort_keys=True,
                                                  ensure_ascii=False))
        print("  actual_opened %s" % json.dumps(actual_opened,
                                                sort_keys=True,
                                                ensure_ascii=False))
    print("REVIEW_DEMO_OK")
    return 0


def record():
    data = build_evidence()
    with open(EVIDENCE_PATH, "w", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")
    print("wrote %s (%d cases)" % (EVIDENCE_PATH, len(data["cases"])))
    return 0


def main(argv):
    if len(argv) != 2 or argv[1] not in ("verify", "demo", "record"):
        raise SystemExit("usage: python3 review_evidence.py "
                         "{verify|demo|record}")
    return {"verify": verify, "demo": demo, "record": record}[argv[1]]()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
