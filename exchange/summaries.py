"""安全摘要：联络人起草、成员确认、按可见范围分层展示。

成员确认前，其他人能看到的仅限允许公开的部分；确认后，配对
对方才能看到 MATCHED 层。原始留言、转述线索、涉私打听只留在
联络人层。公开公告只由 PUBLIC 层组成，并经过保密词表净化。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import Visibility


@dataclass
class SafeSummary:
    """一个成员的安全摘要。"""

    member: str
    sections: dict = field(default_factory=dict)  # Visibility -> list[str]
    withheld: list = field(default_factory=list)  # 被保密词表隐去的词（联络人可见）
    protected: set = field(default_factory=set)   # 明确允许单说的词
    status: str = "draft"                         # draft | pending | confirmed
    version: int = 1


class SummaryService:
    def __init__(self, confidentiality):
        self._confidentiality = confidentiality
        self._summaries = {}

    def draft(self, profile):
        """从档案起草分层摘要。"""
        sections = {v: [] for v in Visibility}

        # PUBLIC：只允许明确许可公布的内容，并过保密词表。
        public_terms = set()
        protected = set()
        for rule in profile.permissions:
            if rule.allowed and rule.visibility == Visibility.PUBLIC:
                public_terms.add(rule.target)
                protected.add(rule.target)
        for attr, visibility in profile.attribute_visibility.items():
            if visibility == Visibility.PUBLIC and attr in profile.attributes:
                public_terms.add(profile.attributes[attr])
        kept, withheld = self._confidentiality.sanitize(
            public_terms, protected=protected)
        sections[Visibility.PUBLIC] = sorted(kept)

        # MATCHED：能力层面的供需与交换条件（不含私密细节）。
        for offer in profile.offers:
            if offer.source == "self":
                sections[Visibility.MATCHED].append(f"能提供：{offer.capability.key}")
        for need in profile.needs:
            sections[Visibility.MATCHED].append(f"需要补：{need.capability.key}")
        for wish in profile.exchanges:
            if wish.want is not None:
                sections[Visibility.MATCHED].append(f"想换：{wish.want.key}")

        # CONTACT：原文、转述线索、否定声明、涉私打听。
        sections[Visibility.CONTACT] = list(profile.raw)
        for lead in profile.reported_leads:
            sections[Visibility.CONTACT].append(
                f"转述线索（{lead.reported_from}）：{lead.capability.key}")
        for non in profile.non_offers:
            sections[Visibility.CONTACT].append(f"明确不做：{non.capability.key}")
        for inquiry in profile.inquiries:
            sections[Visibility.CONTACT].append(f"涉私打听：{inquiry.text}")

        # SELF：本人可见全部结构化内容。
        sections[Visibility.SELF] = [
            f"许可规则：{r.text}" for r in profile.permissions if r.text]

        summary = SafeSummary(
            member=profile.member, sections=sections,
            withheld=withheld, protected=protected)
        self._summaries[profile.member] = summary
        return summary

    def invite_confirm(self, member):
        """联络人邀请成员确认摘要；确认前他人只见公开部分。"""
        summary = self._summaries[member]
        if summary.status == "draft":
            summary.status = "pending"
        return summary

    def confirm(self, member):
        summary = self._summaries[member]
        summary.status = "confirmed"
        return summary

    def get(self, member):
        return self._summaries[member]

    def view(self, member, viewer, *, is_contact=False, is_matched=False):
        """按查看者身份返回有权看到的部分。"""
        summary = self._summaries[member]
        if is_contact:
            return dict(summary.sections), list(summary.withheld)
        if viewer == member:
            return {v: s for v, s in summary.sections.items()
                    if v != Visibility.CONTACT}, []
        visible = {Visibility.PUBLIC: summary.sections[Visibility.PUBLIC]}
        # 成员确认前，其他人能看到的仅限允许公开的部分。
        if is_matched and summary.status == "confirmed":
            visible[Visibility.MATCHED] = summary.sections[Visibility.MATCHED]
        return visible, []

    def announcement(self, members=None):
        """生成公共公告：只含各成员 PUBLIC 层，整体再过一次保密词表。"""
        members = members or list(self._summaries)
        terms = set()
        protected = set()
        for member in members:
            summary = self._summaries[member]
            terms |= set(summary.sections[Visibility.PUBLIC])
            protected |= summary.protected
        kept, _ = self._confidentiality.sanitize(terms, protected=protected)
        lines = []
        for member in members:
            summary = self._summaries[member]
            shown = sorted(set(summary.sections[Visibility.PUBLIC]) & kept)
            if shown:
                lines.append(f"{member}：{'、'.join(shown)}")
        return "\n".join(lines)
