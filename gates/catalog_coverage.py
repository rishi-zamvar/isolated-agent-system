"""Catalog-coverage gate: blocks a feature that touches an unregistered data source.

A data source is identified by its dotted resolver path (the catalog entry's `source`
field, e.g. "economy.cache_hit"). The gate is pure — all IO happens at the call site.
"""


def gate(catalog_sources: set[str], touched_sources: set[str]) -> list[str]:
    """Return a violation string for every touched source absent from the catalog.

    Empty list = gate passes. O(len(touched) + len(catalog)) via set difference.
    """
    return [
        f"data source {src!r} has no catalog entry — register it before merging"
        for src in sorted(touched_sources - catalog_sources)
    ]
