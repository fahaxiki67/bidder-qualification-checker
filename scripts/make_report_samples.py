#!/usr/bin/env python
"""生成 P7 报告样张（Excel 明细 + PDF 报告），数据全部为 mock 演示场景。

用法：python scripts/make_report_samples.py <输出目录>
样张含演示企业（场景：限制投标 FAIL / 查询失败 ERROR / 无记录 NO_DATA），
不含任何真实企业数据。
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from app.core.db import connect, init_db  # noqa: E402
from app.core.runner import run_check  # noqa: E402
from app.reports.excel import export_excel  # noqa: E402
from app.reports.pdf import export_pdf  # noqa: E402

SCENARIOS = [
    ("演示项目甲-限制投标", "bid_ban", "演示企业甲建筑工程有限公司"),
    ("演示项目乙-查询失败", "query_error", "演示企业乙劳务有限公司"),
    ("演示项目丙-无记录", "clean", "演示企业丙科技发展有限公司"),
]


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "local" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    db = out_dir / "sample.sqlite3"
    init_db(db)
    targets = []
    for name, scenario, company in SCENARIOS:
        conn = connect(db)
        cur = conn.execute(
            "INSERT INTO projects (name, industry, province, owner_group, base_date, years_back, terms) "
            "VALUES (?, '建筑', '四川', 'powerchina', ?, 3, '条款1,条款2,条款3,条款4')",
            (name, date.today().isoformat()))
        pid = cur.lastrowid
        cur = conn.execute("INSERT INTO companies (name) VALUES (?)", (company,))
        cid = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO project_companies (project_id, company_id, status) VALUES (?,?, 'running')",
            (pid, cid))
        pcid = cur.lastrowid
        conn.commit()
        conn.close()
        overall = run_check(db, pcid, scenario=scenario)
        print(f"[sample] {name}: overall={overall}")
        if scenario == "query_error":
            targets.append(pcid)  # 样张突出"查询失败绝不写成无异常"
        if scenario == "bid_ban":
            targets.insert(0, pcid)

    xlsx = export_excel(db, targets[0], out_dir / "样张_核查明细表.xlsx")
    pdf = export_pdf(db, targets[0], out_dir / "样张_核查报告.pdf")
    print(f"[sample] Excel 样张: {xlsx}")
    print(f"[sample] PDF 样张: {pdf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
