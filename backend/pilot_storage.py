"""Inspect and move the office pilot SQLite database without changing the source."""

from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from uuid import uuid4


REQUIRED_TABLES = {"users", "people", "locations", "molds", "alembic_version"}


def inspect_database(path: Path) -> dict[str, object]:
    path = path.resolve()
    if not path.is_file():
        raise RuntimeError(f"找不到数据库：{path}")
    with closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=10)) as db:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError(f"数据库完整性检查失败：{path}")
        if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise RuntimeError(f"数据库外键检查失败：{path}")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not REQUIRED_TABLES <= tables:
            raise RuntimeError(f"这不是已初始化的办公室试点库，缺少表：{', '.join(sorted(REQUIRED_TABLES - tables))}")
        users = db.execute("SELECT username, password_hash FROM users ORDER BY username").fetchall()
        if not users:
            raise RuntimeError("数据库没有账号；已停止，避免自动创建新密码")
        return {
            "accounts": len(users),
            "locations": db.execute("SELECT count(*) FROM locations").fetchone()[0],
            "molds": db.execute("SELECT count(*) FROM molds").fetchone()[0],
            "account_records": users,
        }


def import_database(source: Path, target: Path, backup_directory: Path) -> dict[str, object]:
    source = source.resolve(strict=True)
    target = target.resolve()
    if source == target:
        raise RuntimeError("源数据库与 U 盘目标数据库是同一个文件")
    if target.exists():
        raise RuntimeError(f"U 盘试点库已存在，绝不覆盖：{target}")
    source_info = inspect_database(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    backup_directory.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    backup = backup_directory / f"office-pilot-import-{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:8]}.sqlite3"
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=rw", uri=True, timeout=30)) as original:
            with closing(sqlite3.connect(temporary)) as portable:
                original.backup(portable)
        target_info = inspect_database(temporary)
        if target_info != source_info:
            raise RuntimeError("迁移前后账号或库存数量不一致；源库可能仍在使用，请关闭服务后重试")
        with closing(sqlite3.connect(temporary)) as portable:
            with closing(sqlite3.connect(backup)) as saved:
                portable.backup(saved)
        if inspect_database(backup) != target_info:
            raise RuntimeError("电脑本地备份校验失败；已取消迁移")
        if target.exists():
            raise RuntimeError(f"目标数据库刚刚被其他程序创建，绝不覆盖：{target}")
        temporary.rename(target)
        return {"database": str(target), "backup": str(backup), "accounts": target_info["accounts"], "locations": target_info["locations"], "molds": target_info["molds"]}
    finally:
        temporary.unlink(missing_ok=True)


def backup_database(source: Path, backup_directory: Path) -> Path:
    source = source.resolve(strict=True)
    source_info = inspect_database(source)
    backup_directory.mkdir(parents=True, exist_ok=True)
    backup = backup_directory / f"office-pilot-{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:8]}.sqlite3"
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=rw", uri=True, timeout=30)) as original:
            with closing(sqlite3.connect(backup)) as saved:
                original.backup(saved)
        if inspect_database(backup) != source_info:
            raise RuntimeError("备份与源库账号或库存数量不一致，请确认服务已关闭")
        return backup
    except BaseException:
        backup.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="办公室试点数据库检查与一次性迁移")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check")
    check.add_argument("database", type=Path)
    move = sub.add_parser("import")
    move.add_argument("source", type=Path)
    move.add_argument("target", type=Path)
    move.add_argument("backup_directory", type=Path)
    save = sub.add_parser("backup")
    save.add_argument("database", type=Path)
    save.add_argument("backup_directory", type=Path)
    args = parser.parse_args()
    if args.command == "check":
        info = inspect_database(args.database)
        print(json.dumps({"database": str(args.database.resolve()), "accounts": info["accounts"], "locations": info["locations"], "molds": info["molds"]}, ensure_ascii=False))
    elif args.command == "import":
        print(json.dumps(import_database(args.source, args.target, args.backup_directory), ensure_ascii=False))
    else:
        print(json.dumps({"backup": str(backup_database(args.database, args.backup_directory))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
