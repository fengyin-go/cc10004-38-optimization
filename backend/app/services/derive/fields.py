"""字段目录与同名字段身份消解。

演示样本里「等级」同时来自会员域和风控域，光看字段名无法确定指向。
所有表达式中的字段引用都经过这里解析：
- 已确认身份（identity_map）优先级最高，确认过的身份不会被后加的同名字段抢走；
- 全库唯一的中文名直接命中；
- 存在多个同名字段且没有确认身份时，抛出 FieldAmbiguous，由业务人员确认后再算。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldMeta:
    key: str  # 样本对象里实际取值用的键
    label: str  # 业务人员看到的字段名（同名字段会重名）
    source: str  # 字段来源域
    kind: str  # text | number | date | boolean


class FieldAmbiguous(Exception):
    """同名字段存在多个候选身份，且当前版本尚未确认用哪一个。"""

    def __init__(self, label: str, candidates: list[FieldMeta]) -> None:
        self.label = label
        self.candidates = candidates
        keys = "、".join(f"{item.label}（{item.source}：{item.key}）" for item in candidates)
        super().__init__(f"字段「{label}」存在同名字段冲突，请先确认身份：{keys}")


# 演示样本固定字段目录；真实项目里这一层来自数据集元数据。
FIELD_CATALOG: list[FieldMeta] = [
    FieldMeta("客户编号", "客户编号", "客户主数据", "text"),
    FieldMeta("客户名称", "客户名称", "客户主数据", "text"),
    FieldMeta("城市", "城市", "客户主数据", "text"),
    FieldMeta("会员等级", "等级", "会员域", "text"),
    FieldMeta("风控等级", "等级", "风控域", "text"),
    FieldMeta("近30天消费金额", "近30天消费金额", "交易域", "number"),
    FieldMeta("近90天登录次数", "近90天登录次数", "行为域", "number"),
    FieldMeta("最近联系日期", "最近联系日期", "客户主数据", "date"),
    FieldMeta("是否企业客户", "是否企业客户", "客户主数据", "boolean"),
]

FIELD_BY_KEY = {item.key: item for item in FIELD_CATALOG}


def resolve_field(label_or_key: str, identity_map: dict[str, str]) -> FieldMeta:
    """把表达式里写的字段名解析成确定身份的字段元数据。

    identity_map: {字段显示名: 已确认的字段 key}，按标签/规则版本持久化。
    """
    token = label_or_key.strip()
    # 直接写了带来源的限定名（等级@风控域）或存储键，直接落库查
    if "@" in token:
        label, _, source = token.partition("@")
        for item in FIELD_CATALOG:
            if item.label == label and item.source == source:
                return item
        raise KeyError(f"字段「{token}」在字段目录中不存在")
    if token in FIELD_BY_KEY:
        return FIELD_BY_KEY[token]

    confirmed_key = identity_map.get(token)
    if confirmed_key and confirmed_key in FIELD_BY_KEY:
        # 已确认身份以确认记录为准，即使后续又新增同名字段也不改变指向
        return FIELD_BY_KEY[confirmed_key]

    matches = [item for item in FIELD_CATALOG if item.label == token]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise FieldAmbiguous(token, matches)
    raise KeyError(f"字段「{token}」在字段目录中不存在")


def catalog_payload() -> list[dict[str, str]]:
    """给前端的字段目录，同名同标签字段并列展示，方便做身份确认。"""
    return [
        {"key": item.key, "label": item.label, "source": item.source, "kind": item.kind}
        for item in FIELD_CATALOG
    ]
