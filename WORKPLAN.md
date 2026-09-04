# 开发计划书（闲时接力开发执行手册）

> 本文件是每轮闲时开发会话的**第一入口**。任务书全文见
> `H:\ZCode_开发任务书_投标人资格智能核查系统.md`（H 盘不可用时用仓库内
> `local/taskdoc/` 备份，该目录已 gitignore，严禁提交）。
>
> 开发周期：2026-09-04 起 至 2026-09-20。执行方式为**闲时任务接力**：
> 每轮结束自动创建下一条"闲时续跑"任务携带进度继续，不重复、不冲突；
> 闲时取号有日限额（每日 00:00 重置），取号失败即说明当日额度用尽，
> 在 PROGRESS.md 写明状态后结束，待额度恢复由接力/用户再启动。
> **每日 08:30 起收口**（全量测试 → push → 交接），09:00 前结束本轮，不跨窗口。

## 一、每轮固定协议

1. **接续**：读 `docs/PROGRESS.md` 最后 2-3 条记录 + 本文件阶段表，确认做到哪、本轮做什么。
2. **对齐远端**：`gh run list` / `git fetch origin && git log HEAD..origin/main --oneline`。
   远端有新提交（用户或其他会话推的）→ 以远端为基线继续；发现分叉 → 停下写清交接，**绝不 reset/clean/stash/强推**。
3. **守卫**（命中则只收口退出并写明原因）：
   - 用户正在 actively 使用机器（前台大量交互、怪异输入）→ 收口退出；
   - 工作树有与本任务无关的未提交改动 → 停下报告，不动它们。
4. **推进**：按阶段表做本轮的事，小步实现；每个模块写 pytest，**全量测试绿了才 commit + push**。
5. **08:30 收口**（硬性）：全量 pytest → 更新 `docs/PROGRESS.md`（本轮完成 / 遗留 / 下一步）→
   最终 commit + push → **自动创建下一条闲时续跑任务**（携带已完成/进行中/下一步/关键结论；
   当天额度用尽取号失败时，在 PROGRESS.md 注明"待额度恢复"后结束）。
6. 9/20 当天收口：不再创建接力任务，写整体总结到 `docs/PROGRESS.md`，能发版则打 tag 发 GitHub Release。
7. **提交纪律**：本机 git commit 前有 Mimosa 安全扫描钩子，会扫当前目录所在项目。
   一律用 `git -C <仓库绝对路径> commit ...` 形式，确保扫的是本仓库；
   若钩子报出本仓库以外路径的告警（误扫工作区），换 `-C` 形式重试即可，本仓库告警必须真修。

## 二、阶段表（对应任务书 §19）

| # | 阶段 | 内容 | 完成标准 | 状态 |
|---|------|------|----------|------|
| P0.5 | 可靠性闭环+真实回放 | 状态合并/HTTP 传输/run_id 隔离/主体一致性/行业门控/terms 控制/SSRF 重定向 + 16 家真实样本回放 | 全部自动测试绿；三平台 CI 绿；回放 16/16=MANUAL 红线语义；真实资料零改动 | ☑ 09-05（194 测试全绿） |
| P0 | 仓库基线修复 | 可靠安装/测试/构建：修 CI（删解析期失败条件与安装兜底）、修 setuptools 包发现、模板/配置随包分发、build 烟测、版本统一 0.3.0 | `pip install -e ".[dev]"` 成功；三平台 CI 实跑绿；wheel/sdist 隔离安装烟测过 | ☑ 09-04（107 测试全绿；安装版 Web 全链路冒烟过） |
| P1 | 架构骨架 | 目录结构、数据模型、9 态状态模型、SourceAdapter/SourceRouter/RuleEngine/SourceRegistry 抽象、SQLite 建表（§16 全部表）、pytest 骨架 | `pytest` 绿；`python -m app.main --help` 可运行 | ☑ 09-04（47 测试全绿） |
| P2 | 核心 Web UI | 本地 Web UI：项目创建、企业输入、地区/规则配置、核查任务页（FastAPI + 简单前端） | 浏览器可建项目、发起一次 mock 核查 | ☑ 09-04（8 场景 mock 全链路，52 测试全绿） |
| P3 | 全国数据源 | 逐个 adapter：信用中国、执行信息公开网、安全生产信用、建筑市场监管平台、gsxt（骨架） | 每个 adapter 有 fixture mock 测试；真实联调单列待办 | ◐ **adapter 骨架完成**（6 源：gsxt/creditchina/zxgk/mem/jzsc/pcczdc，fixture mock 测试全绿，含 SSRF 基座与传输状态映射）；**真实官网联调待 P3R**（query_url 人工复核回填 + 解析器按真实响应修正 + 验证码源真机联调，需白天人工配合） |
| P4 | 集团数据源 | 中国电建禁入供应商 adapter（ec.powerchina.cn）+ "待人工核查"兜底 | mock 测试绿；无法公开验证的必须返回 MANUAL | ☑ 09-05（manual_intake：查询恒 MANUAL；人工导入口径离线评判 10 测试绿；204 全绿） |
| P5 | 地区插件 | 四川完整插件 + 1 个非川插件（如广东）验证插件机制 | 两个插件不动核心代码即可注册生效 | ☑ 09-05（四川 sc_construction+sc_credit、广东 gd_construction；ast 锁定省名不进核心；docs/PLUGINS.md；214 测试绿） |
| P6 | 证据系统 | 截图/HTML 留痕、SHA-256、查询日志、人工复核流 | 每条结论可回链证据；哈希校验测试绿 | ☑ 09-05（响应原文落盘+SHA-256 回环/篡改检出；结果页证据回链+查看器；复核流绑 run_id；bqc import-bans 名单导入口离线评判闭环；221 测试绿） |
| P7 | 报告 | Excel 明细表（11 个 sheet）+ PDF 报告；openpyxl/reportlab 或等价 | 用 mock 数据生成两份样张；"查询失败"绝不写成"无异常" | ☑ 09-05（11 sheet 与 §16 表对应；PDF CID 中文字体；bqc report 子命令；样张已生成；"状态口径说明"sheet 明示红线；224 测试绿） |
| P8 | Windows 打包 | PyInstaller onefile/onedir + 启动脚本；用户数据写 `%LOCALAPPDATA%` | 本机打包成功可启动；CI 出 Windows artifact | ☐ |
| P9 | macOS 打包 | CI 产 macOS arm64 包（本机无 mac，全靠 GitHub Actions） | CI 出 `*-macOS-arm64.zip` artifact | ☐ |
| P10 | GitHub 收尾 | CI 完整化（pytest+win+mac 构建）、Release yml、Issue 模板、验收表 | 打 tag 自动出 Release 挂双平台产物 | ☐ |

## 三、红线（任务书硬性要求，违者即错）

- **状态模型**：PASS / WARNING / FAIL / MANUAL / NO_DATA / ERROR / TIMEOUT / BLOCKED / UNKNOWN。
  `ERROR / TIMEOUT / BLOCKED / MANUAL / UNKNOWN` **永远不得自动算作 PASS**；"没有查到"≠"确认不存在"。
- **架构**：三层数据源（全国 / 地区插件 / 招标人集团），四川逻辑绝不进主程序；
  adapter 只采集，RuleEngine 只评判，禁止选择器+判断混在一个函数。
- **不伪造**：官方平台查不了（验证码/改版/风控）→ 返回 MANUAL 并记入 `docs/ACCEPTANCE.md`，
  绝不假装查询成功。
- **测试**：全部用 fixture/mock，**夜间不得持续访问真实政府网站**；测试必须覆盖任务书 §18 底线清单
  （失败/超时/BLOCKED/MANUAL/UNKNOWN 不算 PASS、表面过期但官方延期、历史已解除不否决、同名不误匹配、日期窗口、路由等）。
- **禁提交**：内部名单、查询记录、数据库、证据截图、Cookie、Token、`.env`、`local/`。
  真实测试企业数据（任务书 §20）只存 `local/`。
- **合规**：不破解验证码、不绕 WAF、不代理池、不高频并发；同一政府网站同一时刻只查一个企业。
- **SSRF 防护**：adapter 发起服务端请求只允许 http/https；请求前校验 host，拒绝 localhost、
  环回、私有与保留地址；official_home/query_url 一律来自 `app/config/sources_registry.yaml` 并记录进证据。

## 四、夜间现实约束（务必清醒）

- gsxt / zxgk 等官网有验证码和风控，**无人值守时段只做 adapter 骨架 + mock 测试 + 页面结构调研笔记**；
  需要"自动导航+人工验证+继续解析"的真机联调，留给用户白天配合，在 PROGRESS 里列为待办。
- 每夜目标 1 个阶段（或大阶段拆 2-3 夜），**质量与测试优先，不追进度刷代码**。
- 网络经本机代理（Clash 7877 已配置好系统代理），访问 GitHub 正常；访问中国政府网站建议 requests 直连不走代理。

## 五、版本策略

- v0.1.0 = P1+P2（可运行骨架，pytest 绿）
- 之后每完成一个阶段递进一个 minor（v0.2.0…）
- P8 完成后发第一个 GitHub 预发行（挂 Windows 包）；9/20 最终夜发收口版本（尽力而为）
- CHANGELOG.md 每阶段更新
