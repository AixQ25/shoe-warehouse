from __future__ import annotations

import os

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, URL
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def database_url() -> str | URL:
    configured = os.getenv("DATABASE_URL")
    if configured:
        return configured
    postgres_host = os.getenv("POSTGRES_HOST")
    if postgres_host:
        if not os.getenv("POSTGRES_PASSWORD"):
            raise RuntimeError("POSTGRES_HOST 已配置，但缺少 POSTGRES_PASSWORD")
        return URL.create(
            "postgresql+psycopg",
            username=os.getenv("POSTGRES_USER", "warehouse"),
            password=os.getenv("POSTGRES_PASSWORD"),
            host=postgres_host,
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            database=os.getenv("POSTGRES_DB", "warehouse"),
        )
    if os.getenv("WAREHOUSE_ENV", "development").lower() == "production":
        raise RuntimeError("正式环境必须配置 PostgreSQL 连接")
    raise RuntimeError("未配置 DATABASE_URL。办公室试点请从 U 盘项目根目录运行 start-local.cmd，避免误连到另一份数据库")


def make_engine(url: str | URL | None = None) -> Engine:
    selected = url or database_url()
    engine = create_engine(selected, pool_pre_ping=True)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _record):  # type: ignore[no-untyped-def]
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)
