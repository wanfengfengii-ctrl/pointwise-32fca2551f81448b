def definition(source, field_id):
    return source.document["fields"][str(field_id)]


def resolve(schema, name):
    return next(f for f in schema if f["name"] == name)


def logical(row, writer, field):
    if any(f["id"] == field["id"] for f in writer):
        return row.get(str(field["id"]))
    return field["initial_default"]


def project(row, writer, requested):
    by_name = {f["name"]: f for f in writer}
    result = {}
    for field in requested:
        old = by_name.get(field["name"])
        result[field["name"]] = (row.get(str(old["id"])) if old else
                                field.get("write_default"))
    return result


def transform(value, transform_name):
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


def partition(source, spec_id, row, writer):
    return [transform(logical(row, writer, definition(source, p["source"])),
                      p["transform"]) for p in source.spec(spec_id)]


def delete_key(source, ids, row, writer):
    return tuple(logical(row, writer, definition(source, fid)) for fid in ids)
