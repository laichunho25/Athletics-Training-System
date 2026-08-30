"""把「現在到底連到哪個資料庫」講清楚。

正式環境最難查的一種故障：build 期間沒讀到 DATABASE_URL，
於是 migrate / create_admin 全寫進容器裡的暫存 SQLite，
上線後跑的卻是 PostgreSQL——帳號看起來建好了，實際上根本不存在。
"""

from django.db import connection


def describe_database():
    """回傳可直接印在部署 log 上的一行摘要（不含密碼）。"""
    cfg = connection.settings_dict
    engine = (cfg.get("ENGINE") or "").rsplit(".", 1)[-1]
    name = cfg.get("NAME") or "—"
    host = cfg.get("HOST") or ""
    if engine == "sqlite3":
        return f"SQLite（檔案 {name}）"
    port = cfg.get("PORT") or ""
    where = host + (f":{port}" if port else "")
    return f"{engine}（{name} @ {where or '未指定主機'}）"


def is_sqlite():
    return "sqlite" in (connection.settings_dict.get("ENGINE") or "")
