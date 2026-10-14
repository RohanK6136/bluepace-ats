from sqlalchemy import create_engine, inspect, text

from app.database import upgrade_phase6_columns


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
