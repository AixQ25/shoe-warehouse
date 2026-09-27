from __future__ import annotations

import os

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from .auth import auth_router, device_router, get_db
from .catalog import router as catalog_router
from .database import make_engine, make_session_factory
from .operations import router as operations_router
from .stocktakes import router as stocktakes_router
from .exceptions import router as exceptions_router
from .imports_exports import router as imports_exports_router
from .labels import router as labels_router


def create_app(engine: Engine | None = None) -> FastAPI:
    selected_engine = engine or make_engine()
    production = os.getenv("WAREHOUSE_ENV", "development").lower() == "production"
    if production and selected_engine.dialect.name != "postgresql":
        raise RuntimeError("正式环境必须使用 PostgreSQL；请配置 DATABASE_URL")

    app = FastAPI(title="鞋模具仓库 API", version="0.1.0")
    app.state.engine = selected_engine
    app.state.session_factory = make_session_factory(selected_engine)
    app.state.cookie_secure = production or os.getenv("COOKIE_SECURE", "0") == "1"
    app.include_router(auth_router)
    app.include_router(device_router)
    app.include_router(catalog_router)
    app.include_router(operations_router)
    app.include_router(stocktakes_router)
    app.include_router(exceptions_router)
    app.include_router(imports_exports_router)
    app.include_router(labels_router)

    @app.get("/api/health", tags=["system"])
    def health(db: Session = Depends(get_db)) -> dict:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "instance_id": os.getenv("WAREHOUSE_INSTANCE_ID")}

    return app


app = create_app()
