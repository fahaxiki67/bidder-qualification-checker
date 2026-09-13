import { ArrowRight, FileSearch, ShieldAlert } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { navigate } from "@/lib/nav";

export function Home() {
  return (
    <AppShell>
      <section className="max-w-3xl">
        <p className="text-xs font-medium tracking-[0.18em] text-muted uppercase">Bidder Review Checker</p>
        <h1 className="mt-3 font-display text-4xl font-medium text-fg md:text-5xl">
          投标资料先过筛，
          <br />
          结论留给人。
        </h1>
        <p className="mt-5 max-w-xl text-base text-muted">
          把多家投标文件丢进来，按报价、清单、文本、元数据和关联线索做本地预警。
          资格核查目前只跑演示数据——全国官网真实查询还没接通，不会假装查过。
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <Button type="button" onClick={() => navigate("/review")}>
            开始离线审查
            <ArrowRight />
          </Button>
          <Button type="button" variant="secondary" onClick={() => navigate("/qualify")}>
            资格核查演示
          </Button>
        </div>
      </section>

      <div className="mt-12 grid gap-4 md:grid-cols-2">
        <Card className="flex flex-col gap-4 rounded-xl p-6">
          <span className="flex size-10 items-center justify-center rounded-sm bg-primary/8 text-primary">
            <FileSearch className="size-5" />
          </span>
          <div>
            <h2 className="text-xl">离线多投标审查</h2>
            <p className="mt-2 text-sm text-muted">
              支持 txt / md / csv / json / xlsx / xls / pdf / docx。按投标人分子目录上传，15 条规则全部接线。扫描件 PDF 只读文本层。
            </p>
          </div>
          <button type="button" onClick={() => navigate("/review")} className="mt-auto text-left text-sm font-medium text-primary">
            进入审查 →
          </button>
        </Card>
        <Card className="flex flex-col gap-4 rounded-xl p-6">
          <span className="flex size-10 items-center justify-center rounded-sm bg-danger/8 text-danger">
            <ShieldAlert className="size-5" />
          </span>
          <div>
            <h2 className="text-xl">资格前审</h2>
            <p className="mt-2 text-sm text-muted">
              信用中国、执行公开、建筑市场等源的解析骨架已在，但接口未人工复核。真实查询一律标成待人工核查。
            </p>
          </div>
          <button type="button" onClick={() => navigate("/qualify")} className="mt-auto text-left text-sm font-medium text-primary">
            看演示与数据源现状 →
          </button>
        </Card>
      </div>

      <dl className="mt-12 grid grid-cols-2 gap-6 border-t border-border pt-8 md:grid-cols-4">
        {[
          ["15 条", "已启用预警规则"],
          ["8 种", "可解析文件格式"],
          ["0 上传", "资料不离开浏览器"],
          ["否", "自动认定串标"],
        ].map(([k, v]) => (
          <div key={v}>
            <dt className="font-display text-2xl text-fg">{k}</dt>
            <dd className="mt-1 text-sm text-muted">{v}</dd>
          </div>
        ))}
      </dl>
    </AppShell>
  );
}
