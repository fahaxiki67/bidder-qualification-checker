import { cn } from "@/lib/utils";

export function Card({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      className={cn(
        "rounded-xl bg-card p-5 text-fg shadow-[var(--shadow-border)] md:p-6",
        className,
      )}
      {...props}
    />
  );
}
