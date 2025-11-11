import os
import sqlite3
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS products (
  id     INTEGER PRIMARY KEY,
  name   TEXT NOT NULL UNIQUE,
  price  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  id           TEXT PRIMARY KEY,             -- ví dụ 'abc123'
  device_id    TEXT NOT NULL,
  state        TEXT NOT NULL,                -- ACTIVE | INVOICED | CANCELLED
  created_at   TEXT NOT NULL,
  closed_at    TEXT,
  total_amount INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS session_items (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id  TEXT NOT NULL,
  product_id  INTEGER NOT NULL,
  qty         INTEGER NOT NULL,
  unit_price  INTEGER NOT NULL,
  amount      INTEGER NOT NULL,
  created_at  TEXT NOT NULL,
  UNIQUE(session_id, product_id)             -- gộp dòng: cùng product_id thì tăng qty
);

CREATE TABLE IF NOT EXISTS invoices (
  id           TEXT PRIMARY KEY,             -- ví dụ 'INV-2025-000123'
  session_id   TEXT NOT NULL UNIQUE,
  issued_at    TEXT NOT NULL,
  total_amount INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS frames (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id   TEXT NOT NULL,
  frame_id     TEXT NOT NULL UNIQUE,
  image_path   TEXT NOT NULL,
  result_json  TEXT NOT NULL,                -- {product_id/label/prob/topk...}
  created_at   TEXT NOT NULL
);
"""

def connect(db_path: str | None = None) -> sqlite3.Connection:
    """Mở kết nối SQLite (1 process), bật WAL + foreign_keys, row_factory=Row."""
    path = db_path or os.getenv("DB_PATH", "data/app.db")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    # đảm bảo PRAGMA có hiệu lực cả khi schema đã tạo
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    return con

def init(con: sqlite3.Connection) -> None:
    """Tạo bảng nếu chưa có."""
    con.executescript(SCHEMA)
    con.commit()

def _normalize_label_line(line: str) -> str:
    ln = line.strip()
    return ln.split(" ", 1)[1] if " " in ln else ln

def seed_products_from_labels(con: sqlite3.Connection, labels_path: str, default_price: int = 10000) -> int:
    """
    Đọc labels.txt (dạng '0 Aquafina' …) và seed vào products(name, price).
    Dùng INSERT OR IGNORE để tránh trùng. Trả về số bản ghi thực sự được thêm.
    """
    p = Path(labels_path)
    if not p.exists():
        print(f"[seed] labels file not found: {labels_path}")
        return 0

    lines = [x for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    names = [_normalize_label_line(x) for x in lines]

    before = con.total_changes
    for name in names:
        con.execute("INSERT OR IGNORE INTO products(name, price) VALUES(?, ?);", (name, default_price))
    con.commit()
    inserted = con.total_changes - before
    print(f"[seed] inserted {inserted}/{len(names)} products (default_price={default_price})")
    return inserted

def product_by_label(con: sqlite3.Connection, label: str):
    row = con.execute(
        "SELECT id, name, price FROM products WHERE name = ?;",
        (label,),
    ).fetchone()
    return dict(row) if row else None

def product_by_id(con: sqlite3.Connection, pid: int):
    row = con.execute(
        "SELECT id, name, price FROM products WHERE id = ?;",
        (pid,),
    ).fetchone()
    return dict(row) if row else None
