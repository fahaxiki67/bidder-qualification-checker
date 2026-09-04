# Changelog

All notable changes to this project will be documented in this file.

## [0.3.0] - 2026-09-04（P3 全国数据源 adapter 骨架）

### Added
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

### Fixed
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
