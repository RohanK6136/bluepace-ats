from sqlalchemy import create_engine, inspect, text

from app.database import upgrade_phase6_columns, upgrade_phase12_ai_hiring_rubric_versions


def test_phase6_adds_missing_interview_round_columns_and_is_idempotent():
    """Older databases must gain the interview round fields without data loss."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(
                text("CREATE TABLE interviews (id INTEGER PRIMARY KEY, legacy_note TEXT)")
            )
            connection.execute(
                text("INSERT INTO interviews (id, legacy_note) VALUES (1, 'keep me')")
            )

        upgrade_phase6_columns(engine)
        # Running the migration again must not try to add columns a second time.
        upgrade_phase6_columns(engine)

        columns = {column["name"] for column in inspect(engine).get_columns("interviews")}
        assert {"round_name", "round_type", "round_number"} <= columns

        with engine.connect() as connection:
            row = connection.execute(
                text("SELECT legacy_note, round_name, round_type, round_number FROM interviews WHERE id = 1")
            ).one()
        assert row.legacy_note == "keep me"
        assert row.round_name == "Interview"
        assert row.round_type == "technical"
        assert row.round_number == 1
    finally:
        engine.dispose()



def test_phase12_backfills_rubric_family_version_and_hash_idempotently():
    import json
    import re

    engine = create_engine("sqlite+pysqlite:///:memory:")
    rubric = {
        "title": "Platform Engineer",
        "criteria": [{"name": "Python", "weight": 100, "required": True}],
        "total_weight": 100,
    }
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE ai_hiring_rubrics ("
                "id INTEGER PRIMARY KEY, rubric_id VARCHAR(36) UNIQUE, organization_id INTEGER, "
                "user_id INTEGER, title VARCHAR(200), job_title VARCHAR(200), rubric_data TEXT, "
                "created_at TEXT, updated_at TEXT)"
            ))
            connection.execute(text(
                "INSERT INTO ai_hiring_rubrics "
                "(id, rubric_id, organization_id, user_id, title, job_title, rubric_data) "
                "VALUES (1, :rubric_id, 7, 8, :title, :job_title, :rubric_data)"
            ), {
                "rubric_id": "legacy-rubric-uuid", "title": "Platform Engineer",
                "job_title": "Platform Engineer", "rubric_data": json.dumps(rubric),
            })

        upgrade_phase12_ai_hiring_rubric_versions(engine)
        upgrade_phase12_ai_hiring_rubric_versions(engine)

        columns = {column["name"] for column in inspect(engine).get_columns("ai_hiring_rubrics")}
        assert {"family_id", "version", "content_hash"} <= columns
        with engine.connect() as connection:
            row = connection.execute(text(
                "SELECT rubric_id, title, job_title, rubric_data, family_id, version, content_hash "
                "FROM ai_hiring_rubrics WHERE id = 1"
            )).mappings().one()
        assert row["family_id"] == row["rubric_id"]
        assert row["version"] == 1
        assert re.fullmatch(r"[0-9a-f]{64}", row["content_hash"])
        assert json.loads(row["rubric_data"]) == rubric
        assert row["title"] == "Platform Engineer"
    finally:
        engine.dispose()
