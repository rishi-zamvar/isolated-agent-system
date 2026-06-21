from gates import catalog_coverage


def test_all_touched_cataloged_passes():
    assert catalog_coverage.gate({"economy.cache_hit", "flow.throughput"},
                                  {"economy.cache_hit"}) == []


def test_uncataloged_source_blocked():
    violations = catalog_coverage.gate({"economy.cache_hit"}, {"flow.throughput"})
    assert len(violations) == 1
    assert "flow.throughput" in violations[0]


def test_multiple_uncataloged_sources_all_reported():
    violations = catalog_coverage.gate(set(), {"a.x", "b.y"})
    assert len(violations) == 2
    assert any("a.x" in v for v in violations)
    assert any("b.y" in v for v in violations)


def test_empty_touched_always_passes():
    assert catalog_coverage.gate(set(), set()) == []


def test_superset_catalog_passes():
    assert catalog_coverage.gate({"a", "b", "c"}, {"a", "b"}) == []


def test_partial_coverage_reports_only_missing():
    violations = catalog_coverage.gate({"a.x"}, {"a.x", "b.y"})
    assert len(violations) == 1
    assert "b.y" in violations[0]
