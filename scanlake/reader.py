from .predicate import evaluate
from .values import delete_key, project


def execute(source, plan):
    requested = source.schema(plan["schema"])
    output = []
    for task in plan["scan"]:
        data = source.metadata(task["path"])
        writer = source.schema(data["schema"])
        sets = []
        for path in task["deletes"]:
            delete = source.metadata(path)
            keys = {tuple(row.get(str(fid)) for fid in delete["equality_ids"])
                    for row in source.rows(path)}
            sets.append((delete["equality_ids"], keys))
        for raw in source.rows(task["path"]):
            if any(delete_key(source, ids, raw, writer) in keys
                   for ids, keys in sets):
                continue
            row = project(raw, writer, requested)
            if evaluate(plan["predicate"], row) is True:
                output.append({name: row[name] for name in plan["columns"]})
    return output
