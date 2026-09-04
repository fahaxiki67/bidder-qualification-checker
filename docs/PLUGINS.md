# 地区插件开发说明（P5）

地区插件是三层数据源架构的第二层（全国 / **地区插件** / 招标人集团专项）。
插件机制的核心承诺：**新增一个省的插件，不改任何核心代码**（core/router/rules/
runner/main 零改动），只交付一个包 + 若干注册表条目。

## 一、机制

```text
app/sources/regions/
└─ <省份拼音>/            # 插件包（如 sichuan/、guangdong/）
   ├─ __init__.py
   ├─ construction.py     # 每个数据源一个模块，暴露 Adapter 类
   └─ credit.py
```

注册 = 在 `app/config/sources_registry.yaml` 追加条目（纯数据）：

```yaml
  - id: sc_construction                       # 全局唯一 source_id
    name: 四川省建筑市场监管公共服务平台
    level: province                           # 地区层固定为 province
    province: 四川                            # 归属省（路由依据）
    official_home: null                       # 人工复核后才能填
    automation_mode: manual                   # 未复核前一律 manual
    evidence_grade: A
    enabled: true
    adapter: app.sources.regions.sichuan.construction   # 指向插件模块
```

生效路径（全部既有机制，无核心分支）：注册表加载 → `load_adapter` 动态导入
→ 路由按 `province` 命中（企业注册地/发证地 或 项目所在地，同省只查一次，
并受行业门控约束）→ 查询状态/SSRF/超时/主体一致性由共享基座承担。

## 二、Adapter 契约

1. 继承共享基座 `app/sources/national/base.py` 的 `NationalAdapter`
   （传输状态映射、SSRF 校验、超时、query_url 未复核→MANUAL 都已内建）；
2. `source_id` 必须与注册表 `id` 完全一致（加载时强校验）；
3. 只实现 `parse(text, *, company)`：把响应解析成客观 `Finding` 列表，
   **不做任何资格判断**（评判归 RuleEngine）；
4. 每条记录必须带主体标识字段 `subject_name` / `subject_uscc`，
   并经 `subject_attrs(company, record)` 生成留痕字段——同名不同码的记录
   会在 adapter/engine 两层被拦截，缺码记录转人工；
5. kind 必须取自既定字典（`penalty_bid_restriction` / `penalty_business` /
   `license_authority_status` / `bankruptcy_status` 等），不得私造 kind 绕开规则。

## 三、automation_mode 口径

| 模式 | 含义 | 查询行为 |
|------|------|----------|
| `manual` | 人工核查：人工查询官方渠道并录入证据 | 恒 MANUAL |
| `manual_intake` | 内部名单人工导入后离线评判 | 恒 MANUAL |
| `auto_fill_manual_verify` | 有验证码，需真机"自动导航+人工验证" | 恒 MANUAL（骨架期） |
| `auto` | 具备自动查询条件（query_url 已人工复核） | 按 URL 执行真实查询 |

URL 纪律：`official_home`/`query_url` 必须先经当前官方门户**人工复核**后回填，
复核前一律 `null` + `manual`——不得按旧资料/搜索摘要写死接口。

## 四、红线（插件同样受约束）

- 省（市）逻辑只存在于插件包内，核心代码由测试
  `tests/test_region_plugins.py::test_province_names_never_enter_core_code`
  用 ast 扫描强制锁定；
- 不破解验证码、不绕 WAF、不代理池、不高频并发；
- fixture/mock 测试先行，真实联调（P3R 式）单列待办；
- 测试与文档不得包含真实企业数据。

## 五、新增一个省插件的最小步骤

1. 建 `app/sources/regions/<省>/__init__.py`；
2. 按契约实现各源模块（可薄封装全国同类 adapter，如广东插件复用 jzsc 契约、
   信用四川复用 creditchina 契约——解析器按真实响应修正前不得声称已支持）；
3. 注册表追加条目（`null` URL + `manual`）；
4. 在 `tests/test_region_plugins.py` 同构补充：加载/路由/manual-MANUAL/parse 契约用例；
5. 更新 `docs/ACCEPTANCE.md` 该源行（adapter/fixture/URL 复核/真实解析逐列如实填写）。

现有插件：四川（sc_construction + sc_credit）、广东（gd_construction，机制验证样例）。
