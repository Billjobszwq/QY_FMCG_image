"""G6 训练输出治理测试：run 目录已存在 fail-closed + classifier 显式数据目录。"""
import pytest


def test_train_v1_rejects_existing_run_dir(tmp_path, monkeypatch):
    """已有 run 目录必须拒绝运行（禁止 exist_ok=True 覆盖旧实验）。"""
    from src.training import train_v1 as TV
    monkeypatch.setattr(TV, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(TV, "validate_dataset", lambda y: {
        "dataset_hash": "x", "content_hash": "y", "n_train": 1, "n_val": 1, "nc": 1})
    (tmp_path / "existing_run").mkdir()
    with pytest.raises(RuntimeError, match="拒绝覆盖"):
        TV.train(epochs=1, run_name="existing_run", data_yaml="fake.yaml")


def test_train_v1_run_dir_mkdir_no_exist_ok():
    """G6：train_v1.train 源码必须显式 exist_ok=False，不得残留 exist_ok=True。"""
    import inspect
    from src.training import train_v1 as TV
    src = inspect.getsource(TV.train)
    # 剥离注释行，只检查实际代码
    code = "\n".join(ln.split("#")[0] for ln in src.splitlines())
    assert "exist_ok=False" in code
    assert "exist_ok=True" not in code


def test_classifier_train_requires_data_dir():
    """classifier.train 不传 data_dir 必须 fail-closed（禁止默认读旧 crop_dataset）。"""
    from src.cascade import classifier as C
    with pytest.raises(RuntimeError, match="data_dir"):
        C.train(run_tag="g6test", data_dir=None)


def test_classifier_get_datasets_requires_data_dir():
    from src.cascade import classifier as C
    with pytest.raises(RuntimeError, match="crop_dataset"):
        C.get_datasets(224, data_dir=None)


def test_classifier_cli_data_dir_flag():
    """CLI 必须提供 --data-dir（G6 显式数据目录要求）。"""
    import inspect
    from src.cascade import classifier as C
    src = inspect.getsource(C)
    assert '"--data-dir"' in src


def test_build_dataset_v7_rejects_existing_dataset(tmp_path, monkeypatch):
    """G3：数据集发布目录已存在必须拒绝覆盖。"""
    from src.training import build_dataset_v7 as B7
    monkeypatch.setattr(B7, "DATASETS_DIR", tmp_path)
    (tmp_path / "already_there").mkdir()
    with pytest.raises(RuntimeError, match="拒绝覆盖"):
        B7.build("already_there")
