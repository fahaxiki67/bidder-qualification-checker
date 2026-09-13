import { useState } from "react";
import { AppShell } from "@/components/app-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import {
  SCENARIOS,
  STATUS_LABEL,
  checkUscc,
  runQualify,
  type QualifyResult,
  type ScenarioId,
  type Status,
  type TermId,
} from "@/lib/qualify/mock";

const TERMS: { id: TermId; label: string }[] = [
  { id: "条款1", label: "条款1 限制投标/采购" },
  { id: "条款2", label: "条款2 停产停业/证照吊销" },
  { id: "条款3", label: "条款3 破产/清算" },
  { id: "条款4", label: "条款4 招标人集团禁入" },
];

function toneFor(status: Status) {
  if (status === "FAIL" || status === "ERROR" || status === "TIMEOUT" || status === "BLOCKED") return "high" as const;
  if (status === "MANUAL" || status === "UNKNOWN" || status === "WARNING") return "mid" as const;
  if (status === "PASS") return "ok" as const;
  return "muted" as const;
}

export function QualifyPage() {
  const [project, setProject] = useState("某市政道路改造工程施工招标");
  const [company, setCompany] = useState("演示验收公司");
  const [uscc, setUscc] = useState("");
  const [province, setProvince] = useState("四川");
  const [ownerGroup, setOwnerGroup] = useState("powerchina");
  const [terms, setTerms] = useState<TermId[]>(["条款1", "条款2", "条款3", "条款4"]);
  const [scenario, setScenario] = useState<ScenarioId>("bid_ban");
  const [usccError, setUsccError] = useState<string | null>(null);
  const [result, setResult] = useState<QualifyResult | null>(null);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const checked = checkUscc(uscc);
    if (!checked.ok) {
      setUsccError(checked.message ?? "信用代码无效");
      return;
    }
    setUsccError(null);
    setResult(
      runQualify({
        project,
        company,
        uscc: checked.value,
        province,
        industry: "建筑",
        ownerGroup,
        terms,
        scenario,
        yearsBack: 3,
      }),
    );
  }

  return (
    <AppShell>
      <header className="max-w-3xl">
        <p className="text-xs font-medium tracking-[0.16em] text-muted">QUALIFY</p>
        <h1 className="mt-2 text-3xl md:text-4xl">资格前审</h1>
        <p className="mt-3 text-sm text-muted">
          当前只能跑演示场景。全国官网接口还没经人工复核回填，真实查询会一律返回「待人工核查」，
          查询失败也绝不会显示成正常。
        </p>
      </header>

      <form onSubmit={submit} className="mt-8 space-y-4">
        <Card>
          <h2 className="text-lg">项目与投标人</h2>
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            <div>
              <Label htmlFor="pname">项目名称</Label>
              <Input id="pname" value={project} onChange={(e) => setProject(e.target.value)} required />
            </div>
            <div>
              <Label htmlFor="cname">企业名称</Label>
              <Input id="cname" value={company} onChange={(e) => setCompany(e.target.value)} required />
            </div>
            <div>
              <Label htmlFor="uscc">统一社会信用代码</Label>
              <Input id="uscc" value={uscc} onChange={(e) => setUscc(e.target.value)} placeholder="可选，18 位" />
              {usccError && <p className="mt-1 text-xs text-danger">{usccError}</p>}
            </div>
            <div>
              <Label htmlFor="prov">注册地 / 项目地</Label>
              <select
                id="prov"
                value={province}
                onChange={(e) => setProvince(e.target.value)}
                className="h-11 w-full rounded-sm border border-border bg-surface px-3 text-sm"
              >
                <option value="四川">四川</option>
                <option value="广东">广东</option>
                <option value="">不限</option>
              </select>
            </div>
            <div>
              <Label htmlFor="og">招标人集团</Label>
              <select
                id="og"
                value={ownerGroup}
                onChange={(e) => setOwnerGroup(e.target.value)}
                className="h-11 w-full rounded-sm border border-border bg-surface px-3 text-sm"
              >
                <option value="powerchina">中国电建</option>
                <option value="">无</option>
              </select>
            </div>
            <div>
              <Label htmlFor="sc">演示场景</Label>
              <select
                id="sc"
                value={scenario}
                onChange={(e) => setScenario(e.target.value as ScenarioId)}
                className="h-11 w-full rounded-sm border border-border bg-surface px-3 text-sm"
              >
                {SCENARIOS.map((s) => (
                  <option key={s.id} value={s.id}>{s.label}</option>
                ))}
              </select>
            </div>
          </div>
          <fieldset className="mt-4">
            <legend className="mb-2 text-xs font-medium text-muted">本项目资格条款</legend>
            <div className="flex flex-wrap gap-3">
              {TERMS.map((t) => (
                <label key={t.id} className="flex min-h-11 items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={terms.includes(t.id)}
                    onChange={(e) =>
                      setTerms((prev) => (e.target.checked ? [...prev, t.id] : prev.filter((x) => x !== t.id)))
                    }
                  />
                  {t.label}
                </label>
              ))}
            </div>
          </fieldset>
          <Button className="mt-5" type="submit">开始核查</Button>
        </Card>
      </form>

      {result && (
        <div className="mt-6 space-y-4">
          <Card>
            <p className="text-xs text-muted">总体结论 · 演示链路</p>
            <div className="mt-2 flex flex-wrap items-center gap-3">
              <span className="font-display text-3xl">{STATUS_LABEL[result.overall]}</span>
              <Badge tone={toneFor(result.overall)}>{result.overall}</Badge>
            </div>
            <p className="mt-3 text-sm text-muted">{result.notice}</p>
          </Card>
          <Card>
            <h2 className="text-lg">条款结论</h2>
            <ul className="mt-3 space-y-3">
              {result.findings.map((f) => (
                <li key={f.title} className="rounded-md bg-surface p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={toneFor(f.status)}>{STATUS_LABEL[f.status]}</Badge>
                    <span className="text-sm font-medium">{f.term} · {f.title}</span>
                  </div>
                  <p className="mt-2 text-sm text-muted">{f.basis}</p>
                </li>
              ))}
            </ul>
          </Card>
          <Card>
            <h2 className="text-lg">数据源</h2>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-xs text-muted">
                  <tr>
                    <th className="py-2 font-medium">平台</th>
                    <th className="py-2 font-medium">级别</th>
                    <th className="py-2 font-medium">状态</th>
                    <th className="py-2 font-medium">说明</th>
                  </tr>
                </thead>
                <tbody>
                  {result.sources.map((s) => (
                    <tr key={s.id} className="border-t border-border/70 align-top">
                      <td className="py-2 pr-3">{s.name}</td>
                      <td className="py-2 pr-3 text-muted">{s.level}</td>
                      <td className="py-2 pr-3"><Badge tone={toneFor(s.status)}>{STATUS_LABEL[s.status]}</Badge></td>
                      <td className="py-2 text-muted">{s.note}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      )}
    </AppShell>
  );
}
