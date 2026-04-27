import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors focus:outline-none",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary text-primary-foreground",
        secondary: "border-transparent bg-secondary text-secondary-foreground",
        destructive: "border-transparent bg-destructive text-destructive-foreground",
        outline: "text-foreground",
        blue: "border-transparent bg-[var(--status-discussing-bg)] text-[var(--status-discussing-fg)]",
        green: "border-transparent bg-[var(--status-concluded-bg)] text-[var(--status-concluded-fg)]",
        purple: "border-transparent bg-[var(--status-project-bg)] text-[var(--status-project-fg)]",
        amber: "border-transparent bg-[var(--status-paused-bg)] text-[var(--status-paused-fg)]",
        gray: "border-transparent bg-[var(--status-archived-bg)] text-[var(--status-archived-fg)]",
        red: "border-transparent bg-[var(--danger-500)] text-white",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
