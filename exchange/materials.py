"""第三方资料授权登记与撤回。

资料的授权只对指定受众和用途有效，不能把承诺当作无条件供给。
撤回时：待确认邀请中不得再带出该资料；已经约好的会面只有在
承诺依赖该资料时才受影响。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Material:
    """一份第三方资料及其授权范围。"""

    id: str
    name: str
    owner: str
    audience: set = field(default_factory=set)   # 指定受众
    purpose: str = ""                            # 指定用途
    public_ok: bool = False
    denied: set = field(default_factory=set)     # 被明确排除的人
    prerequisite_sessions: list = field(default_factory=list)  # 指定的先行场次
    withdrawn: bool = False
    withdrawal_note: str = ""


class MaterialRegistry:
    """登记、核对、撤回资料授权。"""

    def __init__(self):
        self._materials = {}

    def register(self, material):
        self._materials[material.id] = material
        return material

    def get(self, material_id):
        return self._materials[material_id]

    def by_name(self, name):
        for material in self._materials.values():
            if material.name == name:
                return material
        return None

    def all(self):
        return dict(self._materials)

    def apply_grant(self, name, audience, purpose, owner=""):
        """把留言中声明的授权并入登记（不存在则新建）。"""
        material = self.by_name(name)
        if material is None:
            material = Material(id=f"M-{name}", name=name, owner=owner)
            self.register(material)
        material.audience |= set(audience)
        if purpose:
            material.purpose = purpose
        if owner:
            material.owner = owner
        return material

    def apply_denial(self, name, party):
        material = self.by_name(name)
        if material is not None:
            material.denied.add(party)
            material.audience.discard(party)
        return material

    def withdraw(self, material_id, note=""):
        material = self._materials[material_id]
        material.withdrawn = True
        material.withdrawal_note = note
        return material

    def check(self, material_id, viewers, purpose):
        """核对一次使用是否合法，返回问题列表（空列表 = 可用）。

        授权只对指定受众和用途有效；已撤回的资料一律不可用。
        """
        material = self._materials.get(material_id)
        if material is None:
            return [f"资料 {material_id} 未登记，授权范围未知"]
        problems = []
        if material.withdrawn:
            problems.append(f"资料《{material.name}》的使用许可已被{material.owner}撤回")
            return problems
        for viewer in viewers:
            if viewer in material.denied:
                problems.append(f"{viewer} 被明确排除在《{material.name}》授权之外")
            elif material.audience and viewer not in material.audience:
                problems.append(f"{viewer} 不在《{material.name}》的指定受众内")
        if material.purpose and purpose and material.purpose != purpose:
            problems.append(
                f"《{material.name}》用途限{material.purpose}，与{purpose}不符")
        return problems
