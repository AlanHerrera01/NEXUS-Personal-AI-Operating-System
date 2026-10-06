from collections.abc import Generator

from sqlalchemy.orm import Session

from app.infrastructure.persistence.database import SessionFactory


def session_dependency() -> Generator[Session, None, None]:
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()
