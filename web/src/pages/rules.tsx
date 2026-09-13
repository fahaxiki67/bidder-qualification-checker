import { AppShell } from "@/components/app-shell";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { RULE_CATALOG } from "@/lib/review/catalog";

export function RulesPage() {
  return (
    <AppShell>
      <header className="max-w-3xl">
        <p className="text-xs font-medium tracking-[0.16em] text-muted">RULES</p>
        <h1 className="mt-2 text-3xl md:text-4xl">规则与口径</h1>
        <p className="mt-3 text-sm text-muted">
          阈值是筛选参数，不是法律推定。任何单一报价、IP、MAC、作者或文本相似信号，都不得自动认定串通投标。
          F-08～F-10 尚未启用。
        </p>
      </header>

      <Card className="mt-8 overflow-x-auto p-0 md:p-0">
        <table className="w-full min-w-[36rem] text-left text-sm">
          <thead className="border-b border-border text-xs text-muted">
            <tr>
              <th className="px-5 py-3 font-medium">编号</th>
              <th className="px-5 py-3 font-medium">规则</th>
              <th className="px-5 py-3 font-medium">触发条件</th>
              <th className="px-5 py-3 font-medium">级别</th>
            </tr>
          </thead>
          <tbody>
            {RULE_CATALOG.map((r) => (
              <tr key={r.id} className="border-t border-border/70">
                <td className="px-5 py-3 font-mono text-xs">{r.id}</td>
                <td className="px-5 py-3">{r.name}</td>
                <td className="px-5 py-3 text-muted">{r.when}</td>
                <td className="px-5 py-3">
                  <Badge tone={r.level === "高" ? "high" : "mid"}>{r.level}</Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <div className="mt-6 grid gap-4 md:grid-cols-2">
        <Card>
          <h2 className="text-lg">已改、可直接用</h2>
          <ul className="mt-3 space-y-2 text-sm text-muted">
            <li>浏览器内上传，不再填服务器路径</li>
            <li>新增 .xls、.docx 解析</li>
            <li>15 条规则与脱敏、人工复核口径对齐原仓库</li>
            <li>资格核查对真实官网保持 MANUAL，不伪造成功</li>
          </ul>
        </Card>
        <Card>
          <h2 className="text-lg">仍需你配合的</h2>
          <ul className="mt-3 space-y-2 text-sm text-muted">
            <li>白天打开官方查询页，确认真实接口后再回填（P3R）</li>
            <li>扫描件 OCR、广联达 GCFX、.doc 仍未做</li>
            <li>Win/Mac 安装包真机点验收、代码签名</li>
          </ul>
        </Card>
      </div>
    </AppShell>
  );
}
