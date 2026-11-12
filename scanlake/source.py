import copy
import json


class Source:
    def __init__(self, document):
        self.document = copy.deepcopy(document)
        self.opened = []

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as stream:
            return cls(json.load(stream))

    def schema(self, schema_id):
        return self.document["schemas"][str(schema_id)]

    def snapshot(self, snapshot_id):
        return self.document["snapshots"][str(snapshot_id)]

    def spec(self, spec_id):
        return self.document["specs"][str(spec_id)]

    def metadata(self, path):
        return {k: copy.deepcopy(v) for k, v in
                self.document["files"][path].items() if k != "rows"}

    def rows(self, path):
        self.opened.append(path)
        return copy.deepcopy(self.document["files"][path]["rows"])
