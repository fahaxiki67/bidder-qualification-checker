"""SSRF 重定向防护测试（P0.5 §九）。

公网 URL 不得借 HTTP Redirect 跳入环回/私网/IPv6 环回；
每一跳目标重新执行完整 SSRF 校验 + DNS 复检；正常公网跳转不受影响。
全部经 httpx.MockTransport + 注入式假 DNS，不访问真实网络。
"""
from functools import partial

import httpx
import pytest

from app.core.status import Status
from app.sources.national.base import fetch, httpx_get

ENTRY = "https://portal.example.cn/start"
_PUBLIC_IP = "93.184.216.34"


def _get(called, handler, url, timeout=15.0):
    def tracking_handler(request):
        called.append(str(request.url))
        return handler(request)
    return httpx_get(
        url, timeout,
        client_factory=lambda: httpx.Client(
            transport=httpx.MockTransport(tracking_handler), trust_env=False),
        resolver=_public_resolver,
    )


def _public_resolver(host):
    return [_PUBLIC_IP]  # 所有主机名都解析到公网 IP（跳变防护由 URL 校验兜住）


def _redirect(target, status=302):
    def handler(request):
        return httpx.Response(status, headers={"Location": target})
    return handler


class TestRedirectBlocked:
    def test_public_to_loopback_ipv4(self):
        called: list[str] = []
        fr = fetch(ENTRY, get=partial(_get, called, _redirect("http://127.0.0.1/x")))
        assert fr.status is Status.BLOCKED
        assert "SSRF" in fr.note
        assert called == [ENTRY]  # 内网目标从未被真正请求

    def test_public_to_private_ipv4(self):
        called: list[str] = []
        fr = fetch(ENTRY, get=partial(_get, called, _redirect("https://192.168.1.10/admin")))
        assert fr.status is Status.BLOCKED
        assert all("192.168." not in u for u in called)

    def test_public_to_ipv6_loopback(self):
        called: list[str] = []
        fr = fetch(ENTRY, get=partial(_get, called, _redirect("http://[::1]:8080/")))
        assert fr.status is Status.BLOCKED
        assert len(called) == 1

    def test_public_to_decimal_ip_literal(self):
        """歧义 IP 字面量（2130706433 = 127.0.0.1）同样拦截。"""
        called: list[str] = []
        fr = fetch(ENTRY, get=partial(_get, called, _redirect("http://2130706433/")))
        assert fr.status is Status.BLOCKED

    def test_dns_recheck_on_redirect_target(self):
        """第二跳主机名看似公网但 DNS 复检返回私网地址 → 拦截（防 rebinding）。"""
        called: list[str] = []

        def mixed_resolver(host):
            return ["10.9.9.9"] if host == "cdn.example.cn" else [_PUBLIC_IP]

        def get(url, timeout=15.0):
            def th(request):
                called.append(str(request.url))
                return handler(request)
            return httpx_get(
                url, timeout,
                client_factory=lambda: httpx.Client(
                    transport=httpx.MockTransport(th), trust_env=False),
                resolver=mixed_resolver)

        def handler(request):
            return httpx.Response(302, headers={"Location": "https://cdn.example.cn/file"})
        fr = fetch(ENTRY, get=get)
        assert fr.status is Status.BLOCKED
        assert "非公网" in fr.note or "SSRF" in fr.note


class TestRedirectAllowed:
    def test_normal_public_https_redirect_followed(self):
        called: list[str] = []

        def handler(request):
            if request.url.path == "/start":
                return httpx.Response(302, headers={"Location": "https://portal.example.cn/final"})
            return httpx.Response(200, text="final-body")

        fr = fetch(ENTRY, get=partial(_get, called, handler))
        assert fr.status is Status.PASS
        assert fr.text == "final-body"
        assert called == [ENTRY, "https://portal.example.cn/final"]

    def test_relative_location_resolved_and_validated(self):
        called: list[str] = []

        def handler(request):
            if request.url.path == "/start":
                return httpx.Response(302, headers={"Location": "/relative/path"})
            return httpx.Response(200, text="relative-body")

        fr = fetch(ENTRY, get=partial(_get, called, handler))
        assert fr.status is Status.PASS
        assert fr.text == "relative-body"
        assert called[-1] == "https://portal.example.cn/relative/path"

    def test_redirect_chain_within_limit(self):
        def handler(request):
            tail = request.url.path.rsplit("/", 1)[-1]
            n = int(tail) if tail.isdigit() else 0
            if n < 3:
                return httpx.Response(302, headers={"Location": f"/hop/{n + 1}"})
            return httpx.Response(200, text=f"hop-{n}")

        fr = fetch(ENTRY, get=partial(_get, [], handler))
        assert fr.status is Status.PASS and fr.text == "hop-3"

    def test_redirect_loop_over_limit_is_error_not_crash(self):
        def handler(request):
            return httpx.Response(302, headers={"Location": "/loop"})
        fr = fetch(ENTRY, get=partial(_get, [], handler))
        assert fr.status is Status.ERROR  # 超限=传输错误，fetch 归约，绝不抛出


def test_max_redirects_constant_not_weakened():
    from app.sources.national import base
    assert 1 <= base._MAX_REDIRECTS <= 10  # 防护常量存在且未放宽到失控
