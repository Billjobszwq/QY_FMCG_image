"""G4/G2 门店规范化单元测试：NFKC、全半角括号、标点、空白、casefold、别名。"""
from src.data import store_norm as SN


def test_full_half_width_parentheses_collapse():
    """dev_v1 两个重叠案例：全/半角括号差异必须收敛到同一 canonical key。"""
    assert SN.norm_store("何惠晴（上海如海）") == SN.norm_store("何惠晴(上海如海)")
    assert SN.norm_store("陈娟（承照便利店)") == SN.norm_store("陈娟(承照便利店)")


def test_nfkc_fullwidth_ascii():
    assert SN.norm_store("ＡＢＣ１２３") == SN.norm_store("abc123")


def test_punctuation_mapping():
    assert SN.norm_store("门店【Ａ】") == SN.norm_store("门店[a]")
    assert SN.norm_store("甲。店") == SN.norm_store("甲.店")
    assert SN.norm_store("甲，乙") == SN.norm_store("甲,乙")


def test_whitespace_removed():
    assert SN.norm_store("甲  乙\t店") == SN.norm_store("甲乙店")
    assert SN.norm_store("甲　乙") == SN.norm_store("甲乙")  # 全角空格


def test_casefold_stricter_than_lower():
    # casefold 比 lower 更严格：德语 ß → ss（lower 不会展开）
    assert SN.norm_store("STRASSE") == SN.norm_store("straße")
    assert SN.norm_store("ABC") == SN.norm_store("abc")


def test_none_and_empty():
    assert SN.norm_store(None) == ""
    assert SN.norm_store("") == ""


def test_alias_table_mapping():
    SN.ALIAS_TABLE.clear()
    try:
        SN.ALIAS_TABLE[SN.norm_store("老名")] = SN.norm_store("新名")
        assert SN.norm_store("老名") == SN.norm_store("新名")
    finally:
        SN.ALIAS_TABLE.clear()


def test_store_of_filename():
    assert SN.store_of_filename("连锁_门店甲_货架_20260801_x_1.jpg") == "门店甲"
    assert SN.store_of_filename("onlyone.jpg") == "NA"  # 无第二段 → NA
    assert SN.store_of_filename("x") == "NA"


def test_session_of_filename():
    s1 = SN.session_of_filename("连锁_何惠晴（上海如海）_货架_20260730_x_1.jpg")
    s2 = SN.session_of_filename("连锁_何惠晴(上海如海)_货架_20260730_x_2.jpg")
    assert s1 == s2  # 同门店同日期的不同括号写法必须同 session
    s3 = SN.session_of_filename("连锁_何惠晴(上海如海)_货架_20260731_x_2.jpg")
    assert s3 != s1  # 不同日期不同 session


def test_session_no_date_fallback():
    s = SN.session_of_filename("连锁_门店甲_货架_abc_x_1.jpg")
    assert s.endswith("@nodate")
