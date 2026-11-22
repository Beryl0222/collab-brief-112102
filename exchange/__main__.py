"""演示：python3 -m exchange [数据目录]

按时间线处理 data/ 下的留言、回执与撤回，打印每一步的处理结果。
"""
from __future__ import annotations

import sys
from pathlib import Path

from .pipeline import run_pipeline


def main(argv):
    data_dir = Path(argv[1]) if len(argv) > 1 else Path(__file__).parents[1] / "data"
    result = run_pipeline(data_dir)

    print("== 处理经过 ==")
    for event in result.events:
        print(" -", event)

    print("\n== 公共公告（只含允许公开且组合安全的内容）==")
    print(result.announcement or "（无）")

    print("\n== 待联络人核实的转述线索 ==")
    for lead in result.leads:
        print(" -", lead)

    print("\n== 可见性差异的解释（内部 / 公开）==")
    for key, explanation in result.explanations.items():
        print(f" - [{key}] 内部：{explanation.internal}")
        print(f"   {' ' * len(key)} 公开：{explanation.public}")

    print("\n== 承诺终态 ==")
    for commitment in result.commitments.all().values():
        proposal = commitment.proposal
        print(f" - {commitment.id}（{proposal.id}，{proposal.kind}，"
              f"{'/'.join(proposal.parties)}，场次 {proposal.session}）："
              f"{commitment.state} {commitment.note or ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
