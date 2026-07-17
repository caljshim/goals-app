from sqlmodel import Session, SQLModel, create_engine, select

from app.budget.categories import SPENDING_CATEGORIES
from app.config import get_settings
from app.budget.models import Category

settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)


def seed_default_categories(session: Session) -> None:
    """Idempotently populate the category table with the default spending buckets."""
    existing = {c.name for c in session.exec(select(Category)).all()}
    added = False
    for name in sorted(SPENDING_CATEGORIES):
        if name not in existing:
            session.add(Category(name=name))
            added = True
    if added:
        session.commit()


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_default_categories(session)


def get_session():
    with Session(engine) as session:
        yield session
