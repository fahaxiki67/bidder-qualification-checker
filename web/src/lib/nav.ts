export function currentPath(): string {
  return window.location.pathname.replace(/\/$/, "") || "/";
}

export function navigate(to: string) {
  if (currentPath() === to) return;
  history.pushState({}, "", to);
  window.dispatchEvent(new PopStateEvent("popstate"));
}
