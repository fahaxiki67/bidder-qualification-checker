import { Scale } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { currentPath, navigate } from "@/lib/nav";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/", label: "首页" },
  { to: "/review", label: "离线审查" },
  { to: "/qualify", label: "资格核查" },
  { to: "/rules", label: "规则与口径" },
];

export function AppShell({ children }: { children: ReactNode }) {
  const [pathname, setPathname] = useState(currentPath);
  useEffect(() => {
    const onPop = () => setPathname(currentPath());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  return (
    <div className="min-h-dvh">
      <header className="sticky top-0 z-20 border-b border-border/80 bg-bg/90 backdrop-blur-sm">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-3 md:px-6">
          <a
            href="/"
            className="flex items-center gap-2 text-fg"
            onClick={(e) => {
              e.preventDefault();
              navigate("/");
            }}
          >
            <span className="flex size-9 items-center justify-center rounded-sm bg-primary text-primary-fg">
              <Scale className="size-4" strokeWidth={1.75} />
            </span>
            <span className="font-display text-base font-medium tracking-tight">投标审查器</span>
          </a>
          <nav className="flex items-center gap-1 overflow-x-auto text-sm">
            {NAV.map((item) => {
              const active = pathname === item.to;
              return (
                <a
                  key={item.to}
                  href={item.to}
                  onClick={(e) => {
                    e.preventDefault();
                    navigate(item.to);
                  }}
                  className={cn(
                    "rounded-sm px-3 py-2 whitespace-nowrap transition-colors duration-150",
                    active ? "bg-primary text-primary-fg" : "text-muted hover:bg-surface hover:text-fg",
                  )}
                >
                  {item.label}
                </a>
              );
            })}
          </nav>
        </div>
      </header>
      <div className="mx-auto max-w-6xl px-4 py-8 md:px-6 md:py-10">{children}</div>
      <footer className="border-t border-border/80 px-4 py-6 text-center text-xs text-subtle">
        输出仅为人工复核线索，不构成串通投标、违法、资格不合格或投标无效认定。文件在浏览器本地解析，不上传。
      </footer>
    </div>
  );
}
