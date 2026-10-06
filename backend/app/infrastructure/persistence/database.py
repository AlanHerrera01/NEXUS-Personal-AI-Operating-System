from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config.settings import get_settings


class Base(DeclarativeBase):
    pass


def build_engine():
    settings = get_settings()
    connect_args = {"connect_timeout": 2} if settings.database_url.startswith("postgresql") else {}
    return create_engine(settings.database_url, pool_pre_ping=True, connect_args=connect_args)


engine = build_engine()
SessionFactory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


def get_session() -> Generator[Session, None, None]:
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()


def is_database_available() -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
