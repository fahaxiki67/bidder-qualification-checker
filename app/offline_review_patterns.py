"""报价规律与主体关联的增量预警规则（F-05/F-06/S-04/S-05/P-02/P-03）。

本模块是 offline_review 的增量规则层：输入已解析的投标人数据，输出与
offline_review._new_signal 同构的信号字典。它不访问网络、不修改输入文件、
不判定串通投标或投标无效；所有信号均须人工复核。

设计为独立文件以便与主线整改并行开发：接线只需在 review_directory 的
信号生成之后追加一次 ``apply(result, bidders, signals)`` 调用。
"""
from __future__ import annotations

import hashlib
import re
from statistics import mean, pstdev
from typing import Any, Iterable


PATTERN_THRESHOLDS = {
    "arithmetic_step_cv": 0.05,
    "geometric_ratio_cv": 0.02,
    "discount_rate_band": 0.001,
    "line_item_jaccard": 0.90,
    "min_line_item_set_common": 8,
    "shared_block_size": 200,
    "min_shared_blocks": 3,
    "shared_block_coverage": 0.10,
}

RULE_IDS = {
    "QUOTE_ARITHMETIC_PATTERN": "F-05",
    "UNIFORM_DISCOUNT_RATE": "F-06",
    "LINE_ITEM_SET_MATCH": "S-04",
    "SHARED_TEXT_BLOCKS": "S-05",
    "PERSON_OVERLAP": "P-02",
    "KINSHIP_RELATION": "P-03",
    "PAYMENT_ACCOUNT_MATCH": "E-02",
    "PERSON_TABLE_OVERLAP": "P-04",
}

LEGAL_BASIS = {
    "QUOTE_ARITHMETIC_PATTERN": "《招标投标法实施条例》第40条第4项关于投标报价呈规律性差异的关联线索；统计阈值为工具参数",
    "UNIFORM_DISCOUNT_RATE": "《招标投标法实施条例》第40条第4项关联线索；账户或控制价口径仍须人工核验",
    "LINE_ITEM_SET_MATCH": "《招标投标法实施条例》第40条第4项关于投标文件异常一致的关联线索；匹配阈值为工具参数",
    "SHARED_TEXT_BLOCKS": "《招标投标法实施条例》第40条第4项关于投标文件异常一致的关联线索；分块阈值为工具参数",
    "PERSON_OVERLAP": "《招标投标法实施条例》第40条第3项关于项目管理成员同一人的法定边界；扩展人员字段仅作线索",
    "KINSHIP_RELATION": "《招标投标法实施条例》第34条关于单位负责人同一/控股或管理关系的边界；亲属关系本身不等同法定关系",
    "PAYMENT_ACCOUNT_MATCH": "《招标投标法实施条例》第40条第6项关于保证金从同一单位或个人账户转出的法定边界；资料字段相同不等同转出事实",
    "PERSON_TABLE_OVERLAP": "《招标投标法实施条例》第34条第2款关于单位负责人为同一人或存在控股、管理关系的边界；人员任职重合仅作关联线索",
}

# 人员类元数据字段：跨投标人相同值归入 P-02 主体线索，而不是 E-01 电子痕迹。
PERSON_FIELDS = {"legal_representative", "contact", "contact_phone", "project_manager"}

_KINSHIP_RE = re.compile(
    r"夫妻|配偶|父子|母子|父女|母女|兄弟|姐妹|兄妹|姐弟|弟兄|亲属|近亲属|直系|"
    r"堂兄|堂弟|堂姐|堂妹|表兄|表弟|表姐|表妹|叔侄|翁婿|婆媳|连襟|妯娌"
)


def _norm(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip().lower()


def _pairwise(values: list[str]) -> Iterable[tuple[str, str]]:
    for index, left in enumerate(values):
        for right in values[index + 1:]:
            yield left, right


def _signal(code: str, title: str, scope: str, description: str, evidence: list[dict], *,
            level: str = "中") -> dict:
    return {
        "code": code,
        "rule_id": RULE_IDS.get(code),
        "kind": code.lower(),
        "level": level,
        "title": title,
        "scope": scope,
        "description": description,
        "legal_basis": LEGAL_BASIS.get(code, "规则说明中的法规/政策背景；本信号仅供人工复核"),
        "evidence": evidence,
        "manual_action": "人工复核原始文件、公开登记信息与电子投标平台留痕后再作判断",
        "auto_conclusion": False,
    }


def quote_pattern_signals(bidders: list[dict]) -> list[dict]:
    """F-05：三家及以上主报价呈等差或等比排列（实施条例第 40 条「规律性差异」线索）。"""
    quotes = {b["name"]: b.get("primary_quote") for b in bidders if b.get("primary_quote")}
    if len(quotes) < 3:
        return []
    names = list(quotes)
    values = [float(quotes[n]["value"]) for n in names]
    if any(v <= 0 for v in values):
        return []
    ordered = sorted(values)
    diffs = [b - a for a, b in zip(ordered, ordered[1:])]
    ratios = [b / a for a, b in zip(ordered, ordered[1:])]
    signals: list[dict] = []
    evidence = [{"bidder": n, "value": quotes[n]["value"]} for n in names]
    mean_diff = mean(diffs)
    if mean_diff > 0 and pstdev(diffs) / mean_diff <= PATTERN_THRESHOLDS["arithmetic_step_cv"]:
        signals.append(_signal(
            "QUOTE_ARITHMETIC_PATTERN", "多家投标总报价呈等差排列", "项目全部已识别主报价",
            f"{len(values)} 家主报价排序后相邻差值变异系数约 "
            f"{pstdev(diffs) / mean_diff:.2%}，呈现接近固定金额递增/递减的排列；"
            "报价排序本身可能由报价策略、取整或档次划分造成，不能单独认定协商报价。",
            evidence, level="高"))
    mean_ratio = mean(ratios)
    if not signals and mean_ratio > 0 and pstdev(ratios) / mean_ratio <= PATTERN_THRESHOLDS["geometric_ratio_cv"]:
        signals.append(_signal(
            "QUOTE_ARITHMETIC_PATTERN", "多家投标总报价呈等比排列", "项目全部已识别主报价",
            f"{len(values)} 家主报价排序后相邻比值变异系数约 "
            f"{pstdev(ratios) / mean_ratio:.2%}，呈现接近固定比例递增/递减的排列；"
            "需先排除统一按下浮率报价等正常口径。",
            evidence, level="高"))
    return signals


def uniform_discount_signals(bidders: list[dict]) -> list[dict]:
    """F-06：两家及以上相对控制价的下浮率几乎一致（「规律性下浮」线索）。

    只统计投标人自己文件中带控制价标注的资料；找不到控制价的投标人如实跳过。
    """
    rates: dict[str, dict] = {}
    for bidder in bidders:
        primary = bidder.get("primary_quote")
        if not primary or primary.get("kind") == "control":
            continue
        controls = [q for q in bidder.get("quotes", []) if q.get("kind") == "control"]
        if not controls or len({float(q["value"]) for q in controls}) != 1:
            continue
        control = controls[0]
        if not control.get("value"):
            continue
        # 主报价与控制价完全相同通常表示只解析到了控制价，不能当作投标报价。
        if float(primary.get("value")) == float(control.get("value")):
            continue
        rates[bidder["name"]] = {
            "bidder": bidder["name"],
            "quote": primary["value"],
            "control": control["value"],
            "discount_rate": round(1 - float(primary["value"]) / float(control["value"]), 6),
        }
    if len(rates) < 2:
        return []
    band = max(r["discount_rate"] for r in rates.values()) - min(r["discount_rate"] for r in rates.values())
    if band > PATTERN_THRESHOLDS["discount_rate_band"]:
        return []
    return [_signal(
        "UNIFORM_DISCOUNT_RATE", "多家投标相对控制价的下浮率几乎一致", "项目已识别控制价与主报价",
        f"{len(rates)} 家相对各自文件所载控制价的下浮率极差约 {band:.4%}（阈值 "
        f"{PATTERN_THRESHOLDS['discount_rate_band']:.2%}）；统一比例下浮可能来自同一报价"
        "模板、统一策略或协商约定，需核对控制价口径、取整规则与报价编制过程。",
        list(rates.values()), level="高")]


def line_item_set_signals(bidders: list[dict]) -> list[dict]:
    """S-04：两家可比清单项目构成高度一致，即便金额不同。"""
    key_sets: dict[str, set[str]] = {}
    for bidder in bidders:
        key_sets[bidder["name"]] = {
            item["comparison_key"]
            for item in bidder.get("line_items", [])
            if item.get("comparison_key") and item.get("comparability_status") == "COMPARABLE"
        }
    signals: list[dict] = []
    for left, right in _pairwise(list(key_sets)):
        a, b = key_sets[left], key_sets[right]
        union = a | b
        if not union:
            continue
        common = a & b
        score = len(common) / len(union)
        if score >= PATTERN_THRESHOLDS["line_item_jaccard"] and \
                len(common) >= PATTERN_THRESHOLDS["min_line_item_set_common"]:
            signals.append(_signal(
                "LINE_ITEM_SET_MATCH", "清单项目构成高度一致", f"{left} ↔ {right}",
                f"两家清单项目名称集合交并比约 {score:.2%}（共有 {len(common)} 项）；"
                "相同清单可能源自招标文件统一清单或同一编制软件，需结合金额分布与编制痕迹复核。",
                [{"bidder": left, "item_count": len(a)}, {"bidder": right, "item_count": len(b)}],
                level="中"))
    return signals


def person_overlap_signals(bidders: list[dict]) -> list[dict]:
    """P-02：法定代表人/联系人/联系电话/项目经理等人员字段跨投标人相同。"""
    maps: dict[str, dict[str, set[str]]] = {}
    raw_values: dict[tuple[str, str], set[str]] = {}
    for bidder in bidders:
        by_field: dict[str, set[str]] = {}
        for field, values in bidder.get("metadata", {}).items():
            if field not in PERSON_FIELDS:
                continue
            for entry in values:
                text = str(entry.get("value") or "").strip()
                if not text:
                    continue
                by_field.setdefault(field, set()).add(_norm(text))
                raw_values.setdefault((bidder["name"], field), set()).add(text[:100])
        maps[bidder["name"]] = by_field
    signals: list[dict] = []
    for left, right in _pairwise(list(maps)):
        for field in sorted(set(maps[left]) & set(maps[right])):
            shared = maps[left][field] & maps[right][field]
            if not shared:
                continue
            signals.append(_signal(
                "PERSON_OVERLAP", "投标资料所载人员信息重合", f"{left} ↔ {right}",
                f"人员字段 {field} 出现相同值；同一人员出现在不同投标资料中可能由"
                "代理机构、共用办公电话或填写错误等正常原因造成，须核对登记信息与人员真实身份。",
                [{"bidder": left, "field": field,
                  "values": sorted(raw_values.get((left, field), set()))},
                 {"bidder": right, "field": field,
                  "values": sorted(raw_values.get((right, field), set()))}], level="高"))
    return signals


def kinship_signals(result: dict, bidder_names: set[str]) -> list[dict]:
    """P-03：用户提供的关联线索中含亲属关系描述（家族关联线索）。"""
    signals: list[dict] = []
    for clue in result.get("relation_clues", []):
        relation = str(clue.get("relation") or "")
        if not _KINSHIP_RE.search(relation):
            continue
        left, right = str(clue.get("bidder_a") or ""), str(clue.get("bidder_b") or "")
        if left not in bidder_names and right not in bidder_names:
            continue
        signals.append(_signal(
            "KINSHIP_RELATION", "关联线索涉及投标人之间亲属关系", f"{left} ↔ {right}".strip(" ↔"),
            f"用户提供的本地线索描述了亲属关系（{relation}）；家族关联须以婚姻登记、"
            "户籍或商事登记等有权资料核实，线索本身不构成认定。",
            [{"source_file": str(clue.get("source") or "未注明"), "row": clue.get("row"),
              "clue": clue}], level="高"))
    return signals


def shared_block_signals(bidders: list[dict]) -> list[dict]:
    """S-05：两份投标文件共享大段连续文本（定长分块指纹，抓整文比对漏掉的部分抄袭）。

    把每份文件去空白小写文本切成固定长度块并取指纹，跨投标人对全部文件求块交集；
    共块达到数量与覆盖率阈值即提示。块内容不写入证据，避免报告携带投标原文。
    """
    size = PATTERN_THRESHOLDS["shared_block_size"]
    all_blocks: dict[str, set[bytes]] = {}
    block_total: dict[str, int] = {}
    for bidder in bidders:
        blocks: set[bytes] = set()
        for file in bidder.get("_internal_files", []):
            text = re.sub(r"\s+", "", str(file.get("text") or "")).lower()
            for start in range(0, max(0, len(text) - size + 1), size):
                blocks.add(hashlib.blake2b(text[start:start + size].encode("utf-8"),
                                           digest_size=12).digest())
        all_blocks[bidder["name"]] = blocks
        block_total[bidder["name"]] = len(blocks)
    signals: list[dict] = []
    for left, right in _pairwise(list(all_blocks)):
        shared = all_blocks[left] & all_blocks[right]
        smaller = min(block_total[left], block_total[right])
        if not shared or smaller < 1:
            continue
        coverage = len(shared) / smaller
        if len(shared) >= PATTERN_THRESHOLDS["min_shared_blocks"] and \
                coverage >= PATTERN_THRESHOLDS["shared_block_coverage"]:
            signals.append(_signal(
                "SHARED_TEXT_BLOCKS", "投标文件存在大段共用文本", f"{left} ↔ {right}",
                f"按 {size} 字定长分块后，两家文件共有 {len(shared)} 个相同文本块，"
                f"占较小一方块数约 {coverage:.1%}；可能来自统一模板、规范条文引用或"
                "复制同一来源，需核对章节结构、错别字特征与文件形成过程。",
                [{"bidder": left, "block_count": block_total[left]},
                 {"bidder": right, "block_count": block_total[right]},
                 {"shared_blocks": len(shared), "coverage": round(coverage, 4)}],
                level="中"))
    return signals


def _mask_account(value: str) -> str:
    """账号脱敏：保留前 4 后 4，中间用 * 代替；过短全部打码。"""
    text = re.sub(r"\s+", "", str(value or ""))
    if len(text) <= 8:
        return "*" * len(text)
    return f"{text[:4]}{'*' * (len(text) - 8)}{text[-4:]}"


def payment_account_signals(bidders: list[dict]) -> list[dict]:
    """E-02：银行/保证金账户字段跨投标人出现相同账号（电子标经典线索）。

    证据只保留脱敏账号，完整账号留在原始文件中由人工比对。
    """
    maps: dict[str, dict[str, set[str]]] = {}
    for bidder in bidders:
        by_field: dict[str, set[str]] = {}
        for field, values in bidder.get("metadata", {}).items():
            if field != "bank_account":
                continue
            for entry in values:
                text = str(entry.get("value") or "").strip()
                if text:
                    by_field.setdefault(field, set()).add(_norm(text))
        maps[bidder["name"]] = by_field
    signals: list[dict] = []
    for left, right in _pairwise(list(maps)):
        for field in sorted(set(maps[left]) & set(maps[right])):
            shared = maps[left][field] & maps[right][field]
            if not shared:
                continue
            signals.append(_signal(
                "PAYMENT_ACCOUNT_MATCH", "投标资料所载银行/保证金账户相同", f"{left} ↔ {right}",
                f"账户字段 {field} 出现相同账号（证据中已脱敏）；保证金由同一账户代缴、"
                "退款账户误填或代理机构代收均可能是正常原因，须以银行流水、保证金收退"
                "凭证与交易平台留痕核实。",
                [{"bidder": left, "field": field, "accounts": sorted(_mask_account(v) for v in shared)},
                 {"bidder": right, "field": field, "accounts": sorted(_mask_account(v) for v in shared)}],
                level="高"))
    return signals


# 人员长表（企查查/公示导出风格）列别名：人员 + 企业（+ 可选职务）。
def _norm_label_value(value: Any) -> str:
    return re.sub(r"[\s_\-]", "", str(value or "")).lower()


_PERSON_TABLE_KEYS = {
    "person": {"人员", "姓名", "人员姓名", "高管姓名", "股东姓名", "法定代表人姓名",
               "name", "person", "personname"},
    "company": {"公司", "企业", "企业名称", "公司名称", "任职企业", "关联企业",
                "company", "companyname", "股东名称"},
    "role": {"职务", "职位", "角色", "高管类型", "股东类型", "任职类型",
             "role", "position", "title"},
}
_PERSON_TABLE_NORM = {
    kind: {_norm_label_value(key) for key in keys}
    for kind, keys in _PERSON_TABLE_KEYS.items()
}


def person_table_overlap_signals(result: dict, bidder_names: set[str]) -> list[dict]:
    """P-04：用户提供的人员长表（企查查等导出）中同一人任职多家投标人。

    直接识别 relations 文件里的「人员+企业(+职务)」长表行，不要求用户预先
    整理成配对表；同一人命中至少两家投标人名称（精确匹配）才提示。
    """
    by_person: dict[str, dict[str, list[str]]] = {}
    for clue in result.get("relation_clues", []):
        row = clue.get("raw")
        if not isinstance(row, dict):
            continue
        normed = {_norm_label_value(k): v for k, v in row.items()}
        if any(k in normed for k in ("biddera", "companya", "namea")):
            continue  # 配对表行归 P-01/P-03 处理
        person = next((str(normed[k]).strip() for k in _PERSON_TABLE_NORM["person"]
                       if k in normed and str(normed[k] or "").strip()), None)
        company = next((str(normed[k]).strip() for k in _PERSON_TABLE_NORM["company"]
                        if k in normed and str(normed[k] or "").strip()), None)
        role = next((str(normed[k]).strip() for k in _PERSON_TABLE_NORM["role"]
                     if k in normed and str(normed[k] or "").strip()), "")
        if not person or len(person) < 2 or not company:
            continue
        by_person.setdefault(person, {}).setdefault(company, set()).add(role)
    signals: list[dict] = []
    for person in sorted(by_person):
        companies = by_person[person]
        hit = sorted(c for c in companies if c in bidder_names)
        if len(hit) < 2:
            continue
        roles = sorted(r for c in hit for r in companies[c] if r)
        signals.append(_signal(
            "PERSON_TABLE_OVERLAP", "人员长表显示同一人任职多家投标人", person,
            f"用户提供的人员资料中，{person} 同时出现在 {len(hit)} 家投标人"
            f"（{'、'.join(hit)}）的任职记录里"
            + (f"，职务/角色：{'、'.join(roles)}" if roles else "")
            + "；任职重合可能来自兼职工程师、挂名登记或资料误录，须以工商登记、"
              "社保与劳动合同等有权资料核实人员真实归属。",
            [{"person": person,
              "companies": [{"company": c, "roles": sorted(companies[c])} for c in hit]}],
            level="高"))
    return signals


def apply(result: dict, bidders: list[dict], signals: list[dict]) -> None:
    """把本模块全部规则追加进 review 信号列表（review_directory 接线入口）。"""
    names = {b["name"] for b in bidders}
    signals.extend(quote_pattern_signals(bidders))
    signals.extend(uniform_discount_signals(bidders))
    signals.extend(line_item_set_signals(bidders))
    signals.extend(shared_block_signals(bidders))
    signals.extend(person_overlap_signals(bidders))
    signals.extend(payment_account_signals(bidders))
    signals.extend(kinship_signals(result, names))
    signals.extend(person_table_overlap_signals(result, names))


__all__ = [
    "PATTERN_THRESHOLDS", "RULE_IDS", "PERSON_FIELDS",
    "quote_pattern_signals", "uniform_discount_signals", "line_item_set_signals",
    "shared_block_signals", "person_overlap_signals", "payment_account_signals",
    "kinship_signals", "person_table_overlap_signals", "apply",
]
