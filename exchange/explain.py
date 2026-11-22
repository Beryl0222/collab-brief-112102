"""可见性差异的解释。

联络人要能解释为什么一边看得到邀请而另一边暂时看不到；内部
理由可以引用具体规则，但公开公告不能暴露差别背后的私密内容，
所以每条解释都分内部与公开两层。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Explanation:
    internal: str   # 联络人可见，可引用具体规则与私密原因
    public: str     # 公告安全措辞，不含私密内容


class ExplainService:
    def __init__(self, materials, confidentiality):
        self._materials = materials
        self._confidentiality = confidentiality

    def material_access(self, viewer, material_id):
        """为什么某人看不到邀请里的资料说明。"""
        material = self._materials.get(material_id)
        if viewer in material.audience and viewer not in material.denied:
            return Explanation(
                internal=f"{viewer} 在《{material.name}》授权受众内，可以看到。",
                public="按资料授权范围提供。")
        reason = "被明确排除" if viewer in material.denied else "不在指定受众内"
        return Explanation(
            internal=(f"《{material.name}》（{material.id}）由{material.owner}授权，"
                      f"受众限{'、'.join(sorted(material.audience))}，"
                      f"用途限{material.purpose}；{viewer}{reason}。"),
            public="该资料按所有方授权范围提供。")

    def lock_pending(self, commitment):
        """为什么邀请看得到、时段却还没锁。"""
        waiting = [m for m, ok in commitment.lock_ok.items() if not ok]
        unconfirmed = [m for m, ok in commitment.confirmations.items() if not ok]
        parts = []
        if unconfirmed:
            parts.append(f"尚未确认：{'、'.join(unconfirmed)}")
        if waiting:
            parts.append(f"要求先别锁时段：{'、'.join(waiting)}")
        parts.extend(commitment.questions)
        return Explanation(
            internal="；".join(parts) or "等待相关方确认。",
            public="该提议尚在确认流程中。")

    def inquiry(self, inquiry):
        """为什么涉私打听不能公开回答。"""
        combos = [c for c in self._confidentiality.combos
                  if set(c.terms) & set(inquiry.terms)]
        if combos:
            terms = sorted(set().union(*(set(c.terms) for c in combos)))
            internal = (f"打听内容涉及保密词表组合（{'、'.join(terms)}），"
                        "组合出现会暴露项目身份，只能按成员各自许可回答。")
        else:
            internal = "打听内容属于他人未公开信息，需本人许可。"
        return Explanation(
            internal=internal,
            public="涉及保密范围，暂不公开说明。")
