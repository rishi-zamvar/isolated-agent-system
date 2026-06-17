import pytest

from gating import migrations


@pytest.mark.parametrize("sql", [
    "DROP TABLE users;",
    "ALTER TABLE users DROP COLUMN email;",
    "DELETE FROM sessions WHERE expired = 1;",
    "TRUNCATE audit_log;",
    "UPDATE users SET status = 'active';",                       # backfill
    "INSERT INTO new_users (id) SELECT id FROM users;",          # backfill
    "ALTER TABLE users ADD COLUMN age INT NOT NULL;",            # not-null no default
    "CREATE TABLE t (id INT); DROP TABLE old;",                  # mixed -> destructive
    "GRANT ALL ON db TO app;",                                   # unknown stmt -> fail-safe
])
def test_destructive_or_unprovable_is_destructive(sql):
    assert migrations.classify(sql) == "destructive"


@pytest.mark.parametrize("sql", [
    "CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT);",
    "ALTER TABLE users ADD COLUMN nickname TEXT NULL;",
    "ALTER TABLE users ADD COLUMN nickname TEXT;",               # nullable by default
    "CREATE INDEX idx_name ON widgets(name);",
    "ALTER TABLE users ADD COLUMN tier TEXT NOT NULL DEFAULT 'free';",  # safe default
    "-- comment only\nCREATE TABLE x (id INT);",
])
def test_provably_additive_flows(sql):
    assert migrations.classify(sql) == "additive"
