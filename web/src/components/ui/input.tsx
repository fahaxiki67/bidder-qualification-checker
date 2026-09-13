import { cn } from "@/lib/utils";

export function Input({ className, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      className={cn(
        "h-11 w-full rounded-sm border border-border bg-surface px-3 text-sm text-fg placeholder:text-subtle",
        "transition-shadow duration-150 focus-visible:outline-none focus-visible:shadow-[0_0_0_2px_var(--color-ring)]",
        className,
      )}
      {...props}
    />
  );
}

export function Label({ className, ...props }: React.ComponentProps<"label">) {
  return <label className={cn("mb-1.5 block text-xs font-medium text-muted", className)} {...props} />;
}
