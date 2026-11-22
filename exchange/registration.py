"""报名表：只存项目代号与场次，不存留言原文。"""
from __future__ import annotations


class RegistrationBook:
    """报名记录只保留 (代号, 场次) 两个字段。"""

    FIELDS = ("codename", "session")

    def __init__(self):
        self._rows = []

    def record(self, codename, session):
        row = {"codename": codename, "session": session}
        self._rows.append(row)
        return row

    def rows(self):
        return [dict(r) for r in self._rows]

    def sessions_of(self, codename):
        return [r["session"] for r in self._rows if r["codename"] == codename]
