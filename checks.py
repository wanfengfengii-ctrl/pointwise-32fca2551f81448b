import json
import sys
from scanlake.source import Source
from scanlake.planner import Planner
from scanlake.reader import execute


def normal():
    source = Source.load("samples/evolution.json")
    plan = Planner(source).plan(1, 1, ["lt", "value", 25], ["sensor", "value"])
    actual = execute(source, plan)
    expected = [{"sensor": "a", "value": 10}, {"sensor": "b", "value": 20}]
    assert actual == expected, (actual, expected)
    assert source.opened == ["old-a"]
    print(json.dumps({"case": "append-read", "actual": actual,
                      "opened": source.opened}, sort_keys=True))
    print("NORMAL_REGRESSION_OK")


def incident():
    source = Source.load("samples/evolution.json")
    plan = Planner(source).plan(1, 1, ["not", ["eq", "value", 20]],
                                ["sensor", "value"])
    actual = execute(source, plan)
    expected = [{"sensor": "a", "value": 10}, {"sensor": "c", "value": 30}]
    print(json.dumps({"case": "reported-filter", "actual": actual,
                      "expected": expected, "plan": plan,
                      "opened": source.opened}, sort_keys=True))
    if actual != expected:
        print("SCAN_REVIEW_MISMATCH")
        return 1
    return 0


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "normal":
        normal()
    elif mode == "incident":
        sys.exit(incident())
    elif mode == "demo":
        normal()
        incident()
    else:
        raise SystemExit("unknown mode")
