"""实景照片 OSS 直链构造。

.xlsx 里的 URL 是 .aspx 详情页（HTML 查看器），其 <img src> 才是真实图地址，规律已核实为
公开可读、无需签名：{oss_base}/{oss_prefix}{filename}。文件名含中文/全角符号，需 percent-encode。"""
from __future__ import annotations

from urllib.parse import quote

from .config import get_settings


def oss_url(filename: str) -> str:
    s = get_settings()
    return f"{s.oss_base.rstrip('/')}/{s.oss_prefix.lstrip('/')}{quote(filename, safe='/')}"


def aspx_url(filename: str) -> str:
    """详情页地址，仅用于直链不可用时回退解析 <img src>。"""
    return f"http://sys-new.spar-china.com/tally/sys_ProbeDetail_ImgInfo.aspx?imgUrl={quote(filename, safe='/')}"
