"""证据能力启动初始化。

通用 store 只保存列表字段，推导所需的 AST、版本、身份映射在这里装载，
保证种子数据一上来就能试算/重算，而历史标签 TAG-0003 刻意不建版本，
用于演示「旧证据缺失」分支。
"""
from __future__ import annotations

from app.services.derive.parser import parse_expression
from app.services.derive.service import (
    filter_derive_service,
    sample_service,
    tag_derive_service,
)
from app.services.derive.store import SAMPLE_MODULE, evidence
from app.store import store
from app.seed import SEED_ROWS

_BOOTSTRAPPED = False

# 种子规则的结构化条件；标签表达式里的规则引用会拿到这里的快照
FILTER_CONDITIONS: dict[int, str] = {
    1: "近30天消费金额 大于 3000",
    2: '城市 包含 "上海" 或 近90天登录次数 大于等于 20',
    3: '风控等级 等于 "高"',
}

# 标签版本：表达式 + 同名字段的已确认身份（“等级”在 TAG-0002 里确认指向会员域）
TAG_EXPRESSIONS: dict[int, tuple[str, dict[str, str]]] = {
    1: ('规则("FILT-0001") 与 近90天登录次数 大于等于 15', {}),
    2: ('等级 等于 "A" 与 最近联系日期 不为空', {"等级": "会员等级"}),
    4: ('规则("FILT-0003") 或 是否企业客户 等于 是', {}),
}


def bootstrap_evidence() -> None:
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return
    # 样本表兜底：store 已含 seed 时不会重复
    if not store.rows(SAMPLE_MODULE):
        store.rows(SAMPLE_MODULE).extend(SEED_ROWS["sample_object"])

    for rule_id, condition in FILTER_CONDITIONS.items():
        ast = parse_expression(condition)
        evidence.register_filter(rule_id, condition, ast, {}, note="初始条件")

    for tag_id, (expression, identity_map) in TAG_EXPRESSIONS.items():
        ast = parse_expression(expression)
        evidence.add_tag_version(tag_id, expression, ast, identity_map, note="初始版本")

    _BOOTSTRAPPED = True


def reset_evidence() -> None:
    """测试/演示重置：业务表恢复种子，清空运行记录与确认解释，恢复初始规则与标签版本。"""
    store.reset_to_seed()
    evidence.filter_meta.clear()
    evidence.tag_versions.clear()
    evidence.runs.clear()
    evidence.explanations.clear()
    globals()["_BOOTSTRAPPED"] = False
    bootstrap_evidence()
