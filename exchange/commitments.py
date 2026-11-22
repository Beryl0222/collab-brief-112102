"""承诺与确认：申请、邀请、锁定、撤回、改约。

- 排班确定的提议可分别申请确认；每份邀请的编号由受理时生成；
- 参与方在看到各自有权看到的摘要后确认；
- 同一互助承诺的相关方都同意、且资料条件满足后，才锁时段——
  在此之前提议不耗时段；
- 撤回资料使用许可时：待确认邀请中不得再带出该资料；已经约好的
  会面只有在承诺依赖该资料时才受影响；
- 受影响的小组可改成双方都能接受的新约，但须重新确认；空下的
  名额交回排班，让给其他候选。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import Visibility


@dataclass
class Invitation:
    """发给某一方的邀请，只含其有权看到的内容。"""

    id: str
    commitment_id: str
    to_member: str
    view: dict = field(default_factory=dict)   # 对方成员的可见摘要
    material_notes: list = field(default_factory=list)  # 授权范围内的资料说明


@dataclass
class Commitment:
    """一份待确认/已锁定的承诺。"""

    id: str
    proposal: object
    confirmations: dict = field(default_factory=dict)  # member -> bool
    lock_ok: dict = field(default_factory=dict)        # member -> 是否允许锁时段
    state: str = "confirming"  # confirming | locked | blocked | invalidated | superseded
    questions: list = field(default_factory=list)
    note: str = ""

    def parties(self):
        return self.proposal.parties


class CommitmentService:
    def __init__(self, materials, summaries, scheduler):
        self._materials = materials
        self._summaries = summaries
        self._scheduler = scheduler
        self._commitments = {}
        self._invitations = {}
        self._counter = 0

    # -- 申请与邀请 -------------------------------------------------------

    def apply(self, proposal):
        """分别申请确认；有待问事项的提议不能申请。"""
        if proposal.questions:
            raise ValueError(f"{proposal.id} 有待问事项，不能申请确认：{proposal.questions}")
        if proposal.state != "planned":
            raise ValueError(f"{proposal.id} 未排定，不能申请确认")
        self._counter += 1
        commitment = Commitment(
            id=f"C{self._counter}", proposal=proposal,
            confirmations={m: False for m in proposal.parties},
            lock_ok={m: True for m in proposal.parties})
        proposal.state = "confirming"
        self._commitments[commitment.id] = commitment
        self._invitations[commitment.id] = self._make_invitations(commitment)
        return commitment

    def _make_invitations(self, commitment):
        """为每一方生成邀请：对方摘要按可见范围过滤，资料说明只给授权受众。"""
        invitations = {}
        proposal = commitment.proposal
        for member in proposal.parties:
            others = [p for p in proposal.parties if p != member]
            view = {}
            for other in others:
                visible, _ = self._summaries.view(
                    other, member, is_matched=True)
                view[other] = visible
            notes = []
            for ref in proposal.material_refs:
                material = self._materials.get(ref)
                if material.withdrawn:
                    continue  # 待确认邀请中不得再带出已撤回的资料
                if member in material.audience and member not in material.denied:
                    notes.append(
                        f"可使用资料《{material.name}》（限{material.purpose}）")
            invitation = Invitation(
                id=f"INV-{self._counter}-{member}",
                commitment_id=commitment.id, to_member=member,
                view=view, material_notes=notes)
            invitations[member] = invitation
        return invitations

    def invitation_for(self, commitment_id, member):
        return self._invitations[commitment_id][member]

    # -- 确认与锁定 -------------------------------------------------------

    def record_consent(self, consent):
        """把回条登记到匹配的待确认承诺上。"""
        target = self._match_consent(consent)
        if target is None:
            return None
        if consent.confirms:
            target.confirmations[consent.who] = True
        target.lock_ok[consent.who] = consent.allow_lock
        return target

    def _match_consent(self, consent):
        best, best_score = None, 0
        for commitment in self._commitments.values():
            if commitment.state != "confirming":
                continue
            proposal = commitment.proposal
            if consent.who not in proposal.parties:
                continue
            if proposal.session != consent.accepted_for:
                continue
            score = 1
            caps = {e.capability for e in proposal.edges}
            score += len(caps & consent.capabilities)
            mentioned = sum(1 for p in proposal.parties if p in consent.text)
            score += mentioned
            if score > best_score:
                best, best_score = commitment, score
        return best

    def maybe_lock(self, commitment):
        """相关方都同意、都允许锁时段、资料条件满足后才锁时段。"""
        if commitment.state != "confirming":
            return False
        proposal = commitment.proposal
        if not all(commitment.confirmations.values()):
            return False
        if not all(commitment.lock_ok.values()):
            commitment.note = "有成员要求先别锁时段"
            return False
        for ref in proposal.material_refs:
            problems = self._materials.check(
                ref, list(proposal.parties), proposal.purpose)
            if problems:
                commitment.questions.extend(problems)
                return False
        # 本提议在排班时的暂定占用先释放，再按实际容量锁定。
        self._scheduler.release_planned(proposal)
        if not self._scheduler.fits(proposal):
            commitment.state = "blocked"
            commitment.questions.append("时段容量已被其他承诺锁定")
            return False
        self._scheduler.consume_locked(proposal)
        proposal.state = "locked"
        commitment.state = "locked"
        return True

    # -- 撤回与改约 -------------------------------------------------------

    def withdraw_material(self, material_id, note=""):
        """撤回资料许可。返回受影响的承诺 id 列表。"""
        self._materials.withdraw(material_id, note=note)
        affected = []
        for commitment in self._commitments.values():
            proposal = commitment.proposal
            if material_id not in proposal.material_refs:
                continue  # 不依赖该资料的承诺不受影响
            if commitment.state == "confirming":
                # 待确认邀请中不得再带出该资料。
                self._invitations[commitment.id] = self._make_invitations(commitment)
                commitment.state = "blocked"
                commitment.questions.append("资料许可已撤回，待改约")
                affected.append(commitment.id)
            elif commitment.state == "locked":
                # 已约好的会面因承诺依赖该资料而受影响。
                commitment.state = "invalidated"
                commitment.note = note or "资料许可已撤回"
                proposal.state = "invalidated"
                self._scheduler.release_locked(proposal)  # 空位让给其他候选
                affected.append(commitment.id)
        return affected

    def renegotiate(self, commitment_id, new_proposal):
        """受影响的小组改成新约：旧承诺作废，新承诺须重新确认。"""
        old = self._commitments[commitment_id]
        if old.state not in {"invalidated", "blocked"}:
            raise ValueError("只有受影响的承诺才能改约")
        old.state = "superseded"
        new_proposal.state = "planned"
        new_proposal.questions = []
        self._counter += 1
        new_commitment = Commitment(
            id=f"C{self._counter}", proposal=new_proposal,
            confirmations={m: False for m in new_proposal.parties},
            lock_ok={m: True for m in new_proposal.parties})
        new_proposal.state = "confirming"
        self._commitments[new_commitment.id] = new_commitment
        self._invitations[new_commitment.id] = self._make_invitations(new_commitment)
        return new_commitment

    def confirm_directly(self, commitment_id, member, allow_lock=True):
        """新约的重新确认（成员看过自己有权看到的摘要后）。"""
        commitment = self._commitments[commitment_id]
        commitment.confirmations[member] = True
        commitment.lock_ok[member] = allow_lock
        return commitment

    def get(self, commitment_id):
        return self._commitments[commitment_id]

    def all(self):
        return dict(self._commitments)
