# Scan reader release design (current)
The planner caches by predicate and selected columns. Snapshot metadata is
immutable, so a cached scan can be reused by a long-lived Planner.
Metrics are an inclusive projection: a positive result means a file may
contain a match. Boolean expression structure is preserved by the planner.
Partitions are stored as ordered value lists. Matching lists identify the
same scope even if partition specs have evolved.
A delete at or after a data file's sequence applies to that file.
The reader builds equality sets before reading data, then projects requested
names, applies the residual predicate and emits selected columns.
New columns use the requested write default. Names are the projection binding.
The sample append-only regression is the release gate.
