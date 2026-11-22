"""候选匹配：把供给与需求结成提议。

- 只用本人声明的供给；转述线索不直接结队，列为待联络人核实的线索；
- 明确否定过的能力不得当作供给；
- 交换条件（“只想和会某能力的人交换”）必须整体满足，互助提议不拆开；
- 附条件依赖第三方资料的提议登记资料引用，授权只对指定受众和用途
  有效；未知条件与许可范围问题记入“待问”，不当作无条件供给。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class HelpEdge:
    """一条帮助流向：giver 用 capability 帮 receiver。"""

    giver: str
    receiver: str
    capability: str
    conditions: list = field(default_factory=list)


@dataclass
class Proposal:
    """一个候选提议（单向协助或双方互助）。"""

    id: str
    kind: str                     # one_way | mutual
    session: str
    parties: tuple
    edges: list = field(default_factory=list)
    support_offers: list = field(default_factory=list)  # 附带的供给（如样品）
    material_refs: list = field(default_factory=list)
    purpose: str = ""
    covers: int = 0               # 覆盖的已准备需求数
    questions: list = field(default_factory=list)       # 待问事项
    state: str = "candidate"      # candidate|planned|confirming|locked|blocked|invalidated
    note: str = ""

    def involves(self, member):
        return member in self.parties


class Matcher:
    def __init__(self, profiles, materials, sessions=None):
        self._profiles = profiles
        self._materials = materials
        # sessions: {场次id: {"priority": int, "who": [...]}}
        self._sessions = sessions or {}
        self.leads = []           # 转述线索，待联络人核实
        self._counter = 0

    def _session_for(self, parties):
        """从各方都在的场次里选优先级最高的。"""
        common = None
        for member in parties:
            mine = {s for s, info in self._sessions.items()
                    if member in info.get("who", [])}
            mine |= set(self._profiles[member].sessions)
            common = mine if common is None else (common & mine)
        if not common:
            return ""
        return min(common, key=lambda s: self._sessions.get(s, {}).get("priority", 99))

    def _new_id(self):
        self._counter += 1
        return f"P{self._counter}"

    def _exchange_ok(self, giver, receiver):
        """giver 的交换条件是否被 receiver 满足。"""
        profile = self._profiles[giver]
        for wish in profile.exchanges:
            if wish.require_counter is not None:
                key = wish.require_counter.key
                if self._profiles[receiver].offer_for(key) is None:
                    return False
                if self._profiles[receiver].declines(key):
                    return False
        return True

    def _material_conditions(self, parties):
        """收集各方档案里依赖第三方资料的条件。"""
        refs = []
        problems = []
        for member in parties:
            for cond in self._profiles[member].conditions:
                if cond.kind == "material" and cond.ref:
                    material = self._materials.by_name(cond.ref)
                    refs.append(material.id if material else cond.ref)
        return sorted(set(refs)), problems

    def generate(self):
        proposals = []
        members = sorted(self._profiles)

        # 转述线索：不结队，只列给联络人。
        for member in members:
            for lead in self._profiles[member].reported_leads:
                self.leads.append(
                    f"{member}转述：{lead.reported_from}会{lead.capability.key}"
                    "（线索，未核实）")

        for receiver in members:
            for need in self._profiles[receiver].needs:
                key = need.capability.key
                for giver in members:
                    if giver == receiver:
                        continue
                    if need.accept_from and giver not in need.accept_from:
                        continue
                    if self._profiles[giver].declines(key):
                        continue  # 明确否定过，不当作供给
                    offer = self._profiles[giver].offer_for(key)
                    if offer is None:
                        continue
                    if not self._exchange_ok(giver, receiver):
                        continue
                    proposals.append(self._build(giver, receiver, need, offer))

        # 双方互助：单向提议两两互补且交换条件互相满足时合并为互助。
        mutuals = []
        used = set()
        for i, first in enumerate(proposals):
            for second in proposals[i + 1:]:
                if first.parties != second.parties[::-1]:
                    continue
                if first.session != second.session:
                    continue
                a, b = first.parties
                if not (self._exchange_ok(a, b) and self._exchange_ok(b, a)):
                    continue
                merged = Proposal(
                    id=self._new_id(), kind="mutual", session=first.session,
                    parties=first.parties,
                    edges=first.edges + second.edges,
                    support_offers=first.support_offers + second.support_offers,
                    material_refs=sorted(set(first.material_refs)
                                         | set(second.material_refs)),
                    purpose=first.purpose or second.purpose)
                merged.questions = sorted(set(first.questions + second.questions))
                mutuals.append(merged)
                used.update({id(first), id(second)})
        proposals = [p for p in proposals if id(p) not in used] + mutuals

        # 由交换条件直接结成的互助（双方都没有显式“需求”，只声明了想换什么）。
        pairs = set()
        for proposal in proposals:
            pairs.add(frozenset(proposal.parties))
        for a in members:
            for wish in self._profiles[a].exchanges:
                if wish.want is None:
                    continue
                for b in members:
                    if b <= a or frozenset({a, b}) in pairs:
                        continue
                    offer_b = self._profiles[b].offer_for(wish.want.key)
                    if offer_b is None or self._profiles[b].declines(wish.want.key):
                        continue
                    back = None
                    for wish_b in self._profiles[b].exchanges:
                        if wish_b.want is not None and \
                                self._profiles[a].offer_for(wish_b.want.key) \
                                and not self._profiles[a].declines(wish_b.want.key):
                            back = wish_b
                            break
                    if back is None:
                        continue
                    if not (self._exchange_ok(a, b) and self._exchange_ok(b, a)):
                        continue
                    session = self._session_for((a, b))
                    material_refs, _ = self._material_conditions((a, b))
                    proposal = Proposal(
                        id=self._new_id(), kind="mutual", session=session,
                        parties=(a, b),
                        edges=[HelpEdge(giver=b, receiver=a,
                                        capability=wish.want.key),
                               HelpEdge(giver=a, receiver=b,
                                        capability=back.want.key)],
                        material_refs=material_refs,
                        purpose=wish.want.key)
                    self._attach_questions(proposal)
                    proposals.append(proposal)
                    pairs.add(frozenset({a, b}))

        # 覆盖的已准备需求数（未知条件的需求不算已准备）。
        for proposal in proposals:
            proposal.covers = self._coverage(proposal)
        return proposals

    def _build(self, giver, receiver, need, offer):
        parties = (giver, receiver)
        session = self._session_for(parties)
        material_refs, _ = self._material_conditions(parties)
        proposal = Proposal(
            id=self._new_id(), kind="one_way", session=session,
            parties=parties,
            edges=[HelpEdge(giver=giver, receiver=receiver,
                            capability=need.capability.key,
                            conditions=list(offer.conditions))],
            material_refs=material_refs,
            purpose=need.capability.key)

        # 接受方附带的供给（如“我给一套样品供方案讨论”）。
        for other in self._profiles[receiver].offers:
            if other.source == "self" and other.capability.key != need.capability.key:
                proposal.support_offers.append(other)

        # 资料授权核对：只对指定受众和用途有效；通过则条件视为满足。
        self._attach_questions(proposal)
        return proposal

    def _attach_questions(self, proposal):
        """核对资料授权并收集未知条件，写入提议的待问事项。"""
        parties = list(proposal.parties)
        for member in parties:
            for cond in self._profiles[member].conditions:
                if cond.kind != "material" or not cond.ref:
                    continue
                material = self._materials.by_name(cond.ref)
                if material is None:
                    proposal.questions.append(f"{member}：{cond.text}（资料未登记）")
                    continue
                if material.id not in proposal.material_refs:
                    proposal.material_refs.append(material.id)
                problems = self._materials.check(
                    material.id, parties, proposal.purpose)
                if problems:
                    proposal.questions.extend(problems)
                else:
                    cond.status = "satisfied"
                    # 资料指定的先行场次：使用该资料的成员所报名的场次。
                    for s in self._profiles[member].sessions:
                        if s not in material.prerequisite_sessions:
                            material.prerequisite_sessions.append(s)

        # 其余未知条件 → 待问，不当作无条件供给。
        for member in parties:
            for cond in self._profiles[member].open_conditions(
                    kinds={"generic", "timing"}):
                proposal.questions.append(f"{member}：{cond.text}")

    def _coverage(self, proposal):
        covered = 0
        for edge in proposal.edges:
            profile = self._profiles[edge.receiver]
            for need in profile.needs:
                if need.capability.key != edge.capability:
                    continue
                prepared = (
                    all(c.status == "satisfied" for c in need.conditions)
                    and not profile.open_conditions(kinds={"material", "timing"}))
                if prepared:
                    covered += 1
        for member in proposal.parties:
            for wish in self._profiles[member].exchanges:
                if wish.want is None:
                    continue
                others = [p for p in proposal.parties if p != member]
                if any(self._profiles[o].offer_for(wish.want.key) for o in others):
                    covered += 1
        return covered
