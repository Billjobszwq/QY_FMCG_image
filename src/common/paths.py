"""不变护栏：用户原始资产只读，派生结果只写派生目录。写原始资产直接抛错。"""
from pathlib import Path
from .config import PROJECT_ROOT, get_settings

DERIVED_ROOTS = [PROJECT_ROOT / ".kb", PROJECT_ROOT / ".labels", PROJECT_ROOT / ".datasets", PROJECT_ROOT / ".models", PROJECT_ROOT / ".field", PROJECT_ROOT / ".warehouse"]

def readonly_sources():
    s = get_settings()
    return [PROJECT_ROOT / "搭建初期P1", Path(s.field_xlsx), PROJECT_ROOT / ".field" / "blobs", PROJECT_ROOT / ".field" / "manifest.json"]

def assert_writable(path):
    p = Path(path).resolve()
    for ro in readonly_sources():
        rp = Path(ro).resolve()
        if p == rp or rp in p.parents:
            raise PermissionError(f"REFUSE WRITE into read-only source: {p} (protected {rp})")
    return p

def safe_write_text(path, text):
    p = assert_writable(path); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text, encoding="utf-8"); return p

def safe_write_bytes(path, data):
    p = assert_writable(path); p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data); return p

def safe_open_write(path, mode="w"):
    p = assert_writable(path); p.parent.mkdir(parents=True, exist_ok=True); return open(p, mode, encoding=None if "b" in mode else "utf-8")
