"""打包/安装回归测试：资源随包分发、版本单点来源（P0 任务书 §四/§六）。

要求以 pip 安装（editable 或 wheel）后的环境运行 pytest；
未安装时 importlib.metadata 查询会失败并给出修复指引，这是有意的硬约束——
P0 之后"项目必须可安装"是基线，不再支持绕过安装直接从仓库根跑测试。
"""
import importlib.metadata
from pathlib import Path

import app

APP_ROOT = Path(app.__file__).resolve().parent


def test_templates_shipped():
    d = APP_ROOT / "web" / "templates"
    for name in ("base.html", "index.html", "result.html"):
        assert (d / name).is_file(), f"模板未随包分发: {name}"


def test_config_shipped():
    d = APP_ROOT / "config"
    for name in ("app.yaml", "rules.yaml", "sources_registry.yaml"):
        assert (d / name).is_file(), f"配置未随包分发: {name}"


def test_readme_version_not_stale():
    """README 状态行的版本号必须与 app.__version__ 一致（P0 任务书 §六反漂移）。

    0.12.0→0.14.0 期间 README 漂移两个版本未被发现——本轮测试锁死。
    """
    import re

    readme = (Path(app.__file__).resolve().parents[1] / "README.md").read_text(
        encoding="utf-8")
    m = re.search(r"状态：v([0-9]+\.[0-9]+\.[0-9]+)", readme)
    assert m, "README 缺少'状态：vX.Y.Z'版本行"
    assert m.group(1) == app.__version__, (
        f"README 版本 {m.group(1)} 落后/超前于 app.__version__ {app.__version__}；"
        "更新版本号时必须同步 README 状态行")


def test_metadata_version_matches_single_source():
    """pyproject version 必须与 app.__version__ 同源一致，杜绝 0.1.0/0.3.0 漂移。"""
    meta = importlib.metadata.version("bidder-qualification-checker")
    assert meta == app.__version__, (
        f"版本漂移：包元数据 {meta} != app.__version__ {app.__version__}；"
        "两处必须同时改为同一版本号")
