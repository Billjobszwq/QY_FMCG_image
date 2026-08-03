"""数据集内容哈希回归测试（RA-013 复核修订）：label 变更必须改变哈希。"""
import pytest

from src.training.train_v1 import _content_manifest_hash


def _mk_ds(tmp_path):
    for split in ("train", "val"):
        (tmp_path / "images" / split).mkdir(parents=True)
        (tmp_path / "labels" / split).mkdir(parents=True)
        (tmp_path / "images" / split / "a.jpg").write_bytes(b"img-" + split.encode())
        (tmp_path / "labels" / split / "a.txt").write_text(f"0 0.5 0.5 0.1 0.1\n")
    return tmp_path


def test_hash_stable_on_same_content(tmp_path):
    _mk_ds(tmp_path)
    h1, n1 = _content_manifest_hash(tmp_path, "images/train", "images/val")
    h2, n2 = _content_manifest_hash(tmp_path, "images/train", "images/val")
    assert h1 == h2 and n1 == n2 == 4  # 2 图 + 2 标签


def test_label_change_changes_hash(tmp_path):
    """复核核心：图片不变、只改 label，content_hash 必须变化。"""
    _mk_ds(tmp_path)
    h1, _ = _content_manifest_hash(tmp_path, "images/train", "images/val")
    (tmp_path / "labels" / "train" / "a.txt").write_text("1 0.5 0.5 0.1 0.1\n")
    h2, _ = _content_manifest_hash(tmp_path, "images/train", "images/val")
    assert h1 != h2


def test_image_change_changes_hash(tmp_path):
    _mk_ds(tmp_path)
    h1, _ = _content_manifest_hash(tmp_path, "images/train", "images/val")
    (tmp_path / "images" / "val" / "a.jpg").write_bytes(b"img-VAL-TAMPERED")
    h2, _ = _content_manifest_hash(tmp_path, "images/train", "images/val")
    assert h1 != h2


def test_file_move_between_splits_changes_hash(tmp_path):
    """相对路径参与哈希：同名文件换目录也会改变哈希。"""
    _mk_ds(tmp_path)
    h1, _ = _content_manifest_hash(tmp_path, "images/train", "images/val")
    src = tmp_path / "images" / "train" / "a.jpg"
    src.rename(tmp_path / "images" / "train" / "b.jpg")
    h2, _ = _content_manifest_hash(tmp_path, "images/train", "images/val")
    assert h1 != h2
