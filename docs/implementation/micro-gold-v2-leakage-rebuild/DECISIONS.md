# DECISIONS
- D1 起始 Gate=MICRO_GOLD_REBUILD_REQUIRED_DUE_TO_LEAKAGE。
- D2 Forbidden Identity Index v2 为唯一排除事实源（20,597 SHA/8,338 group/
  9,232 photo/2,317 store-session/21,232 symlink）。
- D3 micro-gold v2 provisional 证据链 = SAM mask(sha+score) + classifier
  版本+conf（仅审计侧，人工不可见，非 human_final）。
- D4 min-conf 0.3（provisional 置信，非泄漏门禁）；canonical 120/40/20/20 达成；
  类覆盖 27/38，11 类独立池缺失如实报告（DONE_WITH_CONCERNS 分支）。
- D5 LS22 config：extra status choices 插入标签闭合后（修复 LSF 崩溃）。
- D6 M4 v3 holdout 排除 micro-gold v2 已用照片 + forbidden index；候选冻结。
