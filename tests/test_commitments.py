"""承诺测试：分别申请确认、锁定条件、资料撤回、改约与空位让渡。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from exchange.commitments import CommitmentService
from exchange.confidentiality import ConfidentialityList
from exchange.matching import HelpEdge, Proposal
from exchange.materials import Material, MaterialRegistry
from exchange.models import MemberProfile, Offer, Capability, Visibility
from exchange.parsing import Consent
from exchange.scheduling import Availability, Scheduler, SessionInfo
from exchange.summaries import SummaryService


def make_env(with_material=True):
    materials = MaterialRegistry()
    if with_material:
        materials.register(Material(
            id="M1", name="演示材料", owner="第三方",
            audience={"甲", "乙"}, purpose="评审",
            prerequisite_sessions=["early"]))
    summaries = SummaryService(ConfidentialityList())
    for name in ("甲", "乙", "丙", "丁"):
        profile = MemberProfile(member=name)
        profile.offers.append(Offer(capability=Capability("贴标")))
        summaries.draft(profile)
        summaries.invite_confirm(name)
        summaries.confirm(name)
    sessions = {"early": SessionInfo(id="early", priority=1, who=["甲", "乙", "丙", "丁"]),
                "late": SessionInfo(id="late", priority=2, who=["甲", "乙", "丙", "丁"])}
    avail = [Availability(who=n, times=["early", "late"], max_sessions=1)
             for n in ("甲", "乙", "丙", "丁")]
    scheduler = Scheduler(sessions, avail, materials)
    service = CommitmentService(materials, summaries, scheduler)
    return materials, scheduler, service


def make_proposal(pid, session, parties, material_refs=()):
    proposal = Proposal(
        id=pid, kind="mutual" if len(parties) > 1 else "one_way",
        session=session, parties=tuple(parties),
        edges=[HelpEdge(giver=parties[0], receiver=parties[-1],
                        capability="贴标")],
        material_refs=list(material_refs), purpose="评审")
    proposal.state = "planned"
    return proposal


class ConfirmationFlowTest(unittest.TestCase):
    def setUp(self):
        self.materials, self.scheduler, self.service = make_env()

    def test_lock_requires_all_parties_and_material(self):
        """相关方都同意、材料条件满足后才锁时段。"""
        proposal = make_proposal("P1", "early", ["甲", "乙"], ["M1"])
        commitment = self.service.apply(proposal)
        self.service.confirm_directly(commitment.id, "甲")
        self.assertFalse(self.service.maybe_lock(commitment))  # 乙未确认
        self.service.confirm_directly(commitment.id, "乙")
        self.assertTrue(self.service.maybe_lock(commitment))
        self.assertEqual(commitment.state, "locked")
        self.assertEqual(self.scheduler.capacity_left("甲"), 0)  # 锁定才占时段

    def test_lock_refusal_keeps_confirming(self):
        proposal = make_proposal("P1", "early", ["甲", "乙"])
        commitment = self.service.apply(proposal)
        self.service.confirm_directly(commitment.id, "甲")
        self.service.confirm_directly(commitment.id, "乙", allow_lock=False)
        self.assertFalse(self.service.maybe_lock(commitment))
        self.assertEqual(commitment.state, "confirming")
        self.assertEqual(self.scheduler.capacity_left("甲"), 1)  # 未锁不占时段

    def test_apply_rejects_proposal_with_questions(self):
        proposal = make_proposal("P1", "early", ["甲", "乙"])
        proposal.questions.append("乙：时间待定")
        with self.assertRaises(ValueError):
            self.service.apply(proposal)

    def test_invitation_respects_material_audience(self):
        """邀请里的资料说明只给授权受众。"""
        proposal = make_proposal("P1", "early", ["甲", "丙"], ["M1"])
        # 丙不在 M1 受众内 → 申请前的核对应已拦住；这里直接看邀请生成。
        self.materials.get("M1").audience.add("丙")
        commitment = self.service.apply(proposal)
        invitation = self.service.invitation_for(commitment.id, "丙")
        self.assertTrue(any("演示材料" in n for n in invitation.material_notes))
        self.materials.get("M1").audience.discard("丙")
        invitations = self.service._make_invitations(commitment)
        self.assertEqual(invitations["丙"].material_notes, [])
        self.assertTrue(any("演示材料" in n
                            for n in invitations["甲"].material_notes))

    def test_consent_matching_by_session_and_mentions(self):
        proposal = make_proposal("P1", "early", ["甲", "乙"])
        commitment = self.service.apply(proposal)
        consent = Consent(who="乙", accepted_for="early",
                          text="我接受有甲帮忙的提议。")
        target = self.service.record_consent(consent)
        self.assertEqual(target.id, commitment.id)
        self.assertTrue(commitment.confirmations["乙"])


class WithdrawalTest(unittest.TestCase):
    def setUp(self):
        self.materials, self.scheduler, self.service = make_env()

    def lock_proposal(self, pid, session, parties, material_refs=()):
        proposal = make_proposal(pid, session, parties, material_refs)
        commitment = self.service.apply(proposal)
        for member in parties:
            self.service.confirm_directly(commitment.id, member)
        self.assertTrue(self.service.maybe_lock(commitment))
        return proposal, commitment

    def test_pending_invitation_drops_withdrawn_material(self):
        """待确认邀请中不得再带出已撤回的资料。"""
        proposal = make_proposal("P1", "early", ["甲", "乙"], ["M1"])
        commitment = self.service.apply(proposal)
        before = self.service.invitation_for(commitment.id, "甲")
        self.assertTrue(before.material_notes)
        self.service.withdraw_material("M1", note="所有方收回")
        after = self.service.invitation_for(commitment.id, "甲")
        self.assertEqual(after.material_notes, [])
        self.assertEqual(commitment.state, "blocked")  # 依赖该资料 → 待改约

    def test_locked_meeting_affected_only_if_dependent(self):
        """已约好的会面只有在承诺依赖该资料时才受影响。"""
        dependent, c_dep = self.lock_proposal("P1", "early", ["甲", "乙"], ["M1"])
        independent, c_ind = self.lock_proposal("P2", "late", ["丙", "丁"])
        affected = self.service.withdraw_material("M1")
        self.assertEqual(affected, [c_dep.id])
        self.assertEqual(c_dep.state, "invalidated")
        self.assertEqual(c_ind.state, "locked")  # 不依赖 → 不受影响

    def test_freed_slot_goes_to_other_candidates(self):
        """失效承诺空下的名额交给其他候选。"""
        _, c_dep = self.lock_proposal("P1", "early", ["甲", "乙"], ["M1"])
        self.assertEqual(self.scheduler.capacity_left("乙"), 0)
        self.service.withdraw_material("M1")
        self.assertEqual(self.scheduler.capacity_left("乙"), 1)  # 空位释放
        rival = make_proposal("P3", "late", ["乙", "丙"])
        planned, _ = self.scheduler.replan([rival])
        self.assertEqual([p.id for p in planned], ["P3"])

    def test_renegotiation_requires_fresh_confirmation(self):
        """改约须重新确认，不能沿用旧承诺的同意。"""
        _, c_dep = self.lock_proposal("P1", "early", ["甲", "乙"], ["M1"])
        self.service.withdraw_material("M1")
        new_proposal = make_proposal("P1'", "early", ["甲", "乙"])
        new_commitment = self.service.renegotiate(c_dep.id, new_proposal)
        self.assertEqual(c_dep.state, "superseded")
        self.assertFalse(self.service.maybe_lock(new_commitment))  # 无人确认
        self.service.confirm_directly(new_commitment.id, "甲")
        self.service.confirm_directly(new_commitment.id, "乙")
        self.assertTrue(self.service.maybe_lock(new_commitment))
        self.assertEqual(new_commitment.state, "locked")

    def test_independent_pending_commitment_untouched(self):
        """不依赖该资料的待确认承诺，撤回后照常。"""
        proposal = make_proposal("P1", "late", ["乙", "丙"])
        commitment = self.service.apply(proposal)
        self.service.withdraw_material("M1")
        self.assertEqual(commitment.state, "confirming")


if __name__ == "__main__":
    unittest.main()
