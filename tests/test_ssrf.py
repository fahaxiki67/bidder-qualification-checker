"""SSRF 防护专项测试（WORKPLAN §三红线）。

adapter 服务端请求仅 http/https，拒绝 localhost、环回、私有与保留地址，
含数字型/十六进制点分/IPv4-mapped IPv6 等绕过形态；真实请求前还须复检 DNS 解析结果。
"""
import pytest

from app.sources.national.base import UnsafeUrlError, assert_safe_url

UNSAFE = [
    "ftp://www.creditchina.gov.cn/",              # 协议不允许
    "file:///etc/passwd",
    "javascript:alert(1)",
    "https:///no-host",                            # 缺主机
    "https://localhost/x",
    "https://db.localhost/x",
    "https://printer.local/x",
    "https://nas.internal/x",
    "http://127.0.0.1/",                           # 环回
    "http://0.0.0.0/",                             # 未指定
    "http://10.1.2.3/",                            # 私有
    "http://172.16.0.9/",
    "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data",     # 链路本地（云元数据）
    "http://[::1]/",
    "http://[fc00::1]/",                           # ULA
    "http://[fe80::1]/",                           # 链路本地
    "http://[::ffff:10.0.0.1]/",                   # IPv4-mapped 私有地址
    "http://2130706433/",                          # 十进制整数形式的 127.0.0.1
    "http://0177.0.0.1/",                          # 八进制点分
    "http://0x7f.0.0.1/",                          # 十六进制点分
    "",                                            # 空 URL
]

SAFE = [
    "https://www.creditchina.gov.cn/",
    "http://jzsc.mohurd.gov.cn/api",
    "https://www.gsxt.gov.cn:443/path?q=1",
    "http://172.32.0.1/",                          # 172.16/12 之外是公网，边界不误伤
    "https://example-comp.com",                    # 含数字的普通域名不受影响
]


@pytest.mark.parametrize("url", UNSAFE)
def test_rejects_unsafe_url(url):
    with pytest.raises(UnsafeUrlError):
        assert_safe_url(url)


@pytest.mark.parametrize("url", SAFE)
def test_allows_safe_url(url):
    assert assert_safe_url(url) == url


def test_rejects_private_resolved_ip():
    """传输层真实请求前复检 DNS：解析结果指向内网必须拦截（防 DNS rebinding）。"""
    with pytest.raises(UnsafeUrlError):
        assert_safe_url("https://www.creditchina.gov.cn/", resolved_ips=["10.0.0.7"])
    assert_safe_url("https://www.creditchina.gov.cn/", resolved_ips=["93.184.216.34"])  # 公网放行
