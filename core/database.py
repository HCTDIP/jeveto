import os

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# 本地默认 SQLite 文件；云上设 DATABASE_URL（例：postgresql+psycopg://user:pw@host/db）
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./jeveto.db")
# SQLite 才需要 check_same_thread（Postgres 不接受这个参数）
_CONNECT_ARGS = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=_CONNECT_ARGS)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
