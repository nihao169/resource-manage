import re
from pathlib import Path

def test_sql_has_no_outer_transaction_and_22_tables():
    sql = Path("migrations/sql/0001_base.sql").read_text(encoding="utf-8")
    assert not re.search(r"^BEGIN;|^COMMIT;", sql, re.M)
    assert len(re.findall(r"CREATE TABLE ", sql)) == 22
    assert "DEFERRABLE INITIALLY DEFERRED" in sql
    assert "fm_version_immutable" in sql

def test_sql_matches_document_when_available():
    document = Path(__file__).resolve().parents[2] / "doc" / "PostgreSQL表结构设计.md"
    if document.exists():
        content = document.read_text(encoding="utf-8")
        source = re.search(r"```sql\s*\n(.*?)\n```", content, re.S).group(1).strip()
        source = re.sub(r"^BEGIN;\s*", "", source)
        source = re.sub(r"\s*COMMIT;$", "", source)
        assert Path("migrations/sql/0001_base.sql").read_text(encoding="utf-8").strip() == source

