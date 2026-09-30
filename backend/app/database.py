import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.schema import CreateColumn

load_dotenv()

APP_ENV = os.getenv("APP_ENV", "development")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./bluepace_ats.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
if APP_ENV not in {"development", "test"} and DATABASE_URL.startswith("sqlite"):
    raise RuntimeError("DATABASE_URL must point to PostgreSQL outside development and test environments")

engine_options = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    engine_options["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **engine_options)
if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def initialize_database():
    from app import models

    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=engine)
    upgrade_phase1_columns(engine)


def upgrade_phase1_columns(target_engine):
    from app.models import Application, Candidate, Email

    additions = {
        "candidates": [Candidate.__table__.c.resume_data],
        "applications": [Application.__table__.c.updated_at],
        "emails": [Email.__table__.c.error_message],
    }
    with target_engine.begin() as connection:
        existing_tables = set(inspect(connection).get_table_names())
        for table_name, columns in additions.items():
            if table_name not in existing_tables:
                continue
            existing_columns = {column["name"] for column in inspect(connection).get_columns(table_name)}
            for column in columns:
                if column.name in existing_columns:
                    continue
                definition = str(CreateColumn(column).compile(dialect=target_engine.dialect))
                connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {definition}"))
                existing_columns.add(column.name)