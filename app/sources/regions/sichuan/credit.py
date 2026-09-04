"""信用中国（四川）adapter——四川插件第二源。

复用全国信用中国的抽取契约与解析实现（省级站点字段假设一致，联调后按实测修正）；
主体一致性/状态映射由共享基座承担。插件机制演示：薄封装 + 独立注册即可生效。
"""
from __future__ import annotations

from ...national.creditchina import Adapter as _CreditChinaAdapter


class Adapter(_CreditChinaAdapter):
    source_id = "sc_credit"
