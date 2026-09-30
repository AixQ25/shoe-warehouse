"""Last-resort interactive recovery for the portable office pilot admin account."""

from __future__ import annotations

import argparse
import sqlite3
from contextlib import closing
from pathlib import Path

from app.auth import hash_password, verify_password
from app.console_input import read_password
from pilot_storage import backup_database, inspect_database


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("backup_directory", type=Path)
    args = parser.parse_args()
    database = args.database.resolve()
    inspect_database(database)
    new_password = read_password("请输入新的 admin 密码（至少 6 个字符，输入时显示 *）：")
    confirm = read_password("再输入一次（输入时显示 *）：")
    if len(new_password) < 6 or new_password != confirm:
        raise SystemExit("密码不足 6 个字符或两次输入不一致；数据库未修改")
    saved = backup_database(database, args.backup_directory)
    with closing(sqlite3.connect(database)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE")
        admin = db.execute("SELECT id, active, role FROM users WHERE username='admin'").fetchone()
        if admin is None or not admin[1] or admin[2] != "ADMIN":
            raise RuntimeError("未找到有效的 admin 维护员账号；数据库未修改")
        db.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new_password), admin[0]))
        db.execute("UPDATE login_sessions SET revoked_at=CURRENT_TIMESTAMP WHERE user_id=? AND revoked_at IS NULL", (admin[0],))
        db.execute("UPDATE authorized_devices SET authorized=0, revoked_at=CURRENT_TIMESTAMP WHERE user_id=? AND revoked_at IS NULL", (admin[0],))
        db.commit()
        stored = db.execute("SELECT password_hash FROM users WHERE id=?", (admin[0],)).fetchone()[0]
        if not verify_password(new_password, stored) or db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError(f"密码校验失败；请从备份恢复：{saved}")
    print(f"admin 密码已更新；旧登录和设备授权已撤销。本机备份：{saved}")


if __name__ == "__main__":
    main()
