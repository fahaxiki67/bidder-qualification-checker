from datetime import date

from app.core.models import Company, Project, SourceRef
from app.core.registry import SourceRegistry
from app.core.router import plan

NATIONAL = [
    SourceRef(id="creditchina", name="信用中国", level="national"),
    SourceRef(id="zxgk", name="执行信息公开网", level="national"),
]
REGIONS = [
    SourceRef(id="sc_construction", name="四川建筑市场监管", level="province", province="四川"),
    SourceRef(id="gd_construction", name="广东建筑市场监管", level="province", province="广东"),
]
OWNER = [
    SourceRef(id="powerchina_ban", name="电建禁入名单", level="owner", owner_group="powerchina"),
    SourceRef(id="other_ban", name="别家集团禁入", level="owner", owner_group="other", enabled=False),
]


def test_sichuan_company_guangdong_project_powerchina_owner():
    """任务书 §3 场景：四川企业投广东的中国电建项目。"""
    registry = SourceRegistry(NATIONAL + REGIONS + OWNER)
    company = Company(name="四川某建筑公司", registered_province="四川")
    project = Project(name="广东某电建项目", province="广东", owner_group="powerchina")
    ids = [e.id for e in plan(company, project, registry)]
    assert "creditchina" in ids and "zxgk" in ids          # 全国共性
    assert "sc_construction" in ids                        # 发证地
    assert "gd_construction" in ids                        # 项目所在地
    assert "powerchina_ban" in ids                         # 招标人专项
    assert "other_ban" not in ids                          # 停用的源不查


def test_same_province_only_once():
    registry = SourceRegistry(NATIONAL + REGIONS)
    company = Company(name="广东某公司", registered_province="广东")
    project = Project(name="广东项目", province="广东")
    ids = [e.id for e in plan(company, project, registry)]
    assert ids.count("gd_construction") == 1


def test_no_region_no_province_sources():
    registry = SourceRegistry(NATIONAL + REGIONS)
    ids = [e.id for e in plan(Company(name="某公司"), Project(name="某项目"), registry)]
    assert set(ids) == {"creditchina", "zxgk"}


def test_owner_mismatch_excluded():
    registry = SourceRegistry(OWNER)
    ids = [e.id for e in plan(
        Company(name="某公司"),
        Project(name="非电建项目", owner_group="sinohydro"), registry)]
    assert ids == []
