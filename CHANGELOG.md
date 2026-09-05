# Changelog

All notable changes to this project will be documented in this file.

## [0.19.0] - 2026-09-05（第二轮独立审计整改：报告安全 / 结论诚实性 / 并发加固）

> 本轮合并另一独立 AI 审计（Arena 会话工作区，基于 v0.18.0 的 improvements.patch）。
> 其与 0.18.1 重合的发现（证据串源、截断哈希、场景校验、serve 监听、SQLite 并发）
> 已在 0.18.1 先行修复，此处只收录本轮真实新增项；证据落盘哈希方案沿用 0.18.1 的
> 字节级实现（比补丁版更严）。

### Fixed
- **Excel 公式注入（安全）**：reports/excel.py 新增 `_cell()` 消毒——`=` `+` `-` `@`
  制表/回车开头的第三方文本（企业名/处罚描述/名单备注）前置单引号强制按文本处理，
  全表（含表头）统一走消毒，不给 CSV 再导出留公式执行机会
- **PDF 长文本溢出 + 特殊字符崩溃**：reports/pdf.py 全部单元格改 Paragraph 渲染
  （XML 转义 + 换行转 `<br/>` + CJK 字体），长企业名自动折行不再被裁，
  含 `& <` 的网页原文不再解析失败
- **演示链路虚构"查询成功"**：mock 路径未实际查询的源改记 NO_DATA 并注明原因
  （此前全部记 PASS，报告凭空声称查过所有官方源）；主源加注"仅主源返回演示数据"
- **runner 层未知演示场景**：抛 ValueError 带可选场景列表（Web 层 0.18.1 已拦 400，
  本轮补齐 CLI/直接调用方）
- **`bqc serve` 非回环监听**：0.18.1 的硬拒绝改为显式 `--allow-lan` 放行 + 告警
  （默认仍然拒绝，退出码 2）
- **`import app.web.server` 建库副作用**：改为 `ensure_db()` 首次请求时按当次
  BQC_DB 解析建库，DB_PATH 保留兼容旧引用
- **SQLite 并发**：`connect()` 升级 timeout=30 + WAL + busy_timeout=30000
  （0.18.1 为 5s/初始化期 WAL）

### Added
- PDF 报告补齐"判定依据/发现明细/证据清单"三节（此前只有状态没有理由，不可复核）
- 证据落盘携带数据源登记等级（`evidence_grade`），决定能否支持 FAIL 的关键属性不再为空
- Excel/PDF/结果页统一新增**「数据来源」口径行**：mock 演示链路与真实官方查询显式区分
- `years_back`（近 N 年窗口）从死参数变为透明提示：窗口外记录在判定依据里显式标注，
  只提示不降级——机器绝不因超窗口自行把 FAIL 抹成 WARNING
- 本地 Web UI 跨站写请求同源校验（Origin/Referer 非本机 → 403；无来源头的
  CLI/脚本/TestClient 不受影响）
- pyproject 新增 `recon` 可选依赖组（playwright，与 P3R 侦察脚本配套，不拖慢 CI）
- `tests/test_audit_fixes.py`：18 条审计回归测试（合入时 16/18 直接通过，
  余 2 条为合并过程引入的问题，修复后全绿）

### 测试
- 257 → 275 项全绿

## [0.18.1] - 2026-09-05（外部复核整改：证据链按源隔离 + 输入校验闭环）

### Fixed（P0）
- **证据串源（runner.py）**：真实链路落证循环复用上一循环的 `out` 变量——每个源
  落盘的都是最后一个源的响应原文；尾源无原文时前面成功源的证据全部丢失；
  全部源在赋值前异常时还会 UnboundLocalError。改为 `outcomes[source_id]`
  逐源登记，落证/查询 URL/状态/正文严格按源对应
- **历史禁入名单永久参判（runner.py）**：`_load_imported_findings` 曾合并某来源
  全部历史导入文件——旧版名单未移除的企业会被永久误判。改为每个来源只评判
  最新一份完整快照（captured_at/id 最新且哈希可复核），历史证据只留档不参判，
  最新快照损坏不回退旧快照

### Fixed（P1）
- **大证据必然哈希校验失败（evidence.py）**：先算哈希再追截断标记，触发截断的
  证据 100% 自检"损坏"。新增 `evidence_payload()`：截断标记拼进正文后按最终
  字节算哈希、写盘、校验三处同源；DB 登记失败自动清理孤立证据文件
- **非法输入静默降级（web/server.py）**：未知演示场景曾落到 mock 兜底分支近似
  "无异常"。现白名单校验 400；并补齐表单校验：项目/企业名称非空+长度上限、
  USCC 去空格转大写+GB 32100 校验位验证、条款白名单、复核人必填、
  `terms` 改不可变默认

### Changed
- 注册表配置错误启动即报错（registry.py）：重复 id/未知字段/非法 automation_mode/
  owner 源缺 owner_group 一律 ValueError，不再静默覆盖或丢弃
- SQLite 并发加固（db.py）：`busy_timeout=5000` + 初始化启用 WAL；
  `app_versions` 改按"当前版本不存在"登记（旧库升级也能登记新版本）
- `bqc serve --host` 仅允许 127.0.0.1/localhost/::1（无认证工具不得暴露局域网）
- README 状态行与实际成熟度对齐

### 测试
- 241 → 257 项全绿：逐源证据隔离×3、名单快照替代×1、截断哈希/孤立文件×2、
  注册表校验×4+用例改判×1、Web 输入校验×6

## [0.18.0] - 2026-09-05（CLI 体验收口：证据校验入口 + 友好报错）

### Added
- CLI `bqc verify-evidence --db <路径>`：随时复核证据完整性（SHA-256 比对，
  正常/损坏分列，退出码区分）——验收（UAT C 组）与日常自查两用

### Fixed
- `bqc report` 对不存在的核查记录：友好提示退出码 2（此前堆栈）
- `bqc import-bans` 文件不存在：友好提示退出码 2（此前堆栈）
- report 对空库自动先建表

### 测试
- 240 → 241 项全绿

## [0.17.0] - 2026-09-05（联调工具链闭环：实测响应一键留证）

### Added
- `bqc check-source --save-evidence <db>`：单源联调实测的真实响应原文一键存为
  SHA-256 哈希证据（kind=p3r_probe），与 P6 证据系统/回放链打通——
  侦察→回填→实测留证→离线评判 的 P3R 工具链闭环
- 测试 239 → 240 项全绿

### Fixed
- 修复 check-source 分支局部 import 遮蔽模块级 init_db 的 UnboundLocalError
  （经典 Python 作用域坑，CLI 测试当场暴露即修）

## [0.16.0] - 2026-09-05（P3R 工具：门户自动侦察脚本）

### Added
- scripts/recon_portal.py：官方门户自动导航侦察——打开入口、填入测试企业名、
  点击查询、截图 2 张、捕获页面发出的接口请求候选（candidates.json）。
  供白天人工复核使用：人看截图与候选清单确认后**手工**回填（工具不回填）。
  已用本机假门户离线验证（自动捕获 /api/search?q=... 候选）。
  依赖为开发用（playwright/pyyaml，非运行时依赖，不进打包产物）。
- docs/P3R_CHECKLIST.md 增加快捷方式说明

### 纪律
夜间不运行（WORKPLAN 真实站点访问仅限白天人工配合）；单页低频；遇验证码截图即停。

## [0.15.0] - 2026-09-05（文档一致性收口：README 版本漂移修复+测试锁死）

### Fixed
- README 状态行版本漂移（停在 v0.12.0，实际 0.14.0）——即 P0 任务书 §六点名的
  漂移问题类；已修正并新增回归测试：README"状态：vX.Y.Z"必须与 app.__version__
  一致（0.12.0→0.14.0 期间漂移两个版本未被发现，本轮测试永久锁死）

### 测试
- 238 → 239 项全绿

## [0.14.0] - 2026-09-05（验收准备：UAT 手册 + 联调工具离线实测）

### Added
- docs/UAT.md 用户验收手册：Windows/macOS 便携包、Web 全链路、报告与证据的
  逐步操作单（操作→预期→勾选），含常见问题（SmartScreen/Gatekeeper/端口占用）
- P3R 复核工具 bqc check-source 离线端到端实测：夜间门控拒绝（退出码 2）、
  白天覆盖放行、未知源拒绝、未复核源 MANUAL 如实输出——四条路径全部验证

### 测试
- 233 → 238 项全绿（含上一独立复核轮六项修复的回归）

## [0.13.0] - 2026-09-05（独立复核轮：六项 A 类缺陷修复）

### Fixed（全数附回归测试）
- 报告"数据源注册表"sheet 恒为空：DB source_registry 表无任何写入方——
  改读包内 sources_registry.yaml（权威登记处），sheet 如实呈现全部源与模式
- 证据文件写入编码与哈希不一致（utf-8 严格 vs replace）：孤立代理字符会让
  证据落盘崩溃——统一 errors=replace，回环一致（测试：代理字符样例）
- runner 证据落盘失败会中断整轮核查：降级为 stderr 告警，结论照常出
  （测试：证据目录被文件占位时核查完成）
- Web 同项目同企业重复提交 → UNIQUE 约束 500：幂等复用既有记录（重跑语义）
- years_back 无服务端校验（负数/超大值直通）：钳制 1~10（前端 min/max 不可信）
- 证据查看器路径校验用前缀判断（/evil 可绕过 /ev）：改 contains 关系判定
  （测试：DB 行被篡改指向 /etc/passwd → 400）

### 说明
- 本轮为独立复核轮：系统性排查报告/证据/Web/runner/CLI，六项缺陷全部
  在复核中发现并即修，233 → 238 项测试全绿

## [0.12.0] - 2026-09-05（P3R 准备：复核作业清单 + 单源联调工具）

### Added
- docs/P3R_CHECKLIST.md：逐源人工复核作业清单（复核入口/当前模式/解析契约假设/
  已实测风控提示/回填示例/完成判据）
- CLI `bqc check-source <source_id> --name 企业 [--uscc 码]`：单源联调诊断，
  受 nightly_mock_only 门控（白天人工复核显式 --daytime-override）；
  输出状态/注记/发现/主体匹配，失败状态不美化
- docs/SUMMARY.md：项目整体总结（十阶段/红线兑现/如实清单/下一步），供 9/20 收口

### 测试
- 228 → 233 项全绿（tests/test_diagnostics.py：门控/未知源/MANUAL 输出/注入查询/CLI）

## [0.11.0] - 2026-09-05（P10 收尾：打 tag 自动 Release，双平台产物）

### Added
- .github/workflows/release.yml：push tag `v*` 自动执行——三平台 pytest 门 →
  wheel/sdist 构建 → Windows exe 打包冒烟（LOCALAPPDATA 断言）→ macOS arm64
  打包冒烟（serve 实访问断言）→ 自动创建 GitHub Release 并挂全部产物
  （wheel/sdist/Windows zip/macOS zip/SHA256SUMS），说明文字自动取自 CHANGELOG
  对应版本章节（scripts/extract_changelog.py）
- 本 v0.11.0 Release 即由该工作流自动生成（完成标准实证）

### 说明
- WORKPLAN 十个阶段（P0~P10）至此全部完成；真实官网联调（P3R）与各源
  query_url 人工复核仍为待办，需白天人工配合——"已支持数据源清单"在真实
  联调完成前保持未勾选，不伪造支持状态

## [0.10.0] - 2026-09-05（P9 macOS 打包：PyInstaller arm64 + .command 启动脚本）

### Added
- scripts/start_server.command（可执行位入库）：双击即起本地 Web UI
- CI 新增 package-macos job：PyInstaller arm64 构建 → frozen 冒烟
  （--version/--help/init-db 落 `~/Library/Application Support/bqc/data/` 断言
  + serve 首页实访问验证）→ zip 保留可执行位 → artifact；Release 附该包
- 本机 M4 实测：同一 spec 构建、.command 启动、首页渲染、数据目录全过；
  CI 产物下载后本机复验 --version 通过

### 测试
- 228 项全绿；CI 六 job（三平台 test + build + package-windows + package-macos）实跑全绿

## [0.9.0] - 2026-09-05（P8 Windows 打包：PyInstaller onefile + %LOCALAPPDATA%）

### Added
- app/paths.py：数据路径单点解析——源码/CLI 运行落当前工作目录 data/（行为不变）；
  PyInstaller frozen 下 Windows 落 `%LOCALAPPDATA%\bqc\data\`、macOS 落
  `~/Library/Application Support/bqc/data/`；BQC_DB 环境变量优先级始终最高
- entry_bqc.py + bqc.spec：onefile 控制台应用 bqc(.exe)；注册表动态导入的
  10 个数据源 adapter 全部显式 hiddenimports；config/templates 随包分发
- scripts/start_server.bat：本地 Web UI 启动脚本（随 zip 分发）
- CI 新增 package-windows job：构建 exe → frozen 冒烟（--version/--help/init-db
  落点断言 %LOCALAPPDATA%）→ zip 上传 artifact；Release 附该 Windows 便携包

### 测试
- 224 → 228 项全绿（tests/test_paths.py：frozen 各平台路径解析 4 项）
- 本机 Mac 实测 spec：构建→CLI→init-db 用户目录→serve 首页渲染全过

## [0.8.0] - 2026-09-05（P7 报告：Excel 明细 11 sheet + PDF）

### Added
- Excel 核查明细表（app/reports/excel.py）：11 个 sheet 与任务书 §16 表结构对应
  （封面与汇总/项目/企业/条款结论/查询日志/发现明细/证据清单/人工复核/数据源注册表/
  状态口径说明/免责与合规声明）；取数口径=最新一次完整核查运行（与 Web 结果页一致）
- PDF 核查报告（app/reports/pdf.py）：reportlab 内置 CID 中文字体（无需外部字体文件），
  汇总/条款结论/查询日志/口径声明四节
- CLI：`bqc report <pc_id> --excel x.xlsx [--pdf y.pdf]`（最新完整批次的报告导出）
- scripts/make_report_samples.py：mock 演示样张生成（限制投标 FAIL/查询失败 ERROR/
  无记录 NO_DATA 三场景）

### 红线落实
- 全部状态用语统一走 report_label——"查询失败/超时/待人工"绝不写成"无异常/正常"；
  Excel"状态口径说明"sheet 与 PDF 声明节明示该红线

### 测试
- 221 → 224 项全绿（tests/test_reports.py：11 sheet 断言、ERROR=查询失败且全表
  无"正常"、FAIL=触发否决条款、PDF 生成+文本抽取、CLI 子命令）

## [0.7.0] - 2026-09-05（P6 证据系统：SHA-256 留痕、回链、人工复核流、名单导入口）

### Added
- 证据落盘与校验（app/core/evidence.py）：真实响应原文写入证据目录（随数据库，
  gitignored），SHA-256 登记，verify 随时复核完整性——篡改/损坏/缺失必被检出；
  单证据 5MB 截断保护并在文内注明
- runner 真实链路逐源落证据：证据行绑定产生它的 source_queries.id（结论可回链）；
  mock 演示链路不落盘（证据只来自真实采集）
- Web：结果页"数据源查询日志（证据回链）"（证据 kind+哈希前缀+时间+查看链接）、
  证据原文查看器（路径穿越防护）；人工复核流——每条源查询可提交复核
  （复核人/结论/备注），绑定核查批次 run_id，作为审计记录展示、不自动改判机器结论
- CLI：`bqc import-bans <file>` 名单人工导入口（文件 SHA-256 留证，名单文件不入库）；
  manual_intake 源核查时自动读取导入证据，经主体一致性检查离线评判——
  人工证据触发条款 → decision=FAIL 且 data_status=MANUAL/manual_required 保留；
  同名不同码名单记录在落库前剔除

### 测试
- 214 → 221 项全绿（tests/test_evidence.py：哈希回环/篡改检出/回链/查看器/
  复核流/导入评判闭环/错主体不绑定）

## [0.6.0] - 2026-09-05（P5 地区插件机制：四川 + 广东）

### Added
- 地区插件层 `app/sources/regions/`：四川插件（sc_construction 建筑市场监管
  资质/安许/诚信 + sc_credit 信用四川薄封装）与广东插件（gd_construction，
  复用全国 jzsc 契约）——新增省插件不改任何核心代码，仅插件包+注册表条目
- base 传输层新增 `manual` 模式注记：人工核查模式查询恒 MANUAL（附说明文案）
- docs/PLUGINS.md 地区插件开发说明：机制/契约/automation_mode 口径/红线/最小步骤

### 测试
- 204 → 214 项全绿（新增 tests/test_region_plugins.py 10 项，含红线锁定测试：
  ast 扫描核心代码——省名只允许出现在注释/文档示例，字符串常量与标识符零容忍）

## [0.5.0] - 2026-09-05（P4 集团数据源：中国电建禁入供应商 adapter）

### Added
- `app/sources/owners/powerchina.py`：中国电建禁入/受限供应商名单 adapter
  （三级口径：股份公司级/子企业级/基层单位级；记录带 document_name 证据溯源字段）
- 人工导入离线评判契约：名单记录（subject_name/subject_uscc + list_level/scope/
  起止日期）经主体一致性关卡后产出客观 owner_ban Finding，条款4 由 RuleEngine 评判——
  有效期内 FAIL、过期仅 WARNING、他集团记录不适用、缺码记录转人工
- 注册表 automation_mode=manual_intake：内部名单公开门户不可自动核验，
  查询一律 MANUAL（模式注记优先于"URL 未复核"注记），绝不伪造查询成功
- 路由：集团专项源与项目招标人集团不匹配时显式 NOT_APPLICABLE（原为静默跳过）

### Fixed
- engine 主体一致性纵深加固：DIFFERENT_SUBJECT 记录在任何入口都不得形成证据
  （此前仅 adapter 层剔除，人工导入直调 parse 的路径可绕过——同名不同码的
  内部名单记录可能误判 FAIL，P4 专项测试暴露后即修）

### 测试
- 194 → 204 项全绿（新增 tests/test_owner_powerchina.py 10 项）

## [0.4.0] - 2026-09-05（P0.5 可靠性闭环 + 真实业务样本回放）

### Fixed
- **状态合并闭环（§三）**：旧单一严重度表 WARNING 盖过 MANUAL/BLOCKED/TIMEOUT/ERROR，
  "风险提示"会掩盖数据异常与人工复核要求。改为决策层/数据层分层合并
  （combine_decision/combine_data/overall），数据层 NEVER_PASS 优先于 WARNING/PASS/NO_DATA；
  FAIL 抢占展示位时数据异常与人工要求经 data_status/manual_required 保留
- **默认 HTTP 传输层闭环（§四）**：httpx 原生异常此前无人接（单源网络异常炸整轮核查），
  现 TimeoutException→TIMEOUT、RequestError→ERROR；403/418/429/503→BLOCKED 统一口径；
  DNS 复检 UnsafeUrlError→BLOCKED；runner 逐源 try/except 单源异常记 ERROR 带追溯不中断；
  httpx 进运行时依赖
- **Project.terms 真正控制规则（§八）**：rules.yaml 挂结构化 clause+scope，
  未启用条款落 NOT_APPLICABLE 显式留痕；background（§6）恒评估但绝不单独否决项目资格

### Added
- **核查批次 run_id（§五）**：check_runs 表每次运行唯一 run_id，source_queries/
  rule_results 绑定批次，findings 经 query 可溯；Web 只展示最新一次完整运行；
  0.3.x 旧库幂等迁移补列，历史行 run_id=NULL 原样保留，绝不静默删除
- **主体一致性进入真实链路（§六）**：matching.check_subject 七条规则（同名不同码≠同一
  主体、缺码不自动认定、模糊相似不认定）；源记录形成 Finding 前强制判定，可追溯字段
  （requested_*/source_subject_*/matched_by/match_result）随 attrs 留痕；
  DIFFERENT 剔除并留痕，UNCONFIRMED 绝不进业务条款、由兜底条款转人工
- **行业路由门控（§七）**：限定行业的数据源只对适用行业查询；不适用源落
  NOT_APPLICABLE（含原因）——≠"查询无数据"，不参与数据层合并，不硬查
- **SSRF 重定向逐跳校验（§九）**：默认传输禁用自动重定向，显式逐跳跟随（≤5 跳），
  每跳完整 URL 校验+DNS 复检；公网入口借 302 跳内网/环回/歧义 IP 字面量全被拦
- scripts/replay_samples.py 真实样本回放 harness；run_check 增 app_yaml 显式覆盖参数
  （白天人工复核场景，覆盖必须明示留痕）

### 真实样本回放结论（详细见仓库外本地记录）
- 样本 16 家（A/B/C/D/E 类，来源：局域网共享盘招标台账/履约评价汇总/资格审查 PDF），
  程序端到端 16/16 = MANUAL 待人工核查（6 源×16=96 次查询全 MANUAL——query_url
  未人工复核的红线行为），未伪造任何 PASS/NO_DATA 结论
- 官方三站（信用中国/建筑市场监管平台/gsxt）实测均拒绝非浏览器访问
  （40001 反自动化/加密响应/521 WAF）——程序的 MANUAL 预判与真实可自动化能力一致
- 差异根因：数据源覆盖不足（D）与反自动化（F）为主；新增 A/B/C 类缺陷 0 项；
  发现台账时效问题 3 例（C 类）与台账无 USCC 列（G 类，资料实情）

### 测试
- 108 → 194 项全绿（新增状态合并/传输映射/批次隔离/主体匹配/行业门控/terms 控制/
  SSRF 重定向共 7 个专项测试文件）

## [0.3.0] - 2026-09-04（P3 全国数据源 adapter 骨架 + P0 仓库基线修复）

### Fixed（P0 基线修复）
- **修复项目无法安装**：`[tool.setuptools] packages = { include = [...] }` 写法非法，
  setuptools 拒绝解析，`pip install -e .` 必失败（此前 CI 用 `|| pip install pytest`
  兜底掩盖了该问题）；改为 `[tool.setuptools.packages.find]` 自动发现 `app*` 全部包
- **修复 CI 解析失败**：删除 job 级 `if: ${{ hashFiles('tests/**/*.py') != '' }}`
  （该表达式使 workflow 在解析阶段即失败）；删除安装 `||` 兜底——项目装不上时 CI
  必须失败，不得靠单独安装 pytest 掩盖打包问题
- **修复版本漂移**：pyproject/app.__version__/DB 版本种子/CLI `--version` 统一为
  0.3.0；DB 版本种子改为以 `app.__version__` 为单点来源（0.1.0 硬编码清除）
- **修复中文输出在旧代码页 Windows 上崩溃**（三平台 CI 实跑暴露的真实产品缺陷）：
  CLI 编码契约明确化——管道/文件输出一律 UTF-8；真控制台保留本地代码页
  （中文 Windows cp936 显示不受影响），errors=replace 保证任何代码页下不崩溃。
  附带发现：父进程按本地代码页解码中文 UTF-8 管道输出时读线程会静默死亡
  （stdout=None），测试已显式按 UTF-8 解码子进程输出
- 修复安装版数据落点：Web UI 数据库默认路径由"仓库目录/data"改为当前工作目录
  `/data`（与 CLI init-db 一致），安装版不再往 site-packages 写数据

### Added（P0 基线修复）
- 配置移入 `app/config/` 随包分发（sources_registry/rules/app 三个 yaml），
  Web 模板经 package-data 进入构建产物——wheel/sdist 均自包含，脱离源码目录可运行
- `scripts/smoke_installed.py` 安装烟测：四模块导入、模板/配置在位、模板可解析、
  包元数据版本与 `app.__version__` 一致
- `tests/test_packaging.py` 打包回归测试（资源随包分发 + 版本单点来源）
- CI 新增 build job：`python -m build` 出 wheel+sdist，各自装入隔离 venv 后跑
  `pip check` / CLI / 烟测（脱离源码目录执行）；test job 增加 `pip check`、
  安装烟测与 CLI smoke
- `build` 加入 dev 依赖

### Added（P3 adapter 骨架）
- `app/sources/national/`：6 个全国源 adapter 骨架——信用中国、执行信息公开网、
  安全生产信用、建筑市场监管平台、破产重整信息网、gsxt（验证码源）
- SSRF 防护基座：仅 http/https；拒绝 localhost/环回/私有/保留地址，
  含十进制/十六进制点分与 IPv4-mapped IPv6 绕过形态；真实请求前复检 DNS 解析结果
- 传输层状态映射：超时→TIMEOUT、403/429 等风控→BLOCKED、其余网络/HTTP 错误→ERROR、
  2xx→查询成功；失败绝不归约 PASS，响应解析失败同按 ERROR
- 查询 URL 只认注册表：query_url 未人工复核（为空）→ 一律 MANUAL，不写死未复核接口
- 抽取管线输出客观 Finding（限制投标/证照当前状态/破产/法院记录等 kind），与 RuleEngine 联动
- 测试 +47 项共 99 项全绿：SSRF 专项、传输状态映射、各源 fixture mock 解析、
  规则联动（FAIL/WARNING/NO_DATA）、NEVER_PASS 不变量
- runner 真实数据源链路：`run_check(real_sources=True)` 按注册表逐源执行 adapter
  （传输层 get 可注入测试），受 `nightly_mock_only` 门控（夜间/演示模式拒绝真实查询）；
  数据源失败状态（TIMEOUT/ERROR/BLOCKED/MANUAL）折算进总体结论，绝不归约 PASS

### Fixed（P3）
- 演示场景 query_error 的总体结论由 NO_DATA 修正为 ERROR：
  此前数据源查询失败被吞（source_queries 全记 PASS、source_error 无规则消费）

### 待办（真实联调，留白天人工配合）
- 各源查询接口人工复核后回填 `query_url`/`last_verified`，解析器按真实响应格式修正
- zxgk/gsxt 验证码源：自动导航+人工验证联调；Web 层真实模式入口

## [0.2.0] - 2026-09-04（P2 本地 Web UI）

### Added
- 本地 Web UI（仅监听 127.0.0.1）：`bqc serve` 启动
- 首页表单：项目信息（名称/所在地/行业/招标人集团/基准日/近几年）+ 投标人（名称/USCC/注册地）+ 演示场景
- 核查结果页：总体结论徽章、条款核查明细（每条判定依据）、数据源查询日志
- 核查执行器 runner：数据源路由 → mock 采集 → 规则评判 → SQLite 落库 全链路
- 8 种 mock 演示场景，覆盖 4 条款 FAIL / 历史已解除 WARNING / 证照表面过期 / 查询失败 ERROR / 无记录 NO_DATA
- Web 测试 5 项：结果页保证 ERROR/NO_DATA 绝不显示为"正常"

## [0.1.0] - 2026-09-04（P1 架构骨架）

### Added
- 9 态状态机（PASS/WARNING/FAIL/MANUAL/NO_DATA/ERROR/TIMEOUT/BLOCKED/UNKNOWN），
  ERROR/TIMEOUT/BLOCKED/MANUAL/UNKNOWN 永不归约为 PASS；报告用语映射保证"查询失败"不显示为"正常"
- 企业模型与统一社会信用代码（USCC）同一性判定：同名不同码不误匹配
- 证据等级模型：仅 C/D 级线索不得作 FAIL，需 A/B 级闭环
- SourceRegistry：数据源注册表从 config/sources_registry.yaml 加载（9 个初始数据源登记）
- SourceRouter：全国共性 + 注册地(发证地) + 项目所在地 + 招标人集团专项 四维路由
- RuleEngine 五规则：限制投标（条款1）、停产停业/证照吊销（条款2）、破产清算（条款3）、
  集团禁入（条款4）、证照有效期特别规则（§6：表面过期仅 WARNING、官方已延期不判无证）
- SQLite 存储层：projects/companies/project_companies/source_registry/source_queries/
  findings/rule_results/evidence/manual_reviews/app_versions 共 10 表
- CLI：`bqc init-db` / `--help` / `--version`
- pytest 47 项全绿（含任务书 §18 底线：失败/超时/阻断/人工/未知不算 PASS、历史已解除不否决、
  同名不误匹配、日期窗口、地区路由、C/D 不判 FAIL）

## [Unreleased]

### Added (2026-09-04, 仓库初始化)
- 仓库骨架：README / WORKPLAN / LICENSE(MIT) / .gitignore / CI 占位 / Issue 模板
- 数据源注册表、规则、配置目录占位
- docs/PROGRESS.md 进度日志、docs/ACCEPTANCE.md 验收表
