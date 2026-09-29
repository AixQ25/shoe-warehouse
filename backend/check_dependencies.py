"""Return a status code without a traceback for the startup dependency probe."""

try:
    import alembic
    import fastapi
    import httpx
    import psycopg
    import sqlalchemy
    import uvicorn
except Exception:
    raise SystemExit(1)
