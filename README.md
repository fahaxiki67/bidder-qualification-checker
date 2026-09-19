# 投标审查器 / Bidder Review Checker

> 一体化支持企业资格前审证据链，以及多家投标文件的本地离线风险预警。
> 原有资格核查入口仍使用 `bqc`，以保持兼容。

**状态：v0.23.0 正式版（rc.1~rc.4 预发布候选的收口版本；资格审查与离线多投标文件预警已接入，支持 txt/md/csv/json/xlsx/pdf；真实官网联调 P3R 仍待人工配合——作业清单见 docs/P3R_CHECKLIST.md，双平台验收操作单见 docs/UAT.md）。** 可靠性闭环（P0.5：状态合并/批次隔离/主体一致性/行业门控/terms 控制/SSRF 重定向）已完成； 架构骨架（P1）、本地 Web UI（P2）、
全国数据源 adapter（P3：解析器已实现，真实接口响应格式待联调复核）、集团禁入 adapter（P4）、地区插件机制（P5：四川+广东）、证据系统（P6）、报告（P7：Excel 明细 11 sheet + PDF，bqc report）已完成，
可靠性闭环（P0/P0.5）已完成；
按 `WORKPLAN.md` 分阶段推进，进度见 `docs/PROGRESS.md`。

**如实声明：全国官方平台的真实自动查询尚未完成。** 各源 `query_url` 须经人工复核后
回填注册表，此前真实查询一律返回 MANUAL（待人工核查）；目前可运行的是 mock 演示链路。
各平台逐项状态见 `docs/ACCEPTANCE.md`；离线文件审查口径见 `docs/OFFLINE_REVIEW.md`。

## 浏览器离线审查（`web/`）

另提供纯浏览器界面：文件在当前浏览器内存中解析、不上传，并支持 `.xls` / `.docx`。
不替代 `bqc serve` 的本地服务端页面（`app/web/`）。说明见 [`web/README.md`](web/README.md)。

```bash
cd web
npm install
npm run dev
```

## 多投标文件离线审查


离线审查只读取用户明确提供的本地资料，不联网、不上传、不修改原文件。支持
`.txt`、`.md`、`.csv`、`.json`、`.xlsx`、`.pdf`（文本层与本机 OCR）；`.xls`、`.docx` 当前不作为输入解析。
Web `/review-bids` 读取的是运行 Web 服务的服务端所在机器上的本地路径；页面无账号鉴权，
默认只监听回环地址。Web 输入目录和关联线索文件默认必须位于服务当前工作目录内；
需要使用其他目录时先设置 `BQC_REVIEW_ROOT`。若显式使用 `bqc serve --allow-lan`，
仅应在可信网络临时使用。

推荐目录布局为“一级子目录名=投标人”：

```text
project-bids/
├─ 投标人甲/报价.xlsx
├─ 投标人甲/施工组织设计.md
├─ 投标人乙/报价.csv
└─ 投标人乙/施工组织设计.txt
```

也支持根目录文件命名为 `投标人名称__文件名.ext`。可选的本地关联线索 CSV/JSON
可提供 `bidder_a`、`bidder_b`、`relation`、`source` 字段；原值和来源哈希会保留，
但只形成“人工复核”信号。

```bash
bqc review-bids ./project-bids \
  --project "某项目" \
  --relations ./relations.csv \
  --output-json ./outputs/bid-review.json \
  --output-report ./outputs/bid-review.md
```

当前已启用预警规则为：F-01 报价接近、F-02 报价低离散、F-03 报价离群、F-04 可比清单项同步、
F-05 报价近似等差/等比、F-06 相对控制价下浮率一致、F-07 报价接近二档、E-01 电子元数据相同、E-02 银行/保证金账户字段相同、S-01 文件内容一致、
S-02 文本高相似、S-03 文件结构相似、S-04 可比清单项目构成一致、S-05 大段共用文本、P-01 本地关联线索、
P-02 人员字段重合、P-03 亲属关系线索、P-04 人员长表同人任职重合。E-01 仅比较作者、机器码、MAC、IP、硬盘序列号、
数字证书等电子字段，人员字段由 P-02 单独提示；S-04 仅使用 `COMPARABLE` 的 `comparison_key`。
F-06 仅使用文件中识别为 `kind=control` 的“招标控制价”“最高限价”或“控制价”，控制价不会成为
`primary_quote`。所有信号均为人工复核线索，`auto_conclusion=false`，整份结果为
`manual_review_required=true`。阈值是筛选参数，不是法律推定；任何单一报价、IP、MAC、作者、
文件名、联系人或文本相似信号，都不得自动认定串通投标、违法、资格不合格或投标无效。正式判断
须由有权主体结合招标文件、电子投标平台日志、签名/证书、下载上传记录、原始文件和其他事实证据人工完成。

XLSX 原生数值按单元格类型解析；`123.456` 等存在小数/千分位歧义的文本金额跳过并提示核对。
PDF 逐页提取文本；无文本及含图像的页面自动调用本机 OCR，报价保留页码和识别方式。失败或达到预算时标为部分解析，未完整读取的文件不参与全文相似度比较。
启用 OCR 的 Windows/Mac 发布构建将 Poppler、Tesseract 和 `chi_sim`/`eng` 语言包内置，并通过清空外部工具 PATH 的扫描件验收。源码/Python 安装方式需另行安装这些工具，使 `pdftoppm`、`tesseract` 可从 PATH 调用。
每份 PDF 最多 600 MB、2000 页；OCR 最多尝试 50 页、累计 120 秒，文本最多 1000 万字符。OCR 金额必须对照原页人工复核；配置及测试方法见 [离线审查说明](docs/OFFLINE_REVIEW.md)。
清单项跨投标人对齐要求名称、单位和规格/项目特征均有明确且一致的值；缺失字段的明细会保留
并标记为数据不足，不按名称自动合并，也不自动做单位换算。离线扫描还会跳过并记录符号链接，
限制输入文件数量与总大小，并在解析 XLSX 前限制 ZIP 成员数、声明解压大小和第二次审计读取的单元格数；
JSON 递归也有深度/节点预算。结果 `config.limits` 明示 `max_json_depth`、`max_json_nodes` 和
`max_xlsx_audit_cells`。

### 法律与适用范围边界

实现仅把下列现行规则和政策作为“应留证、应复核”的设计背景，不把算法输出替代法律认定：

- [《中华人民共和国招标投标法》](https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/bgt/art/2023/art_1f79dd79321441a0831f3aed697b4535.html)
  与[《中华人民共和国招标投标法实施条例》](https://xzfg.moj.gov.cn/front/law/detail?LawID=1154)：
  重点关注协商报价、约定中标/放弃、同一编制或办理、文件异常一致/报价规律性差异、
  文件混装、保证金同账户，以及单位负责人/控股或管理关系等法定边界；其中 E-02 只从投标资料账户字段
  形成待核线索，不能替代第40条第6项关于保证金转出账户的完整事实证据和适用程序。
- [《电子招标投标办法》（国家发展改革委令第20号）](https://www.ndrc.gov.cn/xxgk/zcfb/fzggwl/201302/t20130220_960752.html?state=123)：
  关注电子签名、来源、时间、网络地址、归档和可追溯日志；电子评标系统的异常分析只能作为辅助。
- [发改法规规〔2022〕1117号意见](https://www.ndrc.gov.cn/xxgk/zcfb/ghxwj/202208/t20220801_1332495.html)：
  可作为异常低价、严重不平衡报价、关联关系、人员混用等风险观察的政策背景，不是新增法定推定。
- [浙江省人民政府浙政发〔2024〕17号意见](https://zjjcmspublic.oss-cn-hangzhou-zwynet-d01-a.internet.cloud.zj.gov.cn/jcms_files/jcms1/web3241/site/attach/0/75fc778458644eafab722be1603649fc.pdf)：
  浙江工程建设场景下，机器码/文件创建标识码、IP、电子保函账户等线索仍要求结合相关事实证据；旧《浙江省招标投标条例》已废止，不作为当前依据。
- [杭建市〔2020〕190号电子招标投标管理办法](https://zfgb.hangzhou.gov.cn/upload/default/bigfile/2025/06/09/20250609_58d18709078bc6deaff0044a11891e10.pdf)：
  仅作为杭州工程建设电子流程留痕、保密、签名及提交/撤回记录的地方流程参考。

政府采购的[财政部令第87号](https://tfs.mof.gov.cn/caizhengbuling/201707/t20170718_2652603.htm)
和[浙江省财政厅浙财采监〔2025〕2号（杭州财政官方页面）](https://czj.hangzhou.gov.cn/art/2025/5/13/art_1655737_59023282.html)
属于单独适用范围；仅在项目标记为政府采购且招标文件载明时启用，其采购文件执行口径不得直接外推到一般工程建设项目。

当前暂无已确认的“同一项目、多家单位投标”真实测试资料。本仓库不读取或复制用户本机候选资料；
未来格式烟测应先由有权限人员完成脱敏和范围确认，演示/合成资料不得被当作真实业务证据。

## 核心特性（规划）

- 三层数据源架构：全国通用 + 地区插件 + 招标人集团专项，绝不写成某省专用
- `SourceRouter` 路由：注册地 / 发证地 / 项目所在地 / 行业 / 招标人 / 条款 多维决定查什么
- 采集与评判分离：Source Adapter 只回答"官方来源查到了什么"，Rule Engine 回答"是否触发否决条款"
- 严格状态模型：`ERROR / TIMEOUT / BLOCKED / MANUAL / UNKNOWN` 永远不得自动算作 PASS
- 证据链：每条结论可回溯到带 SHA-256 的原始证据（URL / 时间 / 截图 / 关键文字）
- 输出：Excel 核查明细（兼容 Excel/WPS；封面内置公式统计联动 + 状态列条件格式）+ PDF 核查报告，"查询失败"绝不写成"无异常"

## 架构

```text
app/
├─ core/          # models / router / rules / evidence / runner / db
├─ sources/
│  ├─ national/   # gsxt、信用中国、执行信息公开网…（解析器已实现；响应格式为联调前假设，待真实接口复核）
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
