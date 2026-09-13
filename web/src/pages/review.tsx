import { useMemo, useRef, useState } from "react";
import { Download, FolderOpen, LoaderCircle, Trash2 } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { demoIncoming } from "@/lib/review/demo";
import { bidderNameFromFile, reviewFiles, type IncomingFile } from "@/lib/review/engine";
import { downloadText, toMarkdown } from "@/lib/review/report";
import type { ReviewResult } from "@/lib/review/types";
import { formatYuan, relativePath } from "@/lib/utils";

type Row = IncomingFile & { id: string };

export function ReviewPage() {
  const [project, setProject] = useState("");
  const [rows, setRows] = useState<Row[]>([]);
  const [relationsText, setRelationsText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ReviewResult | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const dirRef = useRef<HTMLInputElement>(null);

  const grouped = useMemo(() => {
    const map = new Map<string, number>();
    for (const row of rows) {
      const name = row.bidder.trim() || "未分组";
      map.set(name, (map.get(name) ?? 0) + 1);
    }
    return [...map.entries()];
  }, [rows]);

  function addFiles(list: FileList | File[]) {
    const next: Row[] = [];
    for (const file of Array.from(list)) {
      next.push({
        id: `${relativePath(file)}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2, 7)}`,
        file,
        bidder: bidderNameFromFile(file),
      });
    }
    setRows((prev) => [...prev, ...next]);
    setResult(null);
  }

  async function run(incoming?: IncomingFile[], extra?: { relationsText?: string; project?: string }) {
    const payload = incoming ?? rows;
    if (!payload.length) {
      setError("请先加入投标文件，或载入演示样本。");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const out = await reviewFiles(payload, {
        project: extra?.project ?? project,
        relationsText: extra?.relationsText ?? relationsText,
        relationsName: "relations",
      });
      setResult(out);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  function loadDemo() {
    const demo = demoIncoming();
    setProject(demo.project);
    setRelationsText(demo.relationsText);
    const next = demo.files.map((item, i) => ({
      ...item,
      id: `demo-${i}-${item.file.name}`,
    }));
    setRows(next);
    void run(next, { relationsText: demo.relationsText, project: demo.project });
  }

  return (
    <AppShell>
      <header className="max-w-3xl">
        <p className="text-xs font-medium tracking-[0.16em] text-muted">OFFLINE REVIEW</p>
        <h1 className="mt-2 text-3xl md:text-4xl">多投标文件离线审查</h1>
        <p className="mt-3 text-sm text-muted">
          文件只在当前浏览器内存里解析。推荐「一级文件夹名 = 投标人」，或文件名写成
          投标人__文件名。xls / docx 已支持；扫描件 PDF 没有 OCR，只抽文本层。
        </p>
      </header>

      <Card className="mt-8">
        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <Label htmlFor="project">项目名称</Label>
            <Input id="project" value={project} onChange={(e) => setProject(e.target.value)} placeholder="仅写入报告" />
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <Button type="button" onClick={() => fileRef.current?.click()}>
              选择文件
            </Button>
            <Button type="button" variant="secondary" onClick={() => dirRef.current?.click()}>
              <FolderOpen />
              选择文件夹
            </Button>
            <Button type="button" variant="outline" onClick={loadDemo}>
              载入演示样本
            </Button>
          </div>
        </div>
        <input ref={fileRef} type="file" multiple className="hidden" onChange={(e) => e.target.files && addFiles(e.target.files)} />
        <input
          ref={dirRef}
          type="file"
          className="hidden"
          multiple
          // @ts-expect-error non-standard directory picker
          webkitdirectory=""
          onChange={(e) => e.target.files && addFiles(e.target.files)}
        />

        <div
          className="mt-5 rounded-lg border border-dashed border-border bg-surface px-4 py-10 text-center text-sm text-muted"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
          }}
        >
          把文件拖到这里。已加入 {rows.length} 份
          {grouped.length ? ` · ${grouped.length} 家投标人` : ""}
        </div>

        {rows.length > 0 && (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[32rem] text-left text-sm">
              <thead className="text-xs text-muted">
                <tr>
                  <th className="py-2 font-medium">投标人</th>
                  <th className="py-2 font-medium">文件</th>
                  <th className="py-2 font-medium">大小</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id} className="border-t border-border/70">
                    <td className="py-2 pr-3">
                      <Input
                        value={row.bidder}
                        onChange={(e) =>
                          setRows((prev) => prev.map((r) => (r.id === row.id ? { ...r, bidder: e.target.value } : r)))
                        }
                      />
                    </td>
                    <td className="py-2 pr-3 text-muted">{relativePath(row.file)}</td>
                    <td className="py-2 pr-3 tabular-nums text-muted">{(row.file.size / 1024).toFixed(1)} KB</td>
                    <td className="py-2 text-right">
                      <Button variant="ghost" size="icon" aria-label="移除" onClick={() => setRows((p) => p.filter((r) => r.id !== row.id))}>
                        <Trash2 />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="mt-5">
          <Label htmlFor="rel">关联线索 CSV / JSON（可选）</Label>
          <textarea
            id="rel"
            value={relationsText}
            onChange={(e) => setRelationsText(e.target.value)}
            placeholder={"bidder_a,bidder_b,relation\n甲,乙,同一办公地址"}
            className="min-h-24 w-full rounded-sm border border-border bg-surface p-3 text-sm text-fg placeholder:text-subtle"
          />
        </div>

        <div className="mt-5 flex flex-wrap gap-3">
          <Button type="button" disabled={busy} onClick={() => void run()}>
            {busy ? <LoaderCircle className="animate-spin" /> : null}
            {busy ? "正在审查…" : "开始审查"}
          </Button>
          {rows.length > 0 && (
            <Button type="button" variant="ghost" onClick={() => { setRows([]); setResult(null); }}>
              清空
            </Button>
          )}
        </div>
        {error && <p className="mt-3 text-sm text-danger">{error}</p>}
      </Card>

      {result && <ResultView result={result} />}
    </AppShell>
  );
}

function ResultView({ result }: { result: ReviewResult }) {
  return (
    <div className="mt-8 space-y-4">
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-xl">审查概况</h2>
            <p className="mt-1 text-sm text-muted">{result.legal_notice.conclusion}</p>
          </div>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => downloadText("bid-review.md", toMarkdown(result), "text/markdown")}
            >
              <Download /> Markdown
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => downloadText("bid-review.json", JSON.stringify(result, null, 2), "application/json")}
            >
              JSON
            </Button>
          </div>
        </div>
        <dl className="mt-6 grid grid-cols-2 gap-4 md:grid-cols-4">
          <Stat label="投标人" value={result.summary.bidder_count} />
          <Stat label="文件" value={result.summary.file_count} />
          <Stat label="风险信号" value={result.summary.signal_count} />
          <Stat label="高风险" value={result.summary.high_signal_count} />
        </dl>
        <p className="mt-4 text-xs text-subtle">自动结论 = 否 · 整份结果须人工复核</p>
      </Card>

      <Card>
        <h2 className="text-xl">投标人报价</h2>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-muted">
              <tr>
                <th className="py-2 font-medium">投标人</th>
                <th className="py-2 font-medium">主报价（元）</th>
                <th className="py-2 font-medium">文件</th>
                <th className="py-2 font-medium">清单项</th>
              </tr>
            </thead>
            <tbody>
              {result.bidders.map((b) => (
                <tr key={b.name} className="border-t border-border/70">
                  <td className="py-2">{b.name}</td>
                  <td className="py-2 tabular-nums">
                    {b.primary_quote ? formatYuan(b.primary_quote.value) : <span className="text-subtle">未识别</span>}
                  </td>
                  <td className="py-2 tabular-nums">{b.files.length}</td>
                  <td className="py-2 tabular-nums">{b.line_item_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card>
        <h2 className="text-xl">风险信号</h2>
        <div className="mt-4 space-y-3">
          {result.signals.length === 0 && (
            <p className="text-sm text-muted">未触发预警。这不代表没有风险，只说明当前资料未命中已启用规则。</p>
          )}
          {result.signals.map((s) => (
            <article key={s.id} className="rounded-md bg-surface p-4">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={s.level === "高" ? "high" : "mid"}>{s.rule_id} · {s.level}</Badge>
                <h3 className="text-base font-medium">{s.title}</h3>
              </div>
              <p className="mt-1 text-xs text-subtle">{s.scope}</p>
              <p className="mt-2 text-sm text-fg">{s.description}</p>
              <p className="mt-2 text-xs text-muted">{s.legal_basis}</p>
            </article>
          ))}
        </div>
      </Card>

      {(result.parse_errors.length > 0 || result.parse_warnings.length > 0 || result.unsupported_files.length > 0) && (
        <Card>
          <h2 className="text-xl">解析缺口</h2>
          <ul className="mt-3 space-y-1 text-sm text-muted">
            {result.parse_errors.map((e) => (
              <li key={e.path}>错误 · {e.path}：{e.error}</li>
            ))}
            {result.parse_warnings.map((w, i) => (
              <li key={`${w.path}-${i}`}>提示 · {w.path} {w.locator}：{w.error}</li>
            ))}
            {result.unsupported_files.map((f) => (
              <li key={f.path}>未解析 · {f.path}</li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-1 font-display text-2xl tabular-nums">{value}</dd>
    </div>
  );
}
