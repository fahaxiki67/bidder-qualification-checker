# P3R 真实联调作业清单（需白天人工配合）

> 目的：把各数据源从"MANUAL 待人工核查"推进到"真实可查询"。
> 红线：URL 必须由**人工**在当前官方门户浏览器实测后回填，不得按旧资料/搜索摘要写死；
> 本清单只是作业指导，回填动作由人完成。预计总耗时 30~60 分钟。

## 作业流程（每个数据源五步）

1. 浏览器打开官方门户（下表"复核入口"列），人工找到**查询结果页**的真实接口形态；
2. 对照"解析契约假设"列：确认响应字段能否对应（能对应→记 URL；是 HTML 无接口→
   该源置 `auto_fill_manual_verify` 或保持人工）；
3. 回填 `app/config/sources_registry.yaml`：`query_url` + `last_verified: <今天日期>`，
   必要时调整 `automation_mode`；
4. 单源实测（不跑全量）：
   `bqc check-source <source_id> --name "测试企业名" --uscc 9151... --daytime-override`
   （`--daytime-override` 仅白天人工复核时使用；输出状态/发现/注记）；
5. 按真实响应修正该源解析器（app/sources/...）→ 用真实样本回放 → 更新 docs/ACCEPTANCE.md。

## 逐源清单

| # | source_id | 复核入口（official_home） | 当前模式 | 解析契约假设（parse 输入格式） | 风控提示 |
|---|-----------|--------------------------|----------|--------------------------------|----------|
| 1 | gsxt | https://www.gsxt.gov.cn/ | auto_fill_manual_verify（恒 MANUAL） | 未实现 parse（骨架） | **图片验证码**：只能"自动导航+人工验证"，暂不建议回填 query_url |
| 2 | creditchina | https://www.creditchina.gov.cn/ | auto（URL 空→MANUAL） | JSON：`{"result":[{penalty_content, authority_level, start_date, end_date, current, grade, subject_name, subject_uscc}]}` | **实测 40001 反自动化 token**——若浏览器能查而接口拒，保持 auto_fill_manual_verify |
| 3 | zxgk | https://zxgk.court.gov.cn/ | auto_fill_manual_verify | JSON：`{"dishonest":[{case_code, court, file_date, case_note, subject_*}], "executed":[{case_code, amount, ...}]}` | 验证码；需人工验证联调 |
| 4 | mem_safety_credit | https://www.mem.gov.cn/ | auto（URL 空→MANUAL） | JSON：`{"penalties":[{content, authority_level, start_date, end_date, grade, subject_*}]}` | 待实测 |
| 5 | jzsc | https://jzsc.mohurd.gov.cn/ | auto（URL 空→MANUAL） | JSON：`{"qualifications":[{cert_name, status(正常/延期/过期/注销/吊销/暂扣), grade, subject_*}]}` | **实测接口响应体加密**——需浏览器端解码，保持人工或专题研究 |
| 6 | pcczdc | https://pccz.court.gov.cn/ | auto（URL 空→MANUAL） | JSON：`{"cases":[{state(宣告破产/清算程序), current, case_code, court, file_date, subject_*}]}` | 待实测 |
| 7 | powerchina_ban | https://ec.powerchina.cn/ | **manual_intake（保持不变）** | 人工导入 JSON：`{"bans":[{subject_name, subject_uscc, list_level(三级), scope, ban_start, ban_end, document_name}]}`，经 `bqc import-bans` 入库 | 内部名单无公开查询入口——本源不走 URL 复核，走人工导入 |
| 8 | sc_construction | 官方入口待你提供/确认（四川省住建厅建筑市场监管公共服务平台） | manual（恒 MANUAL） | JSON：`{"qualifications":[{cert_name, status, grade, subject_*}], "penalties":[{penalty_content, authority_level, start_date, end_date, grade, subject_*}]}` | 回填 URL 后改 automation_mode: auto |
| 9 | sc_credit | 信用中国（四川）入口待确认 | manual | 同 creditchina 契约 | 同 #2 |
| 10 | gd_construction | 官方入口待确认（广东省住建厅） | manual | 同 jzsc 契约 | 同 #5 |

## 回填示例（creditchina 假设复核通过）

```yaml
  - id: creditchina
    ...
    query_url: https://public.creditchina.gov.cn/...   # 人工实测的接口
    last_verified: 2026-09-XX
    automation_mode: auto
```

## 完成判据

- 逐源在 docs/ACCEPTANCE.md 更新"官方 URL 人工复核 ✓ / 真实解析验证 ✓"；
- "已支持数据源清单"仅在**真实解析验证通过**后勾选；
- 任何源实测发现反自动化/验证码 → 如实记录为 auto_fill_manual_verify 或 manual，
  **不得绕过**（2026-09-05 已实测：信用中国 40001、jzsc 加密响应、gsxt 521）。
