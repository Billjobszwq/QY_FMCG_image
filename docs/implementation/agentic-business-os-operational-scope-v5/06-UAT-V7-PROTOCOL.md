# 06 · UAT V7 协议（OSV5 T7）

namespace uatv7_<UTC>_<随机>；先建 Test Run，再经真实 multipart
Import API 完成 20 检查（指令第九节 1–20）。ids 新增：
import_batch_customer / import_batch_project / import_batch_address /
import_scope_associations / import_evidence / import_audit_events。
validator：protocol=uatv7 强制上述 6 键非空。
报告：.eval/scope_v5/uatv7/report.json。
