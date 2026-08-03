from src.catalog import naming


def test_parse_volume_and_sugar():
    assert naming.parse("500ml茉莉乌龙（无糖）")["volume_ml"] == 500
    assert naming.parse("500ml茉莉乌龙（无糖）")["sugar"] == "无糖"
    assert naming.parse("乌龙茶无糖PET1250ML")["volume_ml"] == 1250
    assert naming.parse("550ml沁柠水")["sugar"] is None


def test_match_key_unifies_two_naming_styles():
    assert naming.match_key("乌龙茶无糖PET1250ML") == naming.match_key("1250ml原味乌龙茶（无糖）")
    assert naming.match_key("茉莉乌龙无糖PET900ML") == naming.match_key("900ml茉莉乌龙（无糖）")


def test_match_key_separates_different_skus():
    assert naming.match_key("乌龙茶无糖PET350ML") != naming.match_key("乌龙茶无糖PET900ML")
    assert naming.match_key("500ml茉莉乌龙（无糖）") != naming.match_key("500ml茉莉乌龙（微甜）")


def test_typo_not_fixed_by_normalize():
    # 错字(楼/樱)归一化救不了，必须靠别名表 —— 此测试记录这一事实
    assert naming.match_key("针叶楼桃味维C饮PET450ML") != naming.match_key("针叶樱桃味维C饮PET450ML")
