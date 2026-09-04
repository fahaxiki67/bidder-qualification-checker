"""全国源 adapter 基类：SSRF 防护、传输层状态映射、查询编排。

纪律（WORKPLAN §三/§四）：
- adapter 只采集客观事实（Finding），评判归 RuleEngine；
- 查询 URL 只认注册表：query_url 未人工复核就为空 → 一律 MANUAL（不得写死未复核接口）；
- SSRF：仅 http/https，拒绝 localhost/环回/私有/保留地址，真实请求前复检 DNS 解析结果；
- 失败状态（TIMEOUT/ERROR/BLOCKED/MANUAL）绝不归约为 PASS，解析失败也算查询失败。

各解析器当前基于**联调前假设的响应格式**（合成 fixture）；测试证明的是状态映射与
抽取管线，不代表真实站点格式，真实联调后必须修正解析器并登记 docs/ACCEPTANCE.md。
"""
from __future__ import annotations

import importlib
import ipaddress
import re
import socket
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urlparse

from ...core.models import Company, Finding, SourceRef
from ...core.status import Status

ALLOWED_SCHEMES = ("http", "https")
#: 常见风控/限制状态码：归为 BLOCKED（访问被限制），其余非 2xx 归为 ERROR
_RISK_HTTP_CODES = {403, 405, 418, 429, 503}


class UnsafeUrlError(ValueError):
    """SSRF 校验拒绝的 URL。"""


def _is_public_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    mapped = getattr(addr, "ipv4_mapped", None)
    if mapped is not None:
        addr = mapped
    return addr.is_global and not addr.is_unspecified


def _looks_like_ip_literal(host: str) -> bool:
    """纯数字点分 / 十六进制点分等歧义形态（0177.0.0.1、0x7f.0.0.1）按 IP 字面量处理。"""
    if re.fullmatch(r"[0-9.]+", host):
        return True
    if "." in host and any(c.isdigit() for c in host) and re.fullmatch(r"(?:0[xX])?[0-9a-fA-F.]+", host):
        return True
    return False


def assert_safe_url(url: str, *, resolved_ips=None, allowed_schemes=ALLOWED_SCHEMES) -> str:
    """校验服务端将请求的 URL，不安全抛 UnsafeUrlError，安全则原样返回。

    resolved_ips：传输层真实请求前把 DNS 解析结果传入复检（防 DNS rebinding）。
    """
    if not url or not isinstance(url, str):
        raise UnsafeUrlError("URL 为空")
    parsed = urlparse(url)
    if parsed.scheme not in allowed_schemes:
        raise UnsafeUrlError(f"协议不允许：{parsed.scheme or '（无）'}")
    host = (parsed.hostname or "").rstrip(".")
    if not host:
        raise UnsafeUrlError("缺少主机名")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise UnsafeUrlError(f"保留主机名：{host}")
    try:
        addr: ipaddress._BaseAddress = ipaddress.ip_address(host)  # 含 IPv6/整数形态
    except ValueError:
        addr = None
    if addr is not None:
        if not _is_public_ip(addr):
            raise UnsafeUrlError(f"非公网地址：{host}")
    elif _looks_like_ip_literal(host):
        raise UnsafeUrlError(f"无法安全判定的数字型主机：{host}")
    if resolved_ips:
        for s in resolved_ips:
            if not _is_public_ip(ipaddress.ip_address(s)):
                raise UnsafeUrlError(f"DNS 解析指向非公网地址：{s}")
    return url


class TransportError(Exception):
    """传输层网络错误（连接失败等）。"""


class TransportTimeout(TransportError):
    """传输层超时。"""


class TransportStatus(TransportError):
    """传输层拿到非 2xx HTTP 状态码。"""

    def __init__(self, status_code: int, note: str = ""):
        super().__init__(note or f"HTTP {status_code}")
        self.status_code = status_code


@dataclass
class FetchResult:
    """单次抓取的传输结果：status 只表达“查询本身是否成功”。"""

    status: Status
    http_status: int | None
    text: str
    url: str
    note: str = ""


def _translate_httpx_error(e: Exception) -> TransportError:
    """httpx 异常 → 传输层状态异常（P0.5 §四）。

    - TimeoutException 家族（连接/读/写/池超时）→ TransportTimeout；
    - 其余 RequestError（DNS/连接失败等）→ TransportError；
    - 非网络异常（编程错误）原样抛出，不得吞掉。
    """
    import httpx

    if isinstance(e, httpx.TimeoutException):
        return TransportTimeout(str(e) or "请求超时")
    if isinstance(e, httpx.RequestError):
        return TransportError(f"{e.__class__.__name__}: {e}")
    raise e


def _default_resolver(host: str) -> list[str]:
    """真实 DNS 解析（传输层复检用）。测试经 resolver 参数注入假解析。"""
    return sorted({ai[4][0] for ai in socket.getaddrinfo(host, None)})


def httpx_get(url: str, timeout: float = 15.0, *, client_factory=None, resolver=None) -> tuple[int, str]:
    """默认传输层（仅真实联调使用）：政府网站直连不走代理；请求前复检 DNS。

    client_factory/resolver 供测试注入（httpx.MockTransport / 假 DNS），
    覆盖的是与生产完全相同的默认调用链，而非绕过它。
    httpx 网络异常在此统一翻译为 TransportError 家族，fetch() 才能映射状态。
    """
    import httpx

    host = (urlparse(url).hostname or "").rstrip(".")
    resolve = resolver or _default_resolver
    try:
        addrs = resolve(host)
    except OSError as e:
        raise TransportError(f"DNS 解析失败：{host}: {e}") from e
    assert_safe_url(url, resolved_ips=addrs)
    factory = client_factory or (lambda: httpx.Client(timeout=timeout, trust_env=False))
    try:
        with factory() as cli:
            resp = cli.get(url)
            return resp.status_code, resp.text
    except TransportError:
        raise
    except Exception as e:
        raise _translate_httpx_error(e) from e


def fetch(url: str, get=None, timeout: float = 15.0) -> FetchResult:
    """抓取并把一切异常归约为状态：BLOCKED/TIMEOUT/ERROR/PASS，绝不抛出。"""
    get = get or httpx_get
    try:
        assert_safe_url(url)
    except UnsafeUrlError as e:
        return FetchResult(Status.BLOCKED, None, "", url, note=f"SSRF 校验拦截：{e}")
    try:
        code, text = get(url, timeout)
    except UnsafeUrlError as e:
        # DNS 复检/重定向目标复检（httpx_get 内部）拦下的不安全地址：SSRF 防护拒绝
        return FetchResult(Status.BLOCKED, None, "", url, note=f"SSRF 复检拦截：{e}")
    except TransportTimeout:
        return FetchResult(Status.TIMEOUT, None, "", url, note="请求超时")
    except TransportStatus as e:
        if e.status_code in _RISK_HTTP_CODES:
            return FetchResult(Status.BLOCKED, e.status_code, "", url,
                               note=f"访问被限制（HTTP {e.status_code}）")
        return FetchResult(Status.ERROR, e.status_code, "", url, note=f"HTTP 错误 {e.status_code}")
    except TransportError as e:
        return FetchResult(Status.ERROR, None, "", url, note=f"网络错误：{e}")
    if 200 <= code < 300:
        return FetchResult(Status.PASS, code, text, url)
    if code in _RISK_HTTP_CODES:
        # 默认路径不抛 TransportStatus，风控状态码在此同样映射 BLOCKED（P0.5 §四）
        return FetchResult(Status.BLOCKED, code, "", url, note=f"访问被限制（HTTP {code}）")
    return FetchResult(Status.ERROR, code, "", url, note=f"HTTP 错误 {code}")


def parse_date(s) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(str(s))
    except ValueError:
        return None


@dataclass
class AdapterOutcome:
    """adapter 对单源的核查结果：查询状态 + 采集到的客观事实。"""

    source_id: str
    status: Status
    findings: list = field(default_factory=list)
    query_url: str | None = None
    note: str = ""


class NationalAdapter:
    """全国源 adapter 基类。子类实现 parse()，返回客观 Finding 列表。"""

    source_id = ""

    def query(self, company: Company, source: SourceRef, *, get=None, timeout: float = 15.0) -> AdapterOutcome:
        url = source.query_url
        if not url:
            return AdapterOutcome(
                self.source_id, Status.MANUAL, [], source.official_home,
                note="查询接口未人工复核（红线：不得写死未复核接口），转人工核查",
            )
        if source.automation_mode == "auto_fill_manual_verify":
            return AdapterOutcome(
                self.source_id, Status.MANUAL, [], url,
                note="该源需验证码/人工介入（auto_fill_manual_verify），骨架期一律转人工",
            )
        fr = fetch(url, get=get, timeout=timeout)
        if fr.status is not Status.PASS:
            return AdapterOutcome(self.source_id, fr.status, [], fr.url, note=fr.note)
        try:
            findings = self.parse(fr.text, company=company)
        except Exception as e:  # 解析失败=查询失败，绝不伪造成功
            return AdapterOutcome(self.source_id, Status.ERROR, [], fr.url,
                                  note=f"响应解析失败：{e.__class__.__name__}: {e}")
        if findings:
            return AdapterOutcome(self.source_id, Status.PASS, findings, fr.url, note="查询成功")
        return AdapterOutcome(self.source_id, Status.NO_DATA, [], fr.url, note="查询成功，未检索到记录")

    def parse(self, text: str, *, company: Company) -> list[Finding]:
        raise NotImplementedError(f"{self.__class__.__name__} 尚未实现解析（P3 骨架）")


def load_adapter(source: SourceRef) -> NationalAdapter:
    """按注册表 adapter 路径加载并校验 source_id 一致。"""
    path = source.adapter or ""
    if not path.startswith("app.sources."):
        raise ValueError(f"adapter 路径非法：{path!r}")
    mod = importlib.import_module(path)
    cls = getattr(mod, "Adapter", None)
    if cls is None:
        raise ValueError(f"{path} 未暴露 Adapter 类")
    inst: NationalAdapter = cls()
    if inst.source_id != source.id:
        raise ValueError(f"adapter source_id={inst.source_id!r} 与注册表 {source.id!r} 不一致")
    return inst


def query_source(source: SourceRef, company: Company, *, get=None, timeout: float = 15.0) -> AdapterOutcome:
    """按注册表条目执行一次单源查询（runner 真实链路的执行单元）。"""
    return load_adapter(source).query(company, source, get=get, timeout=timeout)
