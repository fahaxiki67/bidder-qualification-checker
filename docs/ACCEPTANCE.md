# 开发验收表

> 任务书 §22：无法可靠自动查询的平台必须如实登记，不得伪造成功。
> **fixture/mock 测试通过 ≠ 官方平台已支持。** 下表逐源区分 adapter 存在性、
> mock 验证、URL 人工复核、真实解析验证与当前自动化能力。

## 平台支持状态（P3 骨架完成后逐项核实，2026-09-04）

| 平台 | 级别 | adapter 骨架 | fixture/mock 测试 | 官方 URL 人工复核 | 真实解析验证 | 需验证码/人工 | 当前自动化能力 |
|------|------|:---:|:---:|:---:|:---:|:---:|------|
| 国家企业信用信息公示系统 gsxt.gov.cn | 全国 | ✓ | ✓ | ✗（query_url 留空） | ✗ | **是**（图片验证码，恒 MANUAL） | 无真实查询；查询返回 MANUAL |
| 信用中国 creditchina.gov.cn | 全国 | ✓ | ✓ | ✗（query_url 留空） | ✗ | 待实测 | 无真实查询；查询返回 MANUAL |
| 中国执行信息公开网 zxgk.court.gov.cn | 全国 | ✓ | ✓ | ✗（query_url 留空） | ✗ | **是**（验证码） | 无真实查询；查询返回 MANUAL |
| 应急管理部安全生产信用 mem.gov.cn | 全国 | ✓ | ✓ | ✗（query_url 留空） | ✗ | 待实测 | 无真实查询；查询返回 MANUAL |
| 全国建筑市场监管平台 jzsc.mohurd.gov.cn | 全国 | ✓ | ✓ | ✗（query_url 留空） | ✗ | 待实测 | 无真实查询；查询返回 MANUAL |
| 全国破产重整案件信息网 pcczdc.court.gov.cn | 全国 | ✓ | ✓ | ✗（query_url 留空） | ✗ | 待实测 | 无真实查询；查询返回 MANUAL |
| 中国电建 ec.powerchina.cn | 集团 | ✗（P4） | ✗ | ✗ | ✗ | 待定 | 未开发；内部名单无法公开验证时必须返回 MANUAL |
| 四川地区插件 | 地区 | ✗（P5） | ✗ | ✗ | ✗ | 待定 | 未开发 |
| 第二地区插件（非川） | 地区 | ✗（P5） | ✗ | ✗ | ✗ | 待定 | 未开发，验证插件机制 |

说明：

- **adapter 骨架**：`app/sources/national/` 下 6 个 adapter 模块已注册可加载，含 SSRF
  防护与传输层状态映射（超时→TIMEOUT、风控→BLOCKED、失败→ERROR，绝不 PASS）。
- **fixture/mock 测试**：离线 fixture 验证抽取逻辑与规则联动，104+ 项测试中的部分，
  全部通过；这只证明"给定响应格式时解析正确"，**不证明官方平台可自动查询**。
- **官方 URL 人工复核**：全部未做。`app/config/sources_registry.yaml` 中各源
  `query_url` 留空、`last_verified` 为空——按红线，未复核 URL 一律不写死、
  查询直接返回 MANUAL。
- **真实解析验证**：全部未做，需白天人工配合真机联调（P3R）。
- **当前自动化能力**：mock 演示链路（`nightly_mock_only: true`）可端到端演示
  9 态状态机与规则评判；真实链路 `run_check(real_sources=True)` 已接通注册表，
  但因 URL 未复核，各源实际返回 MANUAL。

## 待办：P3R 真实联调（需白天人工配合）

1. 逐源人工复核官方门户查询入口 → 回填 `query_url`/`last_verified`。
2. 按真实响应格式修正各解析器，用真实样本回放验证。
3. zxgk/gsxt 验证码源："自动导航+人工验证+继续解析"真机联调。
4. Web 层真实模式入口（受 nightly_mock_only 门控）。

## 交付物核对（任务书 §22 最终提交清单）

- [x] 完整源码（随阶段推进持续更新）
- [ ] Windows 安装包（P8）
- [ ] macOS 构建包（P9）
- [x] README
- [x] 测试结果（每轮 PROGRESS.md 记录；当前 107 项全绿）
- [ ] 已支持数据源清单（真实联调后才有"已支持"）
- [x] 未支持数据源清单（即上表）
- [ ] 地区插件开发说明（P5）
- [x] GitHub Release 配置（打 tag 自动出 Release）
- [x] 开发验收表（本文件）
