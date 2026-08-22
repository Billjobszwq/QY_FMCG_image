"""EndpointPolicy：URL/SSRF/DNS/redirect 统一策略（M2/G1，02 §6）。

纪律：
- 保存（M4 service）、连接测试（M4 probe）与真实调用（M3 adapter）三处
  必须复用本策略，不得各自实现 URL 检查。
- scheme 只允许 https；仅 location=local 允许 http 且必须回环。
- 拒绝 userinfo、fragment、空 host、超长 URL、非标准 scheme。
- api 模式拒绝 loopback、RFC1918/ULA 私网、link-local、multicast、
  reserved、unspecified 与云 metadata（169.254.169.254 属 link-local）。
- DNS 解析后复核全部 IP（任一不合规即整体拒绝，防 DNS rebinding）；
  返回 pinned IPs，调用方必须向 pinned IP 发起连接。
- redirect 目标必须重新执行同一策略。
- TLS 严格验证；自定义 CA 只能由部署管理员配置（不在本模块放开）。
"""
from __future__ import annotations

import socket
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv6Address, ip_address
from typing import Callable
from urllib.parse import urlsplit

from src.platform.models.contracts import (
    MODEL_ENDPOINT_BLOCKED,
    ModelManagementError,
)

MAX_URL_LENGTH = 2048
_ALLOWED_SCHEMES = ("http", "https")
_DEFAULT_PORTS = {"http": 80, "https": 443}

Resolver = Callable[[str, int], list[str]]


class EndpointPolicyError(ModelManagementError):
    code = MODEL_ENDPOINT_BLOCKED
    http_status = 422


def _default_resolver(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    return sorted({info[4][0] for info in infos})


def _ip_allowed(ip_str: str, location: str) -> bool:
    ip: IPv4Address | IPv6Address = ip_address(ip_str)
    if location == "local":
        # 本地 Provider 只允许回环（安装策略批准的 RFC1918 网段需要
        # 部署管理员显式配置，V1 不默认放开）
        return ip.is_loopback
    # api：必须是全局可路由公网地址
    if (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_multicast or ip.is_reserved or ip.is_unspecified):
        return False
    return ip.is_global


@dataclass(frozen=True)
class Endpoint:
    """通过策略校验后的连接端点。连接必须使用 pinned_ips。"""

    url: str
    scheme: str
    host: str
    port: int
    path: str
    query: str
    location: str
    pinned_ips: tuple[str, ...]

    def connect_targets(self) -> tuple[tuple[str, int], ...]:
        """仅供调用方连接已复核的 IP（防 DNS rebinding）。"""
        return tuple((ip, self.port) for ip in self.pinned_ips)

    def origin_host_header(self) -> str:
        return self.host


class EndpointPolicy:
    def __init__(self, *, resolver: Resolver | None = None,
                 max_url_length: int = MAX_URL_LENGTH) -> None:
        self._resolver = resolver or _default_resolver
        self._max_url_length = max_url_length

    def validate(self, url: str, *, location: str) -> Endpoint:
        return self._check(url, location=location)

    def validate_redirect(self, url: str, *, location: str) -> Endpoint:
        """重定向目标必须重新执行同一策略（02 §6）。"""
        return self._check(url, location=location)

    def _check(self, url: str, *, location: str) -> Endpoint:
        if location not in ("local", "api"):
            raise EndpointPolicyError(f"未知 location: {location!r}")
        if not isinstance(url, str) or not url:
            raise EndpointPolicyError("URL 为空")
        if len(url) > self._max_url_length:
            raise EndpointPolicyError("URL 超过长度上限")

        try:
            parts = urlsplit(url)
        except ValueError as e:
            raise EndpointPolicyError("URL 无法解析") from e

        scheme = parts.scheme.lower()
        if scheme not in _ALLOWED_SCHEMES:
            raise EndpointPolicyError(
                f"禁止的 scheme: {scheme or '(空)'}")
        if location == "api" and scheme != "https":
            raise EndpointPolicyError("api 模式仅允许 https")
        if parts.username is not None or parts.password is not None:
            raise EndpointPolicyError("URL 不得包含 userinfo")
        if parts.fragment:
            raise EndpointPolicyError("URL 不得包含 fragment")
        host = parts.hostname
        if not host:
            raise EndpointPolicyError("URL 缺少 host")
        try:
            port = parts.port or _DEFAULT_PORTS[scheme]
        except ValueError as e:
            raise EndpointPolicyError("URL 端口非法") from e
        if not (0 < port <= 65535):
            raise EndpointPolicyError("URL 端口越界")

        # IP 字面量直接复核；主机名解析后复核全部 IP（任一不合规整体拒绝）
        pinned: tuple[str, ...]
        try:
            ip_address(host)
            candidates = [host]
        except ValueError:
            try:
                candidates = list(self._resolver(host, port))
            except EndpointPolicyError:
                raise
            except Exception as e:
                raise EndpointPolicyError("DNS 解析失败：拒绝连接") from e
            if not candidates:
                raise EndpointPolicyError("DNS 解析为空：拒绝连接")
        for ip_str in candidates:
            try:
                ok = _ip_allowed(ip_str, location)
            except ValueError:
                ok = False
            if not ok:
                raise EndpointPolicyError(
                    f"Endpoint 策略拒绝该地址（location={location}）")
        pinned = tuple(candidates)

        return Endpoint(
            url=url, scheme=scheme, host=host, port=port,
            path=parts.path, query=parts.query, location=location,
            pinned_ips=pinned)
