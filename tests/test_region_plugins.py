"""地区插件机制测试（P5）。

完成标准：两个插件（四川+广东）**不动核心代码**即可注册生效——
- 插件=app/sources/regions/<省>/ 包 + 注册表条目（纯数据）；
- 红线锁定：省名不得出现在核心代码（core/main/web server）；
- 路由按注册地/项目地命中，manual 模式查询一律 MANUAL；全部 fixture。
"""
import json
from datetime import date
from pathlib import Path

import pytest

import app
from app.core.models import Company, Project, SourceRef
from app.core.registry import SourceRegistry
from app.core.router import plan_with_exclusions
from app.core.rules import RuleEngine
from app.core.status import Status
from app.sources.national.base import load_adapter, query_source

REGISTRY = SourceRegistry.from_yaml(
    Path(app.__file__).resolve().parent / "config" / "sources_registry.yaml")
PKG = Path(app.__file__).resolve().parent

SC_CONSTRUCTION = REGISTRY.get("sc_construction")
SC_CREDIT = REGISTRY.get("sc_credit")
GD_CONSTRUCTION = REGISTRY.get("gd_construction")
COMPANY = Company(name="测试建筑有限公司", uscc="91510000TEST0000XX",
                  registered_province="四川")
TODAY = date(2026, 9, 5)


# ---------- 插件注册生效（不动核心代码） ----------

def test_plugin_adapters_register_and_load():
    for e in (SC_CONSTRUCTION, SC_CREDIT, GD_CONSTRUCTION):
        assert e.level == "province" and e.enabled
        assert load_adapter(e).source_id == e.id
    assert SC_CONSTRUCTION.adapter.startswith("app.sources.regions.sichuan.")
    assert GD_CONSTRUCTION.adapter.startswith("app.sources.regions.guangdong.")


def test_province_names_never_enter_core_code():
    """红线：四川（及任何省名）逻辑绝不进主程序。

    用 ast 精确扫描：注释与模块/函数 docstring 里的举例不构成逻辑，放行；
    字符串常量（比较值、分支数据）与标识符里出现省名即判定违规。
    """
    import ast

    core_files = [*PKG.glob("core/*.py"), PKG / "main.py", PKG / "web" / "server.py"]
    docstring_nodes: set[int] = set()

    def _collect_docstrings(tree: ast.AST) -> None:
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc is not None and isinstance(node.body[0], ast.Expr) and \
                        isinstance(node.body[0].value, ast.Constant):
                    docstring_nodes.add(id(node.body[0].value))

    for f in core_files:
        text = f.read_text(encoding="utf-8")
        tree = ast.parse(text)
        docstring_nodes.clear()
        _collect_docstrings(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in docstring_nodes:
                    continue
                for province in ("四川", "广东", "成都", "广州"):
                    assert province not in node.value, \
                        f"核心代码 {f.name}:{node.lineno} 字符串常量出现省名「{province}」"


def test_new_plugin_needs_zero_core_changes():
    """机制演示：注册表条目 + 插件包即可被路由/加载/查询（全链路无核心改动）。"""
    route = plan_with_exclusions(
        COMPANY,
        Project(name="四川项目", province="四川", industry="建筑", base_date=TODAY),
        REGISTRY)
    ids = {e.id for e in route.planned}
    assert {"sc_construction", "sc_credit"} <= ids
    route_gd = plan_with_exclusions(
        COMPANY,
        Project(name="广东项目", province="广东", industry="建筑", base_date=TODAY),
        REGISTRY)
    gd_ids = {e.id for e in route_gd.planned}
    # 四川注册企业投广东项目：注册地（四川）与项目地（广东）源都要查——原路由语义
    assert {"gd_construction", "sc_construction", "sc_credit"} <= gd_ids
    # 换非两省注册企业 → 两省插件源都不计划
    other = Company(name="某外省公司", uscc=None, registered_province="河北")
    route_none = plan_with_exclusions(
        other, Project(name="项目", province="浙江", industry="建筑", base_date=TODAY), REGISTRY)
    assert not ({"sc_construction", "sc_credit", "gd_construction"} & {e.id for e in route_none.planned})


# ---------- manual 模式：查询一律 MANUAL 待人工 ----------

@pytest.mark.parametrize("sid", ["sc_construction", "sc_credit", "gd_construction"])
def test_manual_mode_query_is_never_pass(sid):
    out = query_source(REGISTRY.get(sid), COMPANY, get=None)
    assert out.status is Status.MANUAL and not out.findings
    assert "人工" in out.note


# ---------- 抽取契约（fixture，经主体一致性） ----------

def _engine(findings, project):
    return {r.rule_id: r for r in RuleEngine().run_all(findings, project, COMPANY)}


def test_sc_construction_parses_license_and_penalties():
    adapter = load_adapter(SC_CONSTRUCTION)
    body = {"qualifications": [
                {"subject_name": "测试建筑有限公司", "subject_uscc": "91510000TEST0000XX",
                 "cert_name": "施工总承包一级", "status": "正常"}],
            "penalties": [
                {"subject_name": "测试建筑有限公司", "subject_uscc": "91510000TEST0000XX",
                 "penalty_content": "省住建厅限制投标半年", "authority_level": "province",
                 "start_date": "2026-08-01", "end_date": "2027-02-01"}]}
    findings = adapter.parse(json.dumps(body, ensure_ascii=False), company=COMPANY)
    kinds = sorted(f.kind for f in findings)
    assert kinds == ["license_authority_status", "penalty_bid_restriction"]
    assert all(f.attrs["match_result"] == "SAME_SUBJECT" for f in findings)
    proj = Project(name="p", base_date=TODAY, industry="建筑", province="四川")
    rules = _engine(findings, proj)
    assert rules["rule_bid_restriction"].status == Status.FAIL.value


def test_sc_credit_inherits_national_contract():
    findings = load_adapter(SC_CREDIT).parse(
        json.dumps({"result": [
            {"subject_name": "测试建筑有限公司", "subject_uscc": "91510000TEST0000XX",
             "penalty_content": "吊销营业执照", "current": True}]}),
        company=COMPANY)
    assert [f.kind for f in findings] == ["penalty_business"]
    assert findings[0].source_id == "sc_credit"


def test_gd_construction_feeds_background_license_rule():
    findings = load_adapter(GD_CONSTRUCTION).parse(
        json.dumps({"qualifications": [
            {"subject_name": "测试建筑有限公司", "subject_uscc": "91510000TEST0000XX",
             "cert_name": "建筑装饰装修专业承包贰级", "status": "吊销"}]}),
        company=COMPANY)
    proj = Project(name="p", base_date=TODAY, terms=("条款1",))
    rules = _engine(findings, proj)
    assert rules["rule_license_validity"].status == Status.FAIL.value
    assert rules["rule_license_validity"].scope == "background"  # 背景规则不单独否决


def test_wrong_subject_record_never_binds():
    """广东插件收到的同名不同码记录不得算到本企业头上（引擎双拦截）。"""
    findings = load_adapter(GD_CONSTRUCTION).parse(
        json.dumps({"qualifications": [
            {"subject_name": "测试建筑有限公司", "subject_uscc": "91510000BBBB0000BB",
             "cert_name": "装饰资质", "status": "吊销"}]}),
        company=COMPANY)
    proj = Project(name="p", base_date=TODAY)
    rules = _engine(findings, proj)
    assert rules["rule_license_validity"].status == Status.NO_DATA.value
