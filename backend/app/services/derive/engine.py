"""带证据捕获的表达式求值器。

每个 AST 节点求值后都会产出一条业务人员可读的 trace：
- 参与字段：字段名、来源、实际取值（含空值标记）；
- 比较过程：左值、运算符、右值、空值分支怎么走、是否命中；
- 规则引用：引用当时的规则编号、版本、条件快照与状态——
  规则之后被停用/修订也不改动这里保存的证据，由上层标记「证据已过期」；
- 逻辑节点：与/或每个分支的命中情况和最终结果。
"""
from __future__ import annotations

from typing import Any, Callable

from app.services.derive.fields import FieldAmbiguous, FieldMeta, resolve_field

NULL_LABEL = "空值"


class RuleNotFound(Exception):
    """表达式引用了不存在的筛选规则。"""


RuleResolver = Callable[[str], dict[str, Any] | None]


def _display(value: Any) -> str:
    if value is None or value == "":
        return NULL_LABEL
    if value is True:
        return "是"
    if value is False:
        return "否"
    return str(value)


def _compare(op: str, left: Any, right: Any) -> bool:
    if op in ("为空",):
        return left is None or left == ""
    if op in ("不为空",):
        return not (left is None or left == "")
    if left is None or left == "":
        # 所有带比较值的运算符遇到空值都走空值分支：不命中，并由调用方记录原因
        return False
    if op == "等于":
        return left == right or str(left) == str(right)
    if op == "不等于":
        return not (left == right or str(left) == str(right))
    if op == "包含":
        return str(right) in str(left)
    if op == "不包含":
        return str(right) not in str(left)
    # 大小比较：尽量按数值，退不回字符串就按字典序
    try:
        lv, rv = float(left), float(right)
    except (TypeError, ValueError):
        lv, rv = str(left), str(right)
    if op == "大于":
        return lv > rv
    if op == "大于等于":
        return lv >= rv
    if op == "小于":
        return lv < rv
    if op == "小于等于":
        return lv <= rv
    raise ValueError(f"暂不支持的运算符「{op}」")


def evaluate(
    node: dict[str, Any],
    obj: dict[str, Any],
    *,
    identity_map: dict[str, str],
    rule_resolver: RuleResolver,
) -> tuple[bool, dict[str, Any]]:
    """求值一个 AST 节点，返回 (是否命中, 解释 trace)。"""
    kind = node.get("type")
    if kind == "compare":
        return _eval_compare(node, obj, identity_map)
    if kind == "logic":
        return _eval_logic(node, obj, identity_map, rule_resolver)
    if kind == "rule":
        return _eval_rule(node, obj, identity_map, rule_resolver)
    raise ValueError(f"未知表达式节点类型：{kind}")


def _eval_compare(
    node: dict[str, Any], obj: dict[str, Any], identity_map: dict[str, str]
) -> tuple[bool, dict[str, Any]]:
    field_label = str(node["field"])
    op = str(node["op"])
    expected = node.get("value")
    try:
        meta: FieldMeta = resolve_field(field_label, identity_map)
    except FieldAmbiguous:
        raise
    actual = obj.get(meta.key)
    is_null = actual is None or actual == ""

    if op in ("为空", "不为空"):
        hit = _compare(op, actual, None)
        text = f"字段「{meta.label}」（来源：{meta.source}）当前为{_display(actual)}，{op}判断结果为{'命中' if hit else '不命中'}"
        value_note = "空值分支：该字段没有取值，直接按空值规则判定" if is_null else ""
    else:
        hit = _compare(op, actual, expected)
        if is_null:
            text = (
                f"字段「{meta.label}」（来源：{meta.source}）当前为{NULL_LABEL}，"
                f"空值分支下「{op} {_display(expected)}」直接判定为不命中"
            )
            value_note = "空值分支：字段无取值，比较条件短路为不命中"
        else:
            text = (
                f"字段「{meta.label}」（来源：{meta.source}）取值 {_display(actual)}，"
                f"{op} {_display(expected)} → {'命中' if hit else '不命中'}"
            )
            value_note = ""

    trace = {
        "kind": "compare",
        "hit": hit,
        "text": text,
        "field": {"label": meta.label, "key": meta.key, "source": meta.source, "value": actual, "isNull": is_null},
        "op": op,
        "expected": expected,
        "valueNote": value_note,
    }
    return hit, trace


def _eval_logic(
    node: dict[str, Any],
    obj: dict[str, Any],
    identity_map: dict[str, str],
    rule_resolver: RuleResolver,
) -> tuple[bool, dict[str, Any]]:
    op = str(node["op"])
    branch_hits: list[bool] = []
    steps: list[dict[str, Any]] = []
    for child in node["children"]:
        hit, trace = evaluate(child, obj, identity_map=identity_map, rule_resolver=rule_resolver)
        branch_hits.append(hit)
        steps.append(trace)
    hit = all(branch_hits) if op == "与" else any(branch_hits)
    text = (
        f"按「{op}」组合 {len(steps)} 个分支："
        + ("、".join(f"分支{i + 1}{'命中' if ok else '不命中'}" for i, ok in enumerate(branch_hits)))
        + f" → 整体{'命中' if hit else '不命中'}"
    )
    return hit, {"kind": "logic", "op": op, "hit": hit, "text": text, "steps": steps}


def _eval_rule(
    node: dict[str, Any],
    obj: dict[str, Any],
    identity_map: dict[str, str],
    rule_resolver: RuleResolver,
) -> tuple[bool, dict[str, Any]]:
    code = str(node["code"])
    rule = rule_resolver(code)
    if rule is None:
        trace = {
            "kind": "rule",
            "hit": False,
            "text": f"引用筛选规则「{code}」，但该规则不存在或已归档，按不命中处理",
            "ruleCode": code,
            "ruleMissing": True,
        }
        return False, trace

    sub_hit, sub_trace = evaluate(
        rule["ast"], obj, identity_map={**rule.get("identityMap", {}), **identity_map},
        rule_resolver=rule_resolver,
    )
    # 证据快照：规则此刻的版本与条件文本；将来规则停用/修订，这份快照保持不变
    snapshot = {
        "ruleId": rule["id"],
        "ruleCode": code,
        "version": rule["version"],
        "status": rule["status"],
        "conditionText": rule["conditionText"],
        "revisions": rule.get("revisions", []),
    }
    status_note = ""
    if rule["status"] == "已停用":
        status_note = "该规则当前已停用；本证据记录的是引用时刻的条件，重算需重新确认"
    trace = {
        "kind": "rule",
        "hit": sub_hit,
        "text": (
            f"引用筛选规则「{code}」v{rule['version']}（当前状态：{rule['status']}），"
            f"按规则内条件求值 → {'命中' if sub_hit else '不命中'}"
        ),
        "ruleCode": code,
        "ruleMissing": False,
        "snapshot": snapshot,
        "jump": {"module": "filter", "ruleId": rule["id"], "version": rule["version"]},
        "statusNote": status_note,
        "steps": [sub_trace],
    }
    return sub_hit, trace
