import copy
import json
from .predicate import possible


class Planner:
    def __init__(self, source):
        self.source = source
        self.cache = {}

    def plan(self, snapshot_id, schema_id, predicate, columns):
        key = json.dumps([predicate, columns], sort_keys=True)
        if key in self.cache:
            return copy.deepcopy(self.cache[key])
        snap = self.source.snapshot(snapshot_id)
        schema = self.source.schema(schema_id)
        selected = []
        for path in snap["data"]:
            data = self.source.metadata(path)
            if not possible(self.source, data, schema, predicate):
                continue
            deletes = []
            for delete_path in snap["deletes"]:
                delete = self.source.metadata(delete_path)
                if delete["sequence"] < data["sequence"]:
                    continue
                if delete["partition"] and delete["partition"] != data["partition"]:
                    continue
                deletes.append(delete_path)
            selected.append({"path": path, "deletes": deletes})
        plan = {"snapshot": snapshot_id, "schema": schema_id,
                "predicate": copy.deepcopy(predicate), "columns": list(columns),
                "scan": selected}
        self.cache[key] = copy.deepcopy(plan)
        return plan
