import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium tabular-nums",
  {
    variants: {
      tone: {
        default: "bg-primary/8 text-primary",
        muted: "bg-border/60 text-muted",
        high: "bg-danger/10 text-danger",
        mid: "bg-warn/12 text-warn",
        ok: "bg-ok/12 text-ok",
      },
    },
    defaultVariants: { tone: "default" },
  },
);

export function Badge({
  className,
  tone,
  ...props
}: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ tone, className }))} {...props} />;
}
