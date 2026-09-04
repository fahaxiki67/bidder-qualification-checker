"""地区插件层（第二层）：省级数据源插件。

插件机制（P5）：插件=本目录下的包 + 注册表条目（app/config/sources_registry.yaml），
注册生效**不需要改动核心代码**（core/router/rules/runner/main 零改动）。
红线：四川（及任何省）逻辑绝不进主程序；adapter 只采集，评判归 RuleEngine。
"""
