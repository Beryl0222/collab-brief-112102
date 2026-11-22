"""成员原始留言与澄清的解析。

规则式解析：按标点分句后逐句归类。能识别：

- 转述（“我转述……说”“听说”）：记为线索，不算本人供给；
- 否定（“不做”“没法”“别公开”）：记为明确不供给或拒绝许可；
- 附条件（“前提是”“得等……后”“还没同意”）：挂在对应供给/需求上；
- 同一条留言里同时出现的供给与需求；
- 随后到来的澄清：并入档案，许可类规则以最新一条为准。

词表（能力、资料别名、场次别名）集中在模块常量，社区可按需扩充。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import (
    Capability,
    Condition,
    ExchangeWish,
    Inquiry,
    MemberProfile,
    Need,
    NonOffer,
    Offer,
    PermissionRule,
    Visibility,
)

# 能力词表：键是归一化能力名，值是口语说法（匹配时长的优先）。
CAPABILITY_LEXICON = {
    "温区标定": ["冷柜温区标定", "温区标定", "教标定", "标定", "冷柜", "温区"],
    "视觉设计": ["虚拟货架的配色原型", "配色原型", "交互图", "配色"],
    "贴标": ["贴标"],
    "样品": ["样品"],
}

# 资料别名。“图”单字易误中“交互图”，用否定后顾排除。
MATERIAL_ALIASES = {
    "定位图": ["定位图", r"(?<!交互)(?<!定位)图"],
}

# 场次别名：报名口语 → 场次选择方式。
SESSION_ALIASES = {"先行场": "first_priority", "早场": "first_priority"}

_NEGATION = ("不做", "没法", "不能", "不会", "没有", "不接", "不帮")
_CLAUSE_SPLIT = re.compile(r"[，。；！？\n]+")
_NAME_SPLIT = re.compile(r"[或和、]")


@dataclass
class MaterialGrant:
    """留言中声明的资料授权（指定受众与用途）。"""

    material: str
    audience: set = field(default_factory=set)
    purpose: str = ""
    scope: str = ""
    text: str = ""


@dataclass
class Withdrawal:
    """留言中声明的资料撤回。"""

    material: str
    text: str = ""
    note: str = ""


@dataclass
class Consent:
    """邀请回条：确认某场次的提议，可附锁时段意愿与新的许可规则。"""

    who: str
    accepted_for: str
    confirms: bool = True
    allow_lock: bool = True
    permissions: list = field(default_factory=list)
    capabilities: set = field(default_factory=set)
    text: str = ""


@dataclass
class ParsedMessage:
    """一条留言的解析结果。"""

    who: str
    msg_id: str
    offers: list = field(default_factory=list)
    needs: list = field(default_factory=list)
    non_offers: list = field(default_factory=list)
    permissions: list = field(default_factory=list)
    exchanges: list = field(default_factory=list)
    conditions: list = field(default_factory=list)
    reported_leads: list = field(default_factory=list)
    attributes: dict = field(default_factory=dict)
    attribute_visibility: dict = field(default_factory=dict)
    inquiries: list = field(default_factory=list)
    sessions: list = field(default_factory=list)
    grants: list = field(default_factory=list)
    denials: list = field(default_factory=list)   # list[PermissionRule]
    withdrawals: list = field(default_factory=list)


class MessageParser:
    """把成员口语留言解析为结构化声明。"""

    def __init__(self, sessions=None, sensitive_terms=None):
        # sessions: {场次id: 优先级}，用于把“先行场”映射到优先级最高的场次。
        self._sessions = sessions or {}
        # 保密词表中的敏感词，用于识别涉私打听。
        self._sensitive = list(sensitive_terms or [])

    # -- 词表工具 ---------------------------------------------------------

    @staticmethod
    def _capabilities_in(text):
        """按词表找出文中提到的能力，长说法优先，避免重复。"""
        found = []
        for key, surfaces in CAPABILITY_LEXICON.items():
            for surface in sorted(surfaces, key=len, reverse=True):
                if surface in text:
                    found.append(Capability(key=key, surface=surface))
                    break
        return found

    @staticmethod
    def _capability_one(text):
        caps = MessageParser._capabilities_in(text)
        return caps[0] if caps else None

    @staticmethod
    def _materials_in(text):
        found = []
        for name, aliases in MATERIAL_ALIASES.items():
            for alias in aliases:
                if re.search(alias, text):
                    found.append(name)
                    break
        return found

    def _session_of(self, word):
        alias = SESSION_ALIASES.get(word)
        if alias == "first_priority":
            if self._sessions:
                return min(self._sessions, key=lambda s: self._sessions[s])
            return word
        return word

    # -- 主入口 -----------------------------------------------------------

    def parse(self, who, text, msg_id=""):
        parsed = ParsedMessage(who=who, msg_id=msg_id)
        current_material = None   # 跨分句的资料上下文（“定位图……不给墨舟”）
        current_capability = None  # 跨分句的能力上下文（“带过标定，我能教一场”）
        last_exchange = None

        for clause in _CLAUSE_SPLIT.split(text):
            clause = clause.strip()
            if not clause:
                continue

            # 1. 涉私打听：只记录，绝不公开回答。
            if re.search(r"能不能告诉|可以告诉|是不是.+那间", clause):
                terms = [t for t in self._sensitive if t in clause]
                parsed.inquiries.append(Inquiry(text=clause, terms=terms))
                continue

            # 2. 资料撤回。
            if "收回" in clause or "不再给" in clause:
                mats = self._materials_in(clause)
                if not mats and parsed.withdrawals:
                    # 承前一句的撤回对象（“收回……的图，不再给任何人用”）。
                    parsed.withdrawals[-1].text += "；" + clause
                else:
                    parsed.withdrawals.append(Withdrawal(
                        material=mats[0] if mats else (current_material or ""),
                        text=clause))
                continue
            if "已约好的事" in clause and parsed.withdrawals:
                parsed.withdrawals[-1].note = clause
                continue

            # 3. 资料授权：“X同意给A和B在本组做某用”。
            grant = re.search(r"同意给(?P<aud>[\w、和]+?)在(?P<rest>\S+)用", clause)
            if grant:
                mats = self._materials_in(clause)
                material = mats[0] if mats else (current_material or "")
                current_material = material or current_material
                audience = {n for n in _NAME_SPLIT.split(grant.group("aud")) if n}
                rest = grant.group("rest")
                scope = "本组" if "本组" in rest else ("组内" if "组内" in rest else "")
                cap = self._capability_one(rest)
                parsed.grants.append(MaterialGrant(
                    material=material, audience=audience,
                    purpose=cap.key if cap else rest, scope=scope, text=clause))
                continue

            # 4. 许可规则。
            deny_use = re.search(r"(?:先)?(?:别|不要)用(?P<what>.+)", clause)
            deny_public = re.search(r"(?:别|不要|不能)公开(?P<what>.+)", clause)
            codename = re.search(r"(?P<name>\w+)这个商品代号", clause)
            if deny_public or codename:
                if codename:
                    name = re.sub(r"^(?:先)?(?:别|不要|不能)?(?:公开|用|说|叫)",
                                  "", codename.group("name"))
                    parsed.attributes["商品代号"] = name
                    parsed.attribute_visibility["商品代号"] = Visibility.CONTACT
                    parsed.permissions.append(PermissionRule(
                        target=name, allowed=False, text=clause))
                else:
                    what = deny_public.group("what")
                    parsed.permissions.append(PermissionRule(
                        target=what, allowed=False, text=clause))
                continue
            if deny_use:
                parsed.permissions.append(PermissionRule(
                    target=deny_use.group("what"), allowed=False, text=clause))
                continue
            deny_see = re.search(r"(?:别|不要)让(?P<party>\w+)看到(?P<what>\w+)", clause)
            if deny_see:
                rule = PermissionRule(
                    target=deny_see.group("what"), allowed=False,
                    parties=frozenset({deny_see.group("party")}), text=clause)
                parsed.permissions.append(rule)
                # 该附条件由许可规则落实，记为已满足而非待问。
                parsed.conditions.append(Condition(
                    text=clause, kind="generic", status="satisfied"))
                continue
            alone_ok = re.search(r"单说(?P<what>\w+)可以", clause)
            if alone_ok:
                what = alone_ok.group("what")
                parsed.permissions.append(PermissionRule(
                    target=what, allowed=True,
                    visibility=Visibility.PUBLIC, text=clause))
                continue
            combo_ban = re.search(r"不能和(?P<other>\w+)一起说", clause)
            if combo_ban:
                parsed.permissions.append(PermissionRule(
                    target=combo_ban.group("other"), allowed=False,
                    text=clause))
                continue
            if "不做公开" in clause or "不公开讲解" in clause:
                parsed.permissions.append(PermissionRule(
                    target=current_material or "公开", allowed=False, text=clause))
                continue
            deny_party = re.search(r"不给(?P<who>\w+)$", clause)
            if deny_party and current_material:
                parsed.denials.append(PermissionRule(
                    target=current_material, allowed=False,
                    parties=frozenset({deny_party.group("who")}), text=clause))
                continue
            if "转发" in clause and ("不同意" in clause or "别" in clause):
                parsed.permissions.append(PermissionRule(
                    target="资料", allowed=False,
                    parties=frozenset({"别人"}), text=clause))
                continue
            if "互看摘要" in clause or "看允许的摘要" in clause:
                parsed.permissions.append(PermissionRule(
                    target="摘要", allowed=True,
                    visibility=Visibility.MATCHED, text=clause))
                continue

            # 5. 锁时段意愿（未知条件，不得当作已同意）。
            if "锁时段" in clause or "先别锁" in clause or "别锁" in clause:
                parsed.conditions.append(Condition(
                    text=clause, kind="lock", status="unknown"))
                continue

            # 6. 报名场次。
            signup = re.search(r"报名(?P<session>\w+)", clause)
            if signup:
                parsed.sessions.append(self._session_of(signup.group("session")))
                continue

            # 7. 交换条件。
            want = re.search(r"希望换(?P<what>.+)", clause)
            if want:
                cap = self._capability_one(want.group("what"))
                last_exchange = ExchangeWish(want=cap, text=clause)
                parsed.exchanges.append(last_exchange)
                continue
            only_counter = re.search(r"只想和会(?P<cap>.+?)的人交换", clause)
            if only_counter:
                cap = self._capability_one(only_counter.group("cap"))
                last_exchange = ExchangeWish(
                    want=cap, require_counter=cap, text=clause)
                parsed.exchanges.append(last_exchange)
                continue
            if "一个时段内" in clause:
                if last_exchange is not None:
                    last_exchange.one_slot = True
                else:
                    parsed.conditions.append(Condition(text=clause, kind="generic"))
                continue

            # 8. 转述：记为线索，不算本人供给。
            reported = re.search(r"转述(?P<from>.+?)说", clause)
            if reported or "听说" in clause:
                cap = self._capability_one(clause)
                if cap is not None:
                    parsed.reported_leads.append(Offer(
                        capability=cap, source="reported",
                        reported_from=reported.group("from") if reported else "",
                        note=clause))
                continue

            # 9. 附条件：“前提是……”“得等……后”。
            premise = re.search(r"前提是(?P<what>.+)", clause)
            if premise:
                inner = premise.group("what")
                mats = self._materials_in(inner)
                if mats:
                    owner = re.search(r"(?P<owner>\w+)的" + mats[0], inner)
                    parsed.conditions.append(Condition(
                        text=clause, kind="material", ref=mats[0],
                        status="unknown"))
                    if owner:
                        parsed.attributes.setdefault("资料所有方", owner.group("owner"))
                else:
                    parsed.conditions.append(Condition(text=clause, kind="generic"))
                continue
            if clause.startswith("若") or "得等" in clause:
                kind = "fallback" if clause.startswith("若") else "timing"
                parsed.conditions.append(Condition(text=clause, kind=kind))
                continue

            # 10. 否定声明：明确不做的事。
            if any(neg in clause for neg in _NEGATION):
                cap = self._capability_one(clause)
                if cap is not None:
                    parsed.non_offers.append(NonOffer(capability=cap, text=clause))
                    current_capability = cap
                    continue

            # 11. 需求：“接受A或B帮我做某事”“需要……”。
            accept = re.search(r"接受(?P<who>[\w或和、]+?)帮我(?P<what>\w+)", clause)
            if accept:
                cap = self._capability_one(accept.group("what"))
                names = {n for n in _NAME_SPLIT.split(accept.group("who")) if n}
                if cap is not None:
                    parsed.needs.append(Need(
                        capability=cap, accept_from=frozenset(names), note=clause))
                    current_capability = cap
                    continue
            if any(m in clause for m in ("需要", "想找", "希望有", "缺")):
                cap = self._capability_one(clause)
                if cap is None:
                    want = re.search(r"(?:需要|想找|希望有|缺)(?P<what>\S+)", clause)
                    if want:
                        cap = Capability(key=want.group("what"),
                                         surface=want.group("what"))
                if cap is not None:
                    parsed.needs.append(Need(capability=cap, note=clause))
                    current_capability = cap
                    continue

            # 12. 供给：“我能/可以/给/教/带过/帮……”。
            cap = self._capability_one(clause)
            fallback = re.search(
                r"(?:可以帮|能帮|我可以|我能|我会|擅长|做过|干过|带过)(?P<what>\S+)",
                clause)
            if cap is None and fallback:
                what = fallback.group("what")
                # “我能教一场”这类数量短语承前句能力；否则按词表外能力收录。
                if not re.fullmatch(r"\S{0,2}[一二两]\S{0,2}", what):
                    cap = Capability(key=what, surface=what)
            if cap is None:
                cap = current_capability
            else:
                current_capability = cap
            if cap is not None and any(
                    m in clause for m in ("能", "可以", "给", "教", "带过", "擅长", "帮", "做过")):
                purpose = re.search(r"供(?P<purpose>\w+)", clause)
                note = purpose.group("purpose") if purpose else clause
                existing = next((o for o in parsed.offers
                                 if o.capability.key == cap.key), None)
                if existing is None:
                    parsed.offers.append(Offer(capability=cap, note=note))
                else:
                    existing.note = note

        return parsed

    def parse_consent(self, who, accepted_for, text):
        """解析邀请回条：确认意愿、是否允许锁时段、附加许可。"""
        consent = Consent(who=who, accepted_for=accepted_for, text=text)
        if re.search(r"先别锁|别锁|还没同意锁", text):
            consent.allow_lock = False
        if not re.search(r"接受|愿意|可以|同意", text):
            consent.confirms = False
        if "转发" in text and "不同意" in text:
            consent.permissions.append(PermissionRule(
                target="资料", allowed=False,
                parties=frozenset({"别人"}), text=text))
        if "互看摘要" in text or "看允许的摘要" in text:
            consent.permissions.append(PermissionRule(
                target="摘要", allowed=True,
                visibility=Visibility.MATCHED, text=text))
        consent.capabilities = {
            c.key for c in self._capabilities_in(text)}
        return consent


class ProfileBuilder:
    """把成员的原始留言与随后的澄清逐条合并为档案。"""

    def __init__(self, parser):
        self._parser = parser
        self._profiles = {}
        self.parsed = []          # 所有已解析留言（含转述线索、撤回等）
        self.grants = []
        self.denials = []
        self.withdrawals = []

    def add(self, who, text, msg_id=""):
        parsed = self._parser.parse(who, text, msg_id)
        self.parsed.append(parsed)
        self.grants.extend(parsed.grants)
        self.denials.extend(parsed.denials)
        self.withdrawals.extend(parsed.withdrawals)

        profile = self._profiles.setdefault(who, MemberProfile(member=who))
        profile.raw.append(text)
        for offer in parsed.offers:
            existing = profile.offer_for(offer.capability.key)
            if existing is None:
                profile.offers.append(offer)
            else:  # 同一能力的补充说法并入既有供给
                existing.conditions.extend(offer.conditions)
                if offer.note:
                    existing.note = offer.note
        profile.needs.extend(parsed.needs)
        profile.non_offers.extend(parsed.non_offers)
        profile.permissions.extend(parsed.permissions)
        profile.exchanges.extend(parsed.exchanges)
        profile.reported_leads.extend(parsed.reported_leads)
        profile.attributes.update(parsed.attributes)
        profile.attribute_visibility.update(parsed.attribute_visibility)
        profile.inquiries.extend(parsed.inquiries)
        for session in parsed.sessions:
            if session not in profile.sessions:
                profile.sessions.append(session)
        for cond in parsed.conditions:
            # 同类成员级条件以最新澄清为准（如锁时段意愿）。
            profile.conditions = [
                c for c in profile.conditions
                if not (c.kind == cond.kind == "lock")]
            profile.conditions.append(cond)
        return parsed

    def profiles(self):
        return dict(self._profiles)
