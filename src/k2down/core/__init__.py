"""ルールと提案の読み書き・判定インターフェース・利用ログ。

このパッケージは純粋なローカル処理のみで構成し、一切通信しない。
"""

from k2down.core.judge import Judge
from k2down.core.model import Proposal, Rule, RuleError
from k2down.core.report import build_report
from k2down.core.service import accept, add, decide, decline, escalate, find_rules, propose, record, replace, retire
from k2down.core.store import ProposalStore, RuleStore
from k2down.core.usage import UsageLog

__all__ = [
    "Judge",
    "Proposal",
    "ProposalStore",
    "Rule",
    "RuleError",
    "RuleStore",
    "UsageLog",
    "accept",
    "add",
    "build_report",
    "decide",
    "decline",
    "escalate",
    "find_rules",
    "propose",
    "record",
    "replace",
    "retire",
]
