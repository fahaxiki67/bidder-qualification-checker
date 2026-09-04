from datetime import date

from app.core.matching import same_company
from app.core.models import Company, Project, years_ago


def test_years_ago_normal():
    assert years_ago(date(2026, 9, 4), 3) == date(2023, 9, 4)


def test_years_ago_leap_day():
    assert years_ago(date(2024, 2, 29), 1) == date(2023, 2, 28)


def test_project_window_start():
    p = Project(name="X", base_date=date(2026, 9, 4), years_back=3)
    assert p.window_start == date(2023, 9, 4)


def test_same_uscc_same_company_despite_name_diff():
    a = Company(name="甲公司", uscc="91510112MACD5CDJ9F")
    b = Company(name="乙公司", uscc="91510112MACD5CDJ9F")
    assert same_company(a, b)


def test_same_name_different_uscc_not_same():
    a = Company(name="四川众鑫恒辰建筑工程有限公司", uscc="91510112MACD5CDJ9F")
    b = Company(name="四川众鑫恒辰建筑工程有限公司", uscc="91510112AAAAAAAAAA")
    assert not same_company(a, b)


def test_one_side_uscc_missing_not_same():
    a = Company(name="四川众鑫恒辰建筑工程有限公司", uscc="91510112MACD5CDJ9F")
    b = Company(name="四川众鑫恒辰建筑工程有限公司")
    assert not same_company(a, b)


def test_name_only_normalized_match():
    a = Company(name="四川众鑫恒辰建筑工程有限公司")
    b = Company(name="四川众鑫恒辰 建筑工程有限公司")  # 内含空格
    assert same_company(a, b)
    assert not same_company(a, Company(name="另一家公司"))
