import argparse
import json
from .planner import Planner
from .reader import execute
from .source import Source


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset")
    parser.add_argument("snapshot", type=int)
    parser.add_argument("schema", type=int)
    parser.add_argument("predicate", help="JSON expression using requested names")
    parser.add_argument("columns", help="comma separated requested names")
    args = parser.parse_args()
    source = Source.load(args.dataset)
    plan = Planner(source).plan(args.snapshot, args.schema,
                                json.loads(args.predicate),
                                args.columns.split(","))
    rows = execute(source, plan)
    print(json.dumps({"plan": plan, "rows": rows, "opened": source.opened},
                     ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
