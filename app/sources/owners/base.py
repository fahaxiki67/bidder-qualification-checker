"""集团专项 adapter 基座：与全国源共用传输/SSRF/主体一致性/状态映射基类。

分层（任务书）体现在注册表 level=owner 与路由，而不在基类重复实现；
未来集团源若有独立传输需求，在此扩展，不得改动核心。
"""
from ...sources.national.base import (  # noqa: F401
    AdapterOutcome,
    FetchResult,
    NationalAdapter,
    TransportError,
    TransportStatus,
    TransportTimeout,
    UnsafeUrlError,
    fetch,
    parse_date,
    subject_attrs,
)
