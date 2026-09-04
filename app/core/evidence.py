"""证据等级（任务书 §8）：A/B 级官方证据才支持资格否决；C/D 只用于发现线索。"""
from __future__ import annotations

from enum import Enum


class Grade(str, Enum):
    A = "A"  # 政府实时查询 / 法院官方平台 / 招标人集团官方系统
    B = "B"  # 政府正式公告 / 行政决定书 / 官方 PDF
    C = "C"  # 商业数据库（企查查/天眼查等）
    D = "D"  # 搜索引擎摘要 / 新闻 / 自媒体


OFFICIAL_GRADES: frozenset[Grade] = frozenset({Grade.A, Grade.B})


def can_support_fail(grades) -> bool:
    """是否存在至少一条 A/B 级证据。仅 C/D 时不得作 FAIL。"""
    return any(Grade(g) in OFFICIAL_GRADES for g in grades)


# ---------- 证据落盘与哈希校验（P6 证据系统） ----------
# 纪律：证据目录随数据库（<db同目录>/evidence/），属用户数据，gitignored 严禁提交；
# 每份证据必带 SHA-256，verify 可随时复核完整性；篡改/损坏必须能被检出。

import hashlib  # noqa: E402
import sqlite3  # noqa: E402
import uuid  # noqa: E402
from pathlib import Path  # noqa: E402

#: 单份证据原文大小上限（防病态大响应撑爆磁盘；截断在文件内注明）
MAX_EVIDENCE_BYTES = 5 * 1024 * 1024


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def evidence_dir_for(db_path: str | Path) -> Path:
    return Path(db_path).resolve().parent / "evidence"


def save_evidence(
    db_path: str | Path,
    *,
    source_id: str,
    url: str | None,
    raw_text: str,
    query_id: int | None = None,
    kind: str | None = None,
    grade: str | None = None,
    key_text: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> tuple[int, Path, str]:
    """把一份原始证据写盘并登记（返回 evidence_id, 文件路径, sha256）。

    文件名含内容哈希前缀：同名重查各自留档，互不覆盖（历史不可变）。
    """
    text = raw_text or ""
    truncated = False
    if len(text.encode("utf-8", errors="replace")) > MAX_EVIDENCE_BYTES:
        text = text[: MAX_EVIDENCE_BYTES // 4]  # 按字符保守截断（CJK 4 字节上界）
        truncated = True
    digest = sha256_text(text)
    if truncated:
        text += f"\n\n[证据超 {MAX_EVIDENCE_BYTES} 字节已截断，哈希对应截断后内容]"
    edir = evidence_dir_for(db_path)
    edir.mkdir(parents=True, exist_ok=True)
    fname = f"{digest[:12]}_{uuid.uuid4().hex[:8]}.txt"
    fpath = edir / fname
    # 与哈希同用 replace：孤立代理字符等不可编码内容不得让证据落盘崩溃
    fpath.write_text(text, encoding="utf-8", errors="replace")

    own = conn is None
    c = conn or sqlite3.connect(str(db_path))
    try:
        cur = c.execute(
            "INSERT INTO evidence (query_id, source_id, url, kind, file_path, sha256, grade, key_text) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (query_id, source_id, url, kind, str(fpath), digest, grade, key_text),
        )
        if own:
            c.commit()
        return cur.lastrowid, fpath, digest
    finally:
        if own:
            c.close()


def verify_evidence(db_path: str | Path, evidence_id: int | None = None):
    """复核证据完整性：重算文件 SHA-256 与登记值比对。

    返回 (ok数, [（evidence_id, 问题）])。文件缺失/哈希不符/不可读都算损坏。
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        if evidence_id is None:
            rows = conn.execute("SELECT id, file_path, sha256 FROM evidence").fetchall()
        else:
            rows = conn.execute(
                "SELECT id, file_path, sha256 FROM evidence WHERE id = ?", (evidence_id,)).fetchall()
    finally:
        conn.close()
    ok, broken = 0, []
    for r in rows:
        p = Path(r["file_path"])
        try:
            actual = sha256_text(p.read_text(encoding="utf-8", errors="replace"))
        except OSError as e:
            broken.append((r["id"], f"文件不可读：{e}"))
            continue
        if actual != r["sha256"]:
            broken.append((r["id"], "哈希不符（文件被篡改或损坏）"))
        else:
            ok += 1
    return ok, broken
