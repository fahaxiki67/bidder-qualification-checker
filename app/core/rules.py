"""RuleEngine：只回答"这些事实是否触发本项目资格否决条款"（任务书 §4/§5/§6）。

硬规则：
- FAIL 必须有 A/B 级证据支持；仅 C/D 级线索 → UNKNOWN（任务书 §8）；
- 历史处罚/历史禁入已解除 → WARNING，不按当前状态否决；
- "其他丧失履约能力"不得由机器扩大解释 → 一律 MANUAL 转人工；
- 普通罚款不自动等于 FAIL。

P0.5 §八：规则定义来源 app/config/rules.yaml（scope=term/background + clause）；
审计整改：Project.years_back（“近几年”窗口）此前只是被采集进库、从未参与判断——
死参数最危险的地方是让人误以为已经生效。现按“只提示、不自动降级”落地：
窗口外的记录在判定依据里显式标注，由人工对照招标文件期限口径复核，
机器绝不因超窗口自行把 FAIL 抹成 WARNING（宁可多提示，不可漏否决）。

Project.terms 真正控制哪些资格条款参与正式资格判断——未被本项目启用的条款
不得形成否决（记 NOT_APPLICABLE 留痕）；background 规则始终评估但只作
通用背景风险，绝不单独否决项目资格。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

import yaml

from .evidence import can_support_fail
from .matching import DIFFERENT_SUBJECT, UNCONFIRMED
from .models import Company, Finding, Project, RuleResult
from .status import Status, combine_decision

#: 规则定义文件（随包分发；PROJECT_ROOT/app/config/rules.yaml）
RULES_YAML = Path(__file__).resolve().parents[1] / "config" / "rules.yaml"

_TERM_SPLIT = re.compile(r"[,，、;；/\s]+")


@dataclass
class RuleSpec:
    """rules.yaml 的一行：规则 id ↔ 结构化条款号 ↔ scope。"""

    id: str
    title: str
    clause: str
    scope: str
    fail_requires: str = ""


def load_rule_specs(path: str | Path = RULES_YAML) -> dict[str, RuleSpec]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    specs: dict[str, RuleSpec] = {}
    for raw in data.get("rules") or []:
        spec = RuleSpec(
            id=str(raw["id"]), title=str(raw.get("title", "")),
            clause=str(raw.get("clause", "")),
            scope=str(raw.get("scope", "term")),
            fail_requires=str(raw.get("fail_requires", "")),
        )
        specs[spec.id] = spec
    return specs


def normalize_terms(terms) -> set[str] | None:
    """条款勾选归一化。None=未指定（全部条款启用，兼容旧调用）；
    空串/空集合=明确不启用任何资格条款（仅 background 规则评估）。"""
    if terms is None:
        return None
    if isinstance(terms, str):
        return {x for x in _TERM_SPLIT.split(terms) if x}
    return {str(x) for x in terms if x}


RULES_BY_ID: dict[str, object] = {}


def _register_default_rules() -> None:
    for r in DEFAULT_RULES:
        RULES_BY_ID[r.id] = r


def effective_on(start: date | None, end: date | None, base: date) -> bool:
    """以核查基准日判断处罚/禁入是否仍在有效期（start/end 为空表示不限）。"""
    return (start is None or start <= base) and (end is None or end >= base)


def _fail_or_unknown(cands: list[Finding], reasons: list[str]) -> Status:
    if can_support_fail([c.grade for c in cands]):
        reasons.append("存在 A/B 级官方证据支持否决")
        return Status.FAIL
    reasons.append("仅有 C/D 级线索，不得单独作 FAIL，需 A/B 级证据闭环")
    return Status.UNKNOWN


def out_of_window(f: Finding, project: Project) -> bool:
    """该记录是否整体落在项目“近 N 年”窗口之外（参考日 = 截止日，无则发生日）。

    未载明日期的记录不得判定为超窗口（宁可提示，不可据此放宽）。
    """
    window_start = project.window_start
    ref = f.end_date or f.start_date
    return ref is not None and ref < window_start


def _window_note(count: int, project: Project) -> str:
    return (f"近 {project.years_back} 年窗口（{project.window_start} 起）之外还有 {count} 条记录："
            "本工具不因超窗口自动降级结论，请人工对照招标文件期限口径复核")


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
    KINDS = ("penalty_bid_restriction",)

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
    """条款2：当前处于责令停产停业/证照暂扣吊销状态。关键词是"当前处于"。"""

    id = "rule_business_status"
    title = "当前处于停产停业或证照吊销/暂扣状态"
    KINDS = ("penalty_business",)
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
    """条款3：当前进入清算程序/被宣告破产。"其他丧失履约能力"一律转人工。"""

    id = "rule_bankruptcy"
    title = "进入清算程序或被宣告破产"
    KINDS = ("bankruptcy_status", "loss_of_capacity_other")

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
                    f"[{f.source_id}] 「其他丧失履约能力」不得由机器扩大解释，转人工判断：{f.description}"
                )
                statuses.append(Status.MANUAL)
        if not hit:
            return _done(self.id, self.title, [], ["未检索到破产/清算记录"], company)
        return _done(self.id, self.title, statuses, reasons, company)


class OwnerBanRule:
    """条款4：被纳入招标人集团受限/禁入供应商且仍在有效期内。历史禁入只提示。"""

    id = "rule_owner_ban"
    title = "招标人集团禁入/受限供应商"
    KINDS = ("owner_ban",)

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

    投标文件扫描件过期只允许说"表面已超过载明有效期"（WARNING）；
    是否无证以主管部门当前状态为准：已延期不得判无证；过期/注销/吊销/暂扣才进入否决评估。
    """

    id = "rule_license_validity"
    title = "安全生产许可证/建筑资质当前有效性"
    KINDS = ("license_surface_expired", "license_authority_status")
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
        scope="meta",
    )


def engine_for_terms(terms, specs: dict[str, RuleSpec] | None = None) -> "RuleEngine":
    """按本项目启用的条款构造 RuleEngine（P0.5 §八）。

    terms=None → 未指定，全部规则启用（兼容旧调用/mock 演示）；
    terms 为集合/串 → 仅启用 scope=term 且 clause 命中的规则；background 恒评估。
    """
    specs = specs if specs is not None else load_rule_specs()
    enabled = normalize_terms(terms)
    rules = []
    for spec in specs.values():
        rule = RULES_BY_ID.get(spec.id)
        if rule is None:
            continue
        if spec.scope == "term" and enabled is not None and spec.clause not in enabled:
            continue
        rules.append(rule)
    return RuleEngine(rules=rules, terms=enabled, specs=specs)


class RuleEngine:
    def __init__(self, rules=DEFAULT_RULES, terms=None, specs=None):
        self.rules = list(rules)
        self.terms = normalize_terms(terms)          # None=未指定→全启用（兼容旧调用）
        self.specs = specs if specs is not None else load_rule_specs()

    def run_all(self, findings, project: Project, company: Company | None = None) -> list[RuleResult]:
        # 主体一致性强制点（P0.5 §六 / P4 加固）：
        # - UNCONFIRMED：不得进业务条款（防错并成 FAIL），统一转人工兜底；
        # - DIFFERENT_SUBJECT：非同一主体的记录对本企业=无记录，任何入口
        #   （adapter 已剔除；人工导入直调 parse 的路径在此兜底）都不得形成证据。
        confirmed = [
            f for f in findings
            if f.attrs.get("match_result") not in (UNCONFIRMED, DIFFERENT_SUBJECT)
        ]
        unconfirmed = [f for f in findings if f.attrs.get("match_result") == UNCONFIRMED]
        results: list[RuleResult] = []
        for rule in self.rules:
            out = rule.evaluate(confirmed, project, company)
            # “近 N 年”窗口透明化：本规则消费到的记录里有超窗口的 → 判定依据里写明
            oow = [f for f in confirmed
                   if f.kind in getattr(rule, "KINDS", ()) and out_of_window(f, project)]
            if oow:
                out.reasons.append(_window_note(len(oow), project))
            spec = self.specs.get(rule.id)
            results.append(replace(out, scope=spec.scope if spec else None))
        # 本项目未启用的资格条款：显式留痕 NOT_APPLICABLE（不参与正式资格判断）
        if self.terms is not None:
            enabled_ids = {r.id for r in self.rules}
            for spec in self.specs.values():
                if spec.scope == "term" and spec.id not in enabled_ids and spec.id in RULES_BY_ID:
                    results.append(RuleResult(
                        rule_id=spec.id, title=spec.title, status="NOT_APPLICABLE",
                        reasons=[f"本项目未启用该资格条款（{spec.clause}），不参与正式资格判断"],
                        scope=spec.scope,
                    ))
        if unconfirmed:
            results.append(subject_confirmation_result(unconfirmed))
        return results

    @staticmethod
    def overall(results) -> str:
        """正式资格判断：只统计启用的 term/meta 条款。

        background=通用背景风险不参与否决；NOT_APPLICABLE=未启用条款不入统计；
        任一 ERROR/TIMEOUT/BLOCKED/MANUAL/UNKNOWN 都不会被吞成 PASS。
        """
        return combine_decision(
            r.status for r in results
            if r.status != "NOT_APPLICABLE" and getattr(r, "scope", None) != "background"
        ).value


_register_default_rules()
