"""记忆库SQLite+FTS5存储层。单表memories存原文，memories_fts存手动切分好的
token做全文检索索引。FTS5默认分词器(unicode61)不认识中文词边界，一整段中文
会被当成一个超长token，所以写入和查询两侧都要用同一套"按字符切分"规则手动
分词，不能依赖FTS5自己的分词器(CJK-aware检索的简化实现)。"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .belief import (
    tier_for_confidence, is_archived, decayed_confidence,
    INITIAL_CONFIDENCE, REINFORCE_INCREMENT,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    session_id TEXT NOT NULL,
    confidence REAL NOT NULL,
    created_at TEXT NOT NULL,
    last_reinforced_at TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(tokens);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_SCHEMA)
    return conn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+|[一-鿿]", text.lower())


def _index_tokens(text: str) -> str:
    """写入FTS索引用：空格分隔的token串。"""
    return " ".join(_tokenize(text))


def _or_query(text: str) -> str:
    """查询用：OR连接各个token，要召回率——命中任意一个词就算。"""
    tokens = _tokenize(text)
    if not tokens:
        return ""
    escaped = [t.replace('"', '""') for t in tokens]
    return " OR ".join(f'"{t}"' for t in escaped)


def _phrase_query(text: str) -> str:
    """判重用：把token串整体当一个短语查询，要求同样顺序完整出现——
    近似"内容是否已经一模一样存在过"。"""
    indexed = _index_tokens(text)
    if not indexed:
        return ""
    return f'"{indexed}"'


def _find_exact_match_id(conn: sqlite3.Connection, content: str) -> int | None:
    query = _phrase_query(content)
    if not query:
        return None
    try:
        row = conn.execute(
            "SELECT rowid FROM memories_fts WHERE memories_fts MATCH ? LIMIT 1",
            (query,),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    return row[0] if row else None


def write_memory(db_path: Path, content: str, session_id: str) -> None:
    conn = _connect(db_path)
    try:
        existing_id = _find_exact_match_id(conn, content)
        now = _now_iso()
        if existing_id is not None:
            conn.execute(
                "UPDATE memories SET confidence = MIN(confidence + ?, 1.0), last_reinforced_at = ? WHERE id = ?",
                (REINFORCE_INCREMENT, now, existing_id),
            )
        else:
            cur = conn.execute(
                "INSERT INTO memories (content, session_id, confidence, created_at, last_reinforced_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (content, session_id, INITIAL_CONFIDENCE, now, now),
            )
            new_id = cur.lastrowid
            conn.execute(
                "INSERT INTO memories_fts (rowid, tokens) VALUES (?, ?)",
                (new_id, _index_tokens(content)),
            )
        conn.commit()
    finally:
        conn.close()


def search_memories(db_path: Path, query: str, *, limit: int = 5) -> list[dict]:
    fts_query = _or_query(query)
    if not fts_query:
        return []
    conn = _connect(db_path)
    try:
        try:
            rows = conn.execute(
                """
                SELECT m.id, m.content, m.confidence, m.last_reinforced_at
                FROM memories_fts f JOIN memories m ON m.id = f.rowid
                WHERE memories_fts MATCH ?
                ORDER BY rank LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        now = datetime.now(timezone.utc)
        results = []
        for row_id, content, confidence, last_reinforced_at in rows:
            current = decayed_confidence(
                confidence, datetime.fromisoformat(last_reinforced_at), now,
            )
            if is_archived(current):
                continue
            results.append({
                "id": row_id, "content": content,
                "confidence": current, "last_reinforced_at": last_reinforced_at,
            })
        return results
    finally:
        conn.close()


def forget_matching(db_path: Path, keyword: str) -> int:
    conn = _connect(db_path)
    try:
        ids = [
            row[0] for row in
            conn.execute("SELECT id FROM memories WHERE content LIKE ?", (f"%{keyword}%",)).fetchall()
        ]
        for row_id in ids:
            conn.execute("DELETE FROM memories WHERE id = ?", (row_id,))
            conn.execute("DELETE FROM memories_fts WHERE rowid = ?", (row_id,))
        conn.commit()
        return len(ids)
    finally:
        conn.close()


def clear_all(db_path: Path) -> int:
    conn = _connect(db_path)
    try:
        cur = conn.execute("DELETE FROM memories")
        removed = cur.rowcount
        conn.execute("DELETE FROM memories_fts")
        conn.commit()
        return removed
    finally:
        conn.close()


def stats(db_path: Path) -> dict:
    conn = _connect(db_path)
    try:
        rows = conn.execute("SELECT confidence, last_reinforced_at FROM memories").fetchall()
    finally:
        conn.close()
    now = datetime.now(timezone.utc)
    counts = {"fact": 0, "belief": 0, "observation": 0, "archived": 0}
    for confidence, last_reinforced_at in rows:
        current = decayed_confidence(confidence, datetime.fromisoformat(last_reinforced_at), now)
        if is_archived(current):
            counts["archived"] += 1
        else:
            counts[tier_for_confidence(current)] += 1
    return counts
