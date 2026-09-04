# 投标人资格智能核查系统 / Bidder Qualification Checker

> 输入企业名称或统一社会信用代码 + 项目信息（所在地、行业、招标人集团、资格条款），
> 自动查询多个官方公开来源，把公开数据与本项目资格审查条款对应起来，
> 形成可追溯的资格前审证据链，导出 Excel 核查表与 PDF 核查报告。

**状态：开发中（WIP，v0.4.0）。** 可靠性闭环（P0.5：状态合并/批次隔离/主体一致性/行业门控/terms 控制/SSRF 重定向）已完成； 架构骨架（P1）、本地 Web UI（P2）、
全国数据源 adapter 骨架（P3）已完成，仓库基线修复（P0：可靠安装/CI/打包）已完成；
按 `WORKPLAN.md` 分阶段推进，进度见 `docs/PROGRESS.md`。

**如实声明：全国官方平台的真实自动查询尚未完成。** 各源 `query_url` 须经人工复核后
回填注册表，此前真实查询一律返回 MANUAL（待人工核查）；目前可运行的是 mock 演示链路。
各平台逐项状态见 `docs/ACCEPTANCE.md`。

## 核心特性（规划）

- 三层数据源架构：全国通用 + 地区插件 + 招标人集团专项，绝不写成某省专用
- `SourceRouter` 路由：注册地 / 发证地 / 项目所在地 / 行业 / 招标人 / 条款 多维决定查什么
- 采集与评判分离：Source Adapter 只回答"官方来源查到了什么"，Rule Engine 回答"是否触发否决条款"
- 严格状态模型：`ERROR / TIMEOUT / BLOCKED / MANUAL / UNKNOWN` 永远不得自动算作 PASS
- 证据链：每条结论可回溯到带 SHA-256 的原始证据（URL / 时间 / 截图 / 关键文字）
- 输出：Excel 核查明细（兼容 Excel/WPS）+ PDF 核查报告，"查询失败"绝不写成"无异常"

## 架构

```text
app/
├─ core/          # models / router / rules / evidence / runner / db
├─ sources/
│  ├─ national/   # gsxt、信用中国、执行信息公开网…（P3 骨架已就位）
│  ├─ regions/    # sichuan/ guangdong/ …（地区插件，P5）
│  └─ owners/     # powerchina/ …（招标人集团禁入名单，P4）
├─ web/           # 本地 Web UI（P2；templates 随包分发）
├─ config/        # sources_registry.yaml / rules.yaml / app.yaml（随包分发的唯一登记处）
└─ main.py        # CLI 入口（bqc）
```

## 安装与运行

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"     # Windows
.venv/bin/pip install -e ".[dev]"         # macOS/Linux
pytest                                    # 全量测试
bqc init-db                               # 初始化 SQLite（当前目录 data/）
bqc serve                                 # 启动本地 Web UI（仅监听 127.0.0.1）
```

安装版自包含：`app/config/` 配置与 `app/web/templates/` 模板随 wheel/sdist 分发，
`python -m build` 产物可在脱离源码目录的环境安装运行（CI build job 自动验证）。

## 合规声明

- 本工具仅做公开信息的自动查询与整理，不破解验证码、不绕过反自动化、不伪造身份；
  遇验证码/登录时暂停并转人工验证。
- "未查到"与"确认不存在"严格区分；机器结论不替代人工复核与招标文件条款解释。
- 仓库不含任何企业内部受限名单、用户查询记录、证据截图与登录凭证。

## License

[MIT](LICENSE)
