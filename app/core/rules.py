"""RuleEngine：只回答“这些事实是否触发本项目资格否决条款”（任务书 §4/§5/§6）。

硬规则：
- FAIL 必须有 A/B 级证据支持；仅 C/D 线索 → UNKNOWN（任务书 §8）；
- 历史处罚/历史禁入已解除 → WARNING，不按当前状态否决；
- “其他丧失履约能力”不得由机器扩大解释 → 一律 MANUAL 转人工；
- 普通罚款不自动等于 FAIL。
"""
from __future__ import annotations

from datetime import date

from .evidence import can_support_fail
from .matching import UNCONFIRMED
from .models import Company, Finding, Project, RuleResult
from .status import Status, combine_decision


def effective_on(start: date | None, end: date | None, base: date) -> bool:
    """以核查基准日判断处罚/禁入是否仍在有效期（start/end 为空表示不限）。"""
    return (start is None or start <= base) and (end is None or end >= base)


def _fail_or_unknown(cands: list[Finding], reasons: list[str]) -> Status:
    if can_support_fail([c.grade for c in cands]):
        reasons.append("存在 A/B 级官方证据支持否决")
        return Status.FAIL
    reasons.append("仅有 C/D 级线索，不得单独作 FAIL，需 A/B 级证据闭环")
    return Status.UNKNOWN


def _done(rule_id: str, title: str, statuses, reasons, company) -> RuleResult:
    return RuleResult(
        rule_id=rule_id,
        title=title,
        status=combine_decision(statuses).value,
        reasons=reasons,
        company=company.name if company else None,
    )


class BidRestrictionRule:
    """条款1：被省级以上行业主管部门暂停/取消投标资格。普通罚款不在此列。"""

    id = "rule_bid_restriction"
    title = "被省级以上主管部门限制投标/采购活动"

    def evaluate(self, findings, project: Project, company: Company | None = None) -> RuleResult:
        base = project.base_date
        rel = [f for f in findings if f.kind == "penalty_bid_restriction"]
        if not rel:
            return _done(self.id, self.title, [], ["未检索到限制投标类处罚记录"], company)
        statuses: list[Status] = []
        reasons: list[str] = []
        for f in rel:
            level = f.attrs.get("authority_level", "city")
            if effective_on(f.start_date, f.end_date, base):
                if level in ("province", "national"):
                    reasons.append(f"[{f.source_id}] 省级以上限制投标且在有效期内：{f.description}")
                    statuses.append(_fail_or_unknown([f], reasons))
                else:
                    reasons.append(
                        f"[{f.source_id}] 限制机关层级为 {level}，未达省级以上，不自动否决"
                    )
                    statuses.append(Status.WARNING)
            else:
                reasons.append(f"[{f.source_id}] 处罚截至基准日已解除，仅作历史提示：{f.description}")
                statuses.append(Status.WARNING)
        return _done(self.id, self.title, statuses, reasons, company)


class BusinessStatusRule:
    """条款2：当前处于责令停产停业/证照暂扣吊销状态。关键词是“当前处于”。"""

    id = "rule_business_status"
    title = "当前处于停产停业或证照吊销/暂扣状态"
    REVOCATIONS = {
        "责令停产停业",
        "暂扣营业执照",
        "吊销营业执照",
        "暂扣许可证",
        "吊销许可证",
        "吊销资质证书",
    }

    def evaluate(self, findings, project: Project, company: Company | None = None) -> RuleResult:
        rel = [f for f in findings if f.kind == "penalty_business"]
        if not rel:
            return _done(self.id, self.title, [], ["未检索到停产停业/证照状态记录"], company)
        statuses: list[Status] = []
        reasons: list[str] = []
        for f in rel:
            state = f.attrs.get("status", "")
            if f.attrs.get("current") and state in self.REVOCATIONS:
                reasons.append(f"[{f.source_id}] 当前处于「{state}」：{f.description}")
                statuses.append(_fail_or_unknown([f], reasons))
            elif f.attrs.get("current"):
                reasons.append(f"[{f.source_id}] 当前状态「{state}」不在否决清单内，仅提示")
                statuses.append(Status.WARNING)
            else:
                reasons.append(f"[{f.source_id}] 历史「{state}」已解除，不按当前状态否决")
                statuses.append(Status.WARNING)
        return _done(self.id, self.title, statuses, reasons, company)


class BankruptcyRule:
    """条款3：当前进入清算程序/被宣告破产。“其他丧失履约能力”一律转人工。"""

    id = "rule_bankruptcy"
    title = "进入清算程序或被宣告破产"

    def evaluate(self, findings, project: Project, company: Company | None = None) -> RuleResult:
        statuses: list[Status] = []
        reasons: list[str] = []
        hit = False
        for f in findings:
            if f.kind == "bankruptcy_status":
                hit = True
                if f.attrs.get("current") and f.attrs.get("state") in ("清算程序", "宣告破产"):
                    reasons.append(f"[{f.source_id}] 当前「{f.attrs.get('state')}」：{f.description}")
                    statuses.append(_fail_or_unknown([f], reasons))
                else:
                    reasons.append(f"[{f.source_id}] 破产/清算信息非当前有效状态，仅提示")
                    statuses.append(Status.WARNING)
            elif f.kind == "loss_of_capacity_other":
                hit = True
                reasons.append(
                    f"[{f.source_id}] “其他丧失履约能力”不得由机器扩大解释，转人工判断：{f.description}"
                )
                statuses.append(Status.MANUAL)
        if not hit:
            return _done(self.id, self.title, [], ["未检索到破产/清算记录"], company)
        return _done(self.id, self.title, statuses, reasons, company)


class OwnerBanRule:
    """条款4：被纳入招标人集团受限/禁入供应商且仍在有效期内。历史禁入只提示。"""

    id = "rule_owner_ban"
    title = "招标人集团禁入/受限供应商"

    def evaluate(self, findings, project: Project, company: Company | None = None) -> RuleResult:
        base = project.base_date
        statuses: list[Status] = []
        reasons: list[str] = []
        matched = False
        for f in findings:
            if f.kind != "owner_ban":
                continue
            if not project.owner_group or f.attrs.get("owner_group") != project.owner_group:
                reasons.append(
                    f"[{f.source_id}] 禁入名单属于其他集团（{f.attrs.get('owner_group')}），对本项目不适用"
                )
                statuses.append(Status.NO_DATA)
                continue
            matched = True
            if effective_on(f.start_date, f.end_date, base):
                scope = f.attrs.get("scope", "")
                reasons.append(f"[{f.source_id}] 该集团禁入在有效期内，适用范围：{scope}：{f.description}")
                statuses.append(_fail_or_unknown([f], reasons))
            else:
                reasons.append(f"[{f.source_id}] 该集团历史禁入已过有效期，仅作历史风险提示")
                statuses.append(Status.WARNING)
        if not matched and not statuses:
            return _done(self.id, self.title, [], ["未检索到招标人集团禁入记录"], company)
        return _done(self.id, self.title, statuses, reasons, company)


class LicenseValidityRule:
    """任务书 §6：证照有效期特别规则。

    投标文件扫描件过期只允许说“表面已超过载明有效期”（WARNING）；
    是否无证以主管部门当前状态为准：已延期不得判无证；过期/注销/吊销/暂扣才进入否决评估。
    """

    id = "rule_license_validity"
    title = "安全生产许可证/建筑资质当前有效性"
    DEAD_STATES = {"过期", "注销", "吊销", "暂扣"}

    def evaluate(self, findings, project: Project, company: Company | None = None) -> RuleResult:
        statuses: list[Status] = []
        reasons: list[str] = []
        hit = False
        surface_expired = False
        for f in findings:
            if f.kind == "license_surface_expired":
                hit = True
                surface_expired = True
                reasons.append(
                    f"[{f.source_id}] 投标文件所附证件表面已超过载明有效期（{f.description}），"
                    "以主管部门当前登记状态为准"
                )
                statuses.append(Status.WARNING)
            elif f.kind == "license_authority_status":
                hit = True
                state = f.attrs.get("status", "")
                if state in self.DEAD_STATES:
                    reasons.append(f"[{f.source_id}] 主管部门当前状态为「{state}」：{f.description}")
                    statuses.append(_fail_or_unknown([f], reasons))
                elif state in ("正常", "延期"):
                    if surface_expired:
                        reasons.append(f"[{f.source_id}] 主管部门显示「{state}」，不能判企业无证")
                    else:
                        reasons.append(f"[{f.source_id}] 主管部门当前状态「{state}」")
                    statuses.append(Status.NO_DATA)
                else:
                    reasons.append(f"[{f.source_id}] 主管部门状态「{state}」未知语义，转人工确认")
                    statuses.append(Status.MANUAL)
        if not hit:
            return _done(self.id, self.title, [], ["未检索到证照/资质状态记录"], company)
        return _done(self.id, self.title, statuses, reasons, company)


DEFAULT_RULES = (
    BidRestrictionRule(),
    BusinessStatusRule(),
    BankruptcyRule(),
    OwnerBanRule(),
    LicenseValidityRule(),
)

#: 主体一致性待确认的兜底条款（P0.5 §六）：UNCONFIRMED 记录不得进业务条款，
#: 由本条款统一转人工；随 DEFAULT_RULES 之外的附加结果产出。
SUBJECT_CONFIRMATION_RULE_ID = "rule_subject_confirmation"


def subject_confirmation_result(unconfirmed: list[Finding]) -> RuleResult:
    """无法确认主体的记录：不得作确定性结论，转人工（§六规则 7）。"""
    reasons = []
    for f in unconfirmed:
        reasons.append(
            f"[{f.source_id}] 主体一致性未确认（{f.attrs.get('match_reason', '')}），"
            f"暂不作为否决证据：{f.description}"
        )
    return RuleResult(
        rule_id=SUBJECT_CONFIRMATION_RULE_ID,
        title="主体一致性待人工确认",
        status=Status.MANUAL.value,
        reasons=reasons,
        company=None,
    )


class RuleEngine:
    def __init__(self, rules=DEFAULT_RULES):
        self.rules = list(rules)

    def run_all(self, findings, project: Project, company: Company | None = None) -> list[RuleResult]:
        # 主体一致性强制点（P0.5 §六）：UNCONFIRMED 记录绝不进业务条款（防止
        # 同名/缺码记录被错并成 FAIL），统一转人工兜底条款
        confirmed = [f for f in findings if f.attrs.get("match_result") != UNCONFIRMED]
        unconfirmed = [f for f in findings if f.attrs.get("match_result") == UNCONFIRMED]
        results = [rule.evaluate(confirmed, project, company) for rule in self.rules]
        if unconfirmed:
            results.append(subject_confirmation_result(unconfirmed))
        return results

    @staticmethod
    def overall(results) -> str:
        """全部条款的最严重结论。任一 ERROR/TIMEOUT/BLOCKED/MANUAL/UNKNOWN 都不会被吞成 PASS。"""
        return combine_decision([r.status for r in results]).value
