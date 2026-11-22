"""基础数据模型：能力、条件、许可、成员档案。

成员档案由解析器从原始留言逐步合并而成，原始文字始终保留在
``raw`` 中，只有联络人可见；对外只暴露按许可分层的内容。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Visibility(str, Enum):
    """内容的可见范围。"""

    PUBLIC = "public"    # 允许上公共公告
    MATCHED = "matched"  # 仅配对成功的对方可见
    CONTACT = "contact"  # 仅联络人可见
    SELF = "self"        # 仅成员本人可见


@dataclass(frozen=True)
class Capability:
    """归一化后的能力。key 用于匹配，surface 保留原文说法。"""

    key: str
    surface: str = ""


@dataclass
class Condition:
    """附条件。

    kind: generic（一般）/ material（依赖第三方资料）/ lock（锁时段意愿）/
    fallback（兜底安排）。status: unknown / satisfied / failed。
    未知条件会让提议进入“待问”，而不是被当作无条件供给。
    """

    text: str
    kind: str = "generic"
    ref: Optional[str] = None      # 依赖的资料 id 等
    status: str = "unknown"


@dataclass
class Offer:
    """明确能给出的帮助。source=reported 表示转述来的线索，不算本人供给。"""

    capability: Capability
    conditions: list[Condition] = field(default_factory=list)
    source: str = "self"
    reported_from: Optional[str] = None
    note: str = ""


@dataclass
class Need:
    """真正要补的能力。accept_from 限定接受哪些成员提供。"""

    capability: Capability
    accept_from: Optional[frozenset] = None
    conditions: list[Condition] = field(default_factory=list)
    note: str = ""


@dataclass
class NonOffer:
    """明确否定：本人声明不做的事，匹配时不得当作供给。"""

    capability: Capability
    text: str = ""


@dataclass
class PermissionRule:
    """许可范围规则。allowed=False 表示明确拒绝。

    parties 是具名对象（如“赞助方”“墨舟”），为空表示对所有人。
    """

    target: str
    allowed: bool
    visibility: Visibility = Visibility.PUBLIC
    parties: frozenset = frozenset()
    text: str = ""


@dataclass
class ExchangeWish:
    """交换条件：只愿用自己的时段换对方的具体帮助。

    require_counter 要求对方必须具备某能力；one_slot 表示只给一个
    时段内能做完的安排。互助提议必须整体满足，不能拆开。
    """

    want: Optional[Capability] = None
    require_counter: Optional[Capability] = None
    one_slot: bool = False
    text: str = ""


@dataclass
class Inquiry:
    """成员向联络人提出的涉私问题（如打听他人身份），不得公开回答。"""

    text: str
    terms: list = field(default_factory=list)


@dataclass
class MemberProfile:
    """成员档案：由多条留言与澄清合并而成。"""

    member: str
    offers: list = field(default_factory=list)            # list[Offer]
    needs: list = field(default_factory=list)             # list[Need]
    non_offers: list = field(default_factory=list)        # list[NonOffer]
    permissions: list = field(default_factory=list)       # list[PermissionRule]
    exchanges: list = field(default_factory=list)         # list[ExchangeWish]
    conditions: list = field(default_factory=list)        # list[Condition] 成员级条件
    reported_leads: list = field(default_factory=list)    # list[Offer] 转述线索
    attributes: dict = field(default_factory=dict)        # 如 {"商品代号": "灯雀"}
    attribute_visibility: dict = field(default_factory=dict)
    inquiries: list = field(default_factory=list)         # list[Inquiry]
    sessions: list = field(default_factory=list)          # 报名场次 id
    raw: list = field(default_factory=list)               # 原始留言，仅联络人可见

    # -- 查询 -------------------------------------------------------------

    def offer_for(self, key: str):
        """本人（非转述）对某能力的有效供给。"""
        for offer in self.offers:
            if offer.source == "self" and offer.capability.key == key:
                return offer
        return None

    def declines(self, key: str) -> bool:
        """本人是否明确否定过某能力。"""
        return any(n.capability.key == key for n in self.non_offers)

    def visibility_of(self, target: str, default: Visibility) -> Visibility:
        """目标内容的可见范围；后到的澄清覆盖先前的规则。"""
        result = default
        for rule in self.permissions:
            if rule.target == target:
                result = rule.visibility if rule.allowed else Visibility.CONTACT
        return result

    def open_conditions(self, kinds=None) -> list:
        """尚未满足的条件（unknown），可按 kind 过滤。"""
        return [
            c for c in self.conditions
            if c.status == "unknown" and (kinds is None or c.kind in kinds)
        ]
