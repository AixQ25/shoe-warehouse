"""Back up and remove the known local sample inventory before an office pilot.

Run once from backend with the local development Python environment. Account,
person, device, location, and login data are deliberately retained.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path


SAMPLE_COUNTS = {
    "mold_models": 15,
    "mold_sets": 150,
    "molds": 1500,
    "operations": 18,
    "operation_items": 180,
}
CLEAR_ORDER = (
    "stocktake_adjustments",
    "stocktake_scans",
    "stocktake_expected",
    "stocktake_sessions",
    "operation_items",
    "operations",
    "label_print_batches",
    "import_batches",
    "molds",
    "mold_sets",
    "mold_models",
)


def count(db: sqlite3.Connection, table: str) -> int:
    return db.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]


def assert_sample(db: sqlite3.Connection) -> None:
    actual = {table: count(db, table) for table in SAMPLE_COUNTS}
    if actual != SAMPLE_COUNTS:
        raise RuntimeError(f"库存不再是预期的本机样例，已取消清空：{actual}")
    checks = (
        ("mold_models", "XM-001", "XM-015"),
        ("mold_sets", "SET-0001", "SET-0150"),
        ("molds", "M-000001", "M-001500"),
    )
    for table, first, last in checks:
        codes = db.execute(f'SELECT min(code), max(code) FROM "{table}"').fetchone()
        if codes != (first, last):
            raise RuntimeError(f"{table} 含非预期编号，已取消清空：{codes}")
    if db.execute("SELECT count(*) FROM operations WHERE payload_hash != 'sample-local-history'").fetchone()[0]:
        raise RuntimeError("存在非样例流转单据，已取消清空")


def main() -> None:
    if os.getenv("WAREHOUSE_ENV", "development").lower() == "production" or os.getenv("DATABASE_URL") or os.getenv("POSTGRES_HOST"):
        raise SystemExit("只允许清理当前电脑的默认本机开发库")
    local_data = Path(os.environ["LOCALAPPDATA"]) / "mold-warehouse-dev"
    database = local_data / "warehouse.sqlite3"
    if not database.is_file():
        raise SystemExit("找不到本机开发数据库")

    with sqlite3.connect(database, timeout=30) as db:
        db.execute("PRAGMA foreign_keys=ON")
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("源数据库完整性检查失败，已取消清空")
        assert_sample(db)

        backup_dir = local_data / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / f"before-office-pilot-{datetime.now():%Y%m%d-%H%M%S-%f}.sqlite3"
        with sqlite3.connect(backup) as saved:
            db.backup(saved)
            if saved.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("备份完整性检查失败，已取消清空")
            assert_sample(saved)

        db.execute("BEGIN IMMEDIATE")
        try:
            assert_sample(db)
            for table in CLEAR_ORDER:
                db.execute(f'DELETE FROM "{table}"')
            if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise RuntimeError("清空后外键检查失败")
            if any(count(db, table) for table in CLEAR_ORDER):
                raise RuntimeError("部分业务资料未清空")
            db.commit()
        except BaseException:
            db.rollback()
            raise

        kept = {table: count(db, table) for table in ("users", "people", "authorized_devices", "locations")}
        print(f"业务资料已清空；已保留基础配置：{kept}")
        print(f"清空前备份：{backup}")


if __name__ == "__main__":
    main()
