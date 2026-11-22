"""端到端管线：按时间线处理成员留言、回执、澄清与撤回。

处理顺序由 timeline 资料给出，同组 refs 在意见收齐后一起处理：
- B1 成员留言 → 档案、摘要、公告、候选、排班；
- B2 邀请回条 → 分别申请确认、登记确认、满足后锁时段；
- B3 澄清 → 并入档案，更新待问；
- B4 资料撤回 → 待确认邀请剔除资料、依赖该资料的已约会面失效、
  空位交回排班、受影响小组改约并重新确认。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .commitments import CommitmentService
from .confidentiality import ConfidentialityList
from .explain import ExplainService
from .matching import Matcher, Proposal, HelpEdge
from .materials import Material, MaterialRegistry
from .parsing import MessageParser, ProfileBuilder
from .registration import RegistrationBook
from .scheduling import Availability, Scheduler, SessionInfo
from .summaries import SummaryService


@dataclass
class PipelineResult:
    profiles: dict = field(default_factory=dict)
    proposals: list = field(default_factory=list)
    announcement: str = ""
    events: list = field(default_factory=list)
    explanations: dict = field(default_factory=dict)
    summaries: object = None
    materials: object = None
    commitments: object = None
    scheduler: object = None
    registrations: object = None
    leads: list = field(default_factory=list)


def _load(data_dir):
    tables = {}
    for name in ("messages", "resources", "consents", "timeline"):
        path = Path(data_dir) / f"{name}.json"
        tables[name] = {row["id"]: row for row in
                        json.loads(path.read_text(encoding="utf-8"))}
    return tables


def run_pipeline(data_dir):
    tables = _load(data_dir)
    result = PipelineResult()
    events = result.events

    # -- 排班与保密资料 ----------------------------------------------------
    sessions = {}
    session_infos = {}
    availabilities = []
    materials = MaterialRegistry()
    for row in tables["resources"].values():
        kind = row.get("kind")
        if kind == "session":
            sessions[row["id"]] = {"priority": row["priority"], "who": row["who"]}
            session_infos[row["id"]] = SessionInfo(
                id=row["id"], priority=row["priority"], who=list(row["who"]))
        elif kind == "availability":
            availabilities.append(Availability(
                who=row["who"], times=list(row["times"]),
                max_sessions=row["max_sessions"]))
        elif kind == "private_attachment":
            materials.register(Material(
                id=row["id"], name=row["about"], owner=row["owner"],
                audience=set(row["access"]), purpose=row["purpose"]))
    confidentiality = ConfidentialityList.from_resources(
        list(tables["resources"].values()))
    result.materials = materials

    parser = MessageParser(
        sessions={s: i["priority"] for s, i in sessions.items()},
        sensitive_terms=sorted(confidentiality.terms))
    builder = ProfileBuilder(parser)
    summaries = SummaryService(confidentiality)
    registrations = RegistrationBook()
    scheduler = Scheduler(session_infos, availabilities, materials)
    commitments = CommitmentService(materials, summaries, scheduler)
    explain = ExplainService(materials, confidentiality)
    result.summaries = summaries
    result.scheduler = scheduler
    result.commitments = commitments
    result.registrations = registrations

    timeline = sorted(tables["timeline"].values(), key=lambda e: e["order"])
    proposals = []

    def ingest(msg_ids):
        for msg_id in msg_ids:
            row = tables["messages"][msg_id]
            parsed = builder.add(row["who"], row["text"], msg_id=msg_id)
            events.append(f"解析 {msg_id}（{row['who']}）："
                          f"供给{len(parsed.offers)} 需求{len(parsed.needs)} "
                          f"否定{len(parsed.non_offers)} 转述{len(parsed.reported_leads)} "
                          f"条件{len(parsed.conditions)} 许可{len(parsed.permissions)}")
            for grant in parsed.grants:
                materials.apply_grant(grant.material, grant.audience,
                                      grant.purpose, owner=row["who"])
                events.append(f"登记资料授权：《{grant.material}》受众"
                              f"{'、'.join(sorted(grant.audience))}，用途{grant.purpose}")
            for denial in parsed.denials:
                materials.apply_denial(denial.target, next(iter(denial.parties)))
            for session in parsed.sessions:
                registrations.record(row["who"], session)
                events.append(f"报名：{row['who']} → {session}（报名表只存代号与场次）")
            for withdrawal in parsed.withdrawals:
                material = materials.by_name(withdrawal.material)
                if material is not None:
                    affected = commitments.withdraw_material(
                        material.id, note=withdrawal.note)
                    events.append(f"撤回资料《{material.name}》；受影响承诺："
                                  f"{affected or '无'}；{withdrawal.note}")
        return msg_ids

    for event in timeline:
        refs = event["refs"]
        if refs[0].startswith("N"):
            ingest(refs)
        else:  # 回条组
            for ref in refs:
                row = tables["consents"][ref]
                consent = parser.parse_consent(
                    row["who"], row["accepted_for"], row["text"])
                target = commitments.record_consent(consent)
                if target is not None:
                    events.append(f"登记回条 {ref}（{row['who']} → {target.id}）")

        # 每个时间线节点处理后，推进一次匹配/排班/确认。
        if event["id"] == "B1":
            profiles = builder.profiles()
            result.profiles = profiles
            for member in profiles:
                summaries.draft(profiles[member])
                summaries.invite_confirm(member)
                summaries.confirm(member)
            result.announcement = summaries.announcement()
            events.append(f"公共公告：{result.announcement or '（无允许公开的内容）'}")

            matcher = Matcher(profiles, materials, sessions=sessions)
            proposals = matcher.generate()
            result.proposals = proposals
            result.leads = matcher.leads
            planned, skipped = scheduler.plan(proposals)
            events.append(f"候选提议：{[p.id for p in proposals]}；"
                          f"已排：{[p.id for p in planned]}；"
                          f"待问：{scheduler.pending_questions(proposals) or '无'}")
            for proposal in scheduler.appliable(proposals):
                commitment = commitments.apply(proposal)
                events.append(f"分别申请确认：{proposal.id} → {commitment.id}")

        elif event["id"] == "B2":
            for commitment in commitments.all().values():
                if commitments.maybe_lock(commitment):
                    events.append(f"{commitment.id} 相关方同意且资料条件满足，"
                                  f"锁定时段（{commitment.proposal.session}）")
                elif commitment.state == "confirming":
                    events.append(f"{commitment.id} 待确认："
                                  f"{explain.lock_pending(commitment).internal}")

        elif event["id"] == "B3":
            # 澄清并入档案后，把新的未知条件反映到待确认承诺上。
            for commitment in commitments.all().values():
                if commitment.state != "confirming":
                    continue
                for member in commitment.parties():
                    for cond in result.profiles[member].open_conditions(
                            kinds={"lock"}):
                        note = f"{member}：{cond.text}"
                        if note not in commitment.questions:
                            commitment.questions.append(note)
                        commitment.lock_ok[member] = False
                        events.append(f"{commitment.id} 新增待问：{note}")

        elif event["id"] == "B4":
            # 撤回已在 ingest 中处理；这里为受影响小组改约并重新确认。
            for commitment in list(commitments.all().values()):
                if commitment.state != "invalidated":
                    continue
                old = commitment.proposal
                new_proposal = Proposal(
                    id=old.id + "'", kind=old.kind, session=old.session,
                    parties=old.parties,
                    edges=[HelpEdge(giver=e.giver, receiver=e.receiver,
                                    capability=e.capability)
                           for e in old.edges],
                    support_offers=list(old.support_offers),
                    material_refs=[], purpose=old.purpose)
                new_commitment = commitments.renegotiate(
                    commitment.id, new_proposal)
                events.append(f"{commitment.id} 改约为 {new_commitment.id}"
                              "（不再依赖已撤回资料，须重新确认）")
                for member in new_proposal.parties:
                    commitments.confirm_directly(new_commitment.id, member)
                if commitments.maybe_lock(new_commitment):
                    events.append(f"{new_commitment.id} 双方重新确认，锁定时段")

    # -- 解释：一边看得到、另一边暂时看不到 -------------------------------
    mozhou_inquiry = None
    for profile in result.profiles.values():
        for inquiry in profile.inquiries:
            mozhou_inquiry = inquiry
    if mozhou_inquiry is not None:
        result.explanations["inquiry"] = explain.inquiry(mozhou_inquiry)
    r2 = materials.by_name("定位图")
    if r2 is not None:
        result.explanations["material_墨舟"] = explain.material_access("墨舟", r2.id)
        result.explanations["material_橙子"] = explain.material_access("橙子", r2.id)
    for commitment in commitments.all().values():
        if commitment.state == "confirming":
            result.explanations[f"lock_{commitment.id}"] = \
                explain.lock_pending(commitment)

    return result
