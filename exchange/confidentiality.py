"""保密词表：声明哪些词组合起来会识别项目，并净化公开内容。

社区在排班资料里声明组合（如“云码头 + 灯雀”）。公开介绍只使用
允许公布的词；若允许公布的词凑齐了一个敏感组合，必须隐去其中
一项——优先隐去未被明确允许单说的词，并记录原因供联络人查看。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SensitiveCombo:
    """一组共同出现即暴露原型身份的词。"""

    terms: frozenset
    note: str = ""


@dataclass
class Withheld:
    """被隐去的词及原因（仅联络人可见）。"""

    term: str
    reason: str


class ConfidentialityList:
    """保密词表与净化逻辑。"""

    def __init__(self, combos=None):
        self._combos = list(combos or [])

    @classmethod
    def from_resources(cls, resources):
        """从排班资料读取 confidentiality 记录。"""
        combos = []
        for row in resources:
            if row.get("kind") == "confidentiality":
                combos.append(SensitiveCombo(
                    terms=frozenset(row["expose_identity_if_combined"]),
                    note=row.get("id", "")))
        return cls(combos)

    @property
    def terms(self):
        """词表涉及的全部敏感词。"""
        out = set()
        for combo in self._combos:
            out |= set(combo.terms)
        return out

    @property
    def combos(self):
        return list(self._combos)

    def violations(self, terms):
        """terms 中已凑齐的敏感组合。"""
        return [c for c in self._combos if set(c.terms) <= set(terms)]

    def sanitize(self, terms, protected=()):
        """净化一组拟公开的词。

        protected: 成员明确允许单说的词（如“单说云码头可以”），
        凑齐组合时优先隐去未受保护的词。返回 (可公开集合, 隐去记录)。
        """
        kept = set(terms)
        withheld = []
        for combo in self._combos:
            while set(combo.terms) <= kept:
                candidates = sorted(set(combo.terms) - set(protected))
                drop = candidates[0] if candidates else sorted(combo.terms)[-1]
                kept.discard(drop)
                withheld.append(Withheld(
                    term=drop,
                    reason=f"与{'、'.join(sorted(set(combo.terms) - {drop}))}"
                           f"同时出现会暴露项目身份（{combo.note or '保密词表'}）"))
        return kept, withheld
