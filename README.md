# 投标人资格智能核查系统 / Bidder Qualification Checker

> 输入企业名称或统一社会信用代码 + 项目信息（所在地、行业、招标人集团、资格条款），
> 自动查询多个官方公开来源，把公开数据与本项目资格审查条款对应起来，
> 形成可追溯的资格前审证据链，导出 Excel 核查表与 PDF 核查报告。

**状态：开发中（WIP）。** 当前为仓库初始化骨架，按 `WORKPLAN.md` 分阶段推进，
进度见 `docs/PROGRESS.md`。

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
├─ core/          # models / router / rules / evidence / tasks
├─ sources/
│  ├─ national/   # 国家企业信用公示、信用中国、执行信息公开网…
│  ├─ regions/    # sichuan/ guangdong/ …（地区插件，逐省添加）
│  └─ owners/     # powerchina/ …（招标人集团禁入名单）
├─ reports/       # Excel + PDF 生成
├─ web/           # 本地 Web UI
└─ main.py
config/
├─ sources_registry.yaml   # 数据源注册表（URL 一律在此登记，不散落源码）
├─ rules.yaml              # 资格审查条款
└─ app.yaml
```

## 开发

```bash
python -m venv .venv
.venv/Scripts/pip install -e .[dev]     # Windows
.venv/bin/pip install -e ".[dev]"       # macOS/Linux
pytest
```

## 合规声明

- 本工具仅做公开信息的自动查询与整理，不破解验证码、不绕过反自动化、不伪造身份；
  遇验证码/登录时暂停并转人工验证。
- "未查到"与"确认不存在"严格区分；机器结论不替代人工复核与招标文件条款解释。
- 仓库不含任何企业内部受限名单、用户查询记录、证据截图与登录凭证。

## License

[MIT](LICENSE)
