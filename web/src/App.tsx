import { useEffect, useState } from "react";
import { currentPath } from "@/lib/nav";
import { Home } from "@/pages/home";
import { QualifyPage } from "@/pages/qualify";
import { ReviewPage } from "@/pages/review";
import { RulesPage } from "@/pages/rules";

export function App() {
  const [route, setRoute] = useState(currentPath);
  useEffect(() => {
    const onPop = () => setRoute(currentPath());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  if (route === "/review") return <ReviewPage />;
  if (route === "/qualify") return <QualifyPage />;
  if (route === "/rules") return <RulesPage />;
  return <Home />;
}
