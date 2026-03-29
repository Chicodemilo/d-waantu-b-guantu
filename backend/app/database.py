# Path: app/database.py
# File: database.py
# Created: 2026-03-29
# Purpose: SQLAlchemy engine, session factory, and Base
# Caller: app/routers/* via Depends(get_db)
# Callees: app/config.py, sqlalchemy
# Data In: DATABASE_URL from config
# Data Out: Session, Base, engine
# Last Modified: 2026-03-29

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
