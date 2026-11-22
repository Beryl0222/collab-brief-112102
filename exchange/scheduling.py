"""排班：把候选提议排进场次容量。

规则：
- 优先完成资料指定的先行场次；
- 随后在不拆开互助条件的前提下，尽量覆盖更多已准备的需求；
- 同一成员的容量有限（max_sessions），不同组候选可能竞争同一个
  唯一时段；提议本身不耗时段——只有锁定（commitments 模块）才占用；
- 因未知条件或保密范围而待问的提议单独列出，与可申请确认的分开。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SessionInfo:
    id: str
    priority: int
    who: list = field(default_factory=list)


@dataclass
class Availability:
    who: str
    times: list = field(default_factory=list)
    max_sessions: int = 1


class Scheduler:
    def __init__(self, sessions, availabilities, materials):
        self._sessions = sessions            # {id: SessionInfo}
        self._availability = {a.who: a for a in availabilities}
        self._materials = materials
        self._planned = {}                   # member -> 已排场次数（不含锁定）
        self._locked = {}                    # member -> 已锁定场次数

    # -- 容量 -------------------------------------------------------------

    def _used(self, member):
        return self._planned.get(member, 0) + self._locked.get(member, 0)

    def capacity_left(self, member):
        avail = self._availability.get(member)
        if avail is None:
            return float("inf")
        return avail.max_sessions - self._used(member)

    def locked_count(self, member):
        """真正被锁定承诺占用的场次数；提议与待确认阶段不计入。"""
        return self._locked.get(member, 0)

    def fits(self, proposal):
        return all(self.capacity_left(m) >= 1 for m in proposal.parties)

    def consume_planned(self, proposal):
        for member in proposal.parties:
            if member in self._availability:
                self._planned[member] = self._planned.get(member, 0) + 1

    def release_planned(self, proposal):
        for member in proposal.parties:
            if member in self._planned and self._planned[member] > 0:
                self._planned[member] -= 1

    def consume_locked(self, proposal):
        """锁定时才真正占用时段；提议与待确认阶段不耗时段。"""
        for member in proposal.parties:
            if member in self._availability:
                self._locked[member] = self._locked.get(member, 0) + 1

    def release_locked(self, proposal):
        """承诺失效后释放时段，空下的名额可交给其他候选。"""
        for member in proposal.parties:
            if member in self._locked and self._locked[member] > 0:
                self._locked[member] -= 1

    # -- 排序与排班 -------------------------------------------------------

    def _priority_key(self, proposal):
        prereq = any(
            proposal.session in self._materials.get(ref).prerequisite_sessions
            for ref in proposal.material_refs
            if ref in self._materials.all())
        session = self._sessions.get(proposal.session)
        priority = session.priority if session else 99
        # 先行场次优先，其次覆盖更多已准备需求。
        return (0 if prereq else 1, priority, -proposal.covers, proposal.id)

    def plan(self, proposals):
        """对候选提议排出计划；返回 (已排, 未获排)。"""
        planned, skipped = [], []
        for proposal in sorted(proposals, key=self._priority_key):
            if proposal.state not in {"candidate", "planned"}:
                continue
            if self.fits(proposal):
                proposal.state = "planned"
                self.consume_planned(proposal)
                planned.append(proposal)
            else:
                proposal.note = "时段容量竞争未获排"
                skipped.append(proposal)
        return planned, skipped

    def replan(self, proposals):
        """容量释放后重排未获排的候选。"""
        return self.plan(proposals)

    # -- 排班视图 ---------------------------------------------------------

    def pending_questions(self, proposals):
        """因未知条件或保密范围而待问的提议。"""
        return {p.id: list(p.questions) for p in proposals if p.questions}

    def appliable(self, proposals):
        """可以分别申请确认的提议：已排定且无待问。"""
        return [p for p in proposals
                if p.state == "planned" and not p.questions]
