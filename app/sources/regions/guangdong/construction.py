"""广东省建筑市场监管平台 adapter——第二地区插件（验证插件机制的非川样例）。

复用全国建筑平台（jzsc）的抽取契约：qualifications[] → 资质当前状态
（license_authority_status，供 §6 背景规则）；含进粤登记信息时按资质记录同构处理。
"""
from __future__ import annotations

from ...national.jzsc import Adapter as _JzscAdapter


class Adapter(_JzscAdapter):
    source_id = "gd_construction"
