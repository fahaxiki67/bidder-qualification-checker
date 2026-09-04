# 开发计划书（夜间自动开发执行手册）

> 本文件是每晚 23:00 自动开发会话的**第一入口**。任务书全文见
> `H:\ZCode_开发任务书_投标人资格智能核查系统.md`（H 盘不可用时用仓库内
> `local/taskdoc/` 备份，该目录已 gitignore，严禁提交）。
>
> 开发窗口：2026-09-04 晚 至 2026-09-20，共 17 夜，每夜 23:00 开始、**次日 09:00 前必须收口结束**。

## 一、夜间固定协议（每夜按此执行）

1. **接续**：读 `docs/PROGRESS.md` 最后 2-3 条记录 + 本文件阶段表，确认做到哪、今晚做什么。
2. **对齐远端**：`gh run list` / `git fetch origin && git log HEAD..origin/main --oneline`。
   远端有新提交（用户或其他会话推的）→ 以远端为基线继续；发现分叉 → 停下写清交接，**绝不 reset/clean/stash/强推**。
3. **守卫**（命中则只收口退出并写明原因）：
   - 用户正在 actively 使用机器（前台大量交互、怪异输入）→ 收口退出；
   - 工作树有与本任务无关的未提交改动 → 停下报告，不动它们。
4. **推进**：按阶段表做今晚的事，小步实现；每个模块写 pytest，**全量测试绿了才 commit + push**。
5. **08:30 收口**（硬性）：全量 pytest → 更新 `docs/PROGRESS.md`（今晚完成 / 遗留 / 下一步）→
   最终 commit + push → 结束会话。**09:00 前必须结束，不跨窗口。**
6. 最后一夜（9/20 晚）额外：写整体总结到 `docs/PROGRESS.md`，能发版则打 tag 发 GitHub Release。

## 二、阶段表（对应任务书 §19）

| # | 阶段 | 内容 | 完成标准 | 状态 |
|---|------|------|----------|------|
| P1 | 架构骨架 | 目录结构、数据模型、9 态状态模型、SourceAdapter/SourceRouter/RuleEngine/SourceRegistry 抽象、SQLite 建表（§16 全部表）、pytest 骨架 | `pytest` 绿；`python -m app.main --help` 可运行 | ☐ |
| P2 | 核心 Web UI | 本地 Web UI：项目创建、企业输入、地区/规则配置、核查任务页（FastAPI + 简单前端） | 浏览器可建项目、发起一次 mock 核查 | ☐ |
| P3 | 全国数据源 | 逐个 adapter：信用中国、执行信息公开网、安全生产信用、建筑市场监管平台、gsxt（骨架） | 每个 adapter 有 fixture mock 测试；真实联调单列待办 | ☐ |
| P4 | 集团数据源 | 中国电建禁入供应商 adapter（ec.powerchina.cn）+ "待人工核查"兜底 | mock 测试绿；无法公开验证的必须返回 MANUAL | ☐ |
| P5 | 地区插件 | 四川完整插件 + 1 个非川插件（如广东）验证插件机制 | 两个插件不动核心代码即可注册生效 | ☐ |
| P6 | 证据系统 | 截图/HTML 留痕、SHA-256、查询日志、人工复核流 | 每条结论可回链证据；哈希校验测试绿 | ☐ |
| P7 | 报告 | Excel 明细表（11 个 sheet）+ PDF 报告；openpyxl/reportlab 或等价 | 用 mock 数据生成两份样张；"查询失败"绝不写成"无异常" | ☐ |
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
