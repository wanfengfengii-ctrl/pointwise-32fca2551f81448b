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


def evaluate(expr, row):
    op = expr[0]
    if op == "and":
        return tri_and(evaluate(expr[1], row), evaluate(expr[2], row))
    if op == "or":
        return tri_or(evaluate(expr[1], row), evaluate(expr[2], row))
    if op == "not":
        return tri_not(evaluate(expr[1], row))
    value = row[expr[1]]
    if op == "isnull":
        return value is None
    if value is None:
        return None
    if op == "eq":
        return value == expr[2]
    if op == "lt":
        return value < expr[2]
    raise ValueError("UNKNOWN_PREDICATE")


def possible(source, metadata, schema, expr):
    """Cheap inclusive projection into file metrics."""
    op = expr[0]
    if op == "and":
        return (possible(source, metadata, schema, expr[1]) and
                possible(source, metadata, schema, expr[2]))
    if op == "or":
        return (possible(source, metadata, schema, expr[1]) or
                possible(source, metadata, schema, expr[2]))
    if op == "not":
        return not possible(source, metadata, schema, expr[1])
    field = next(f for f in schema if f["name"] == expr[1])
    metric = metadata["metrics"].get(str(field["id"]))
    if metric is None:
        return True
    if op == "isnull":
        return metric.get("null_count", 0) > 0
    if metric.get("null_count") == metadata["count"]:
        return False
    if op == "eq":
        return (metric.get("lower", expr[2]) <= expr[2] <=
                metric.get("upper", expr[2]))
    if op == "lt":
        return metric.get("lower", expr[2] - 1) < expr[2]
    raise ValueError("UNKNOWN_PREDICATE")
