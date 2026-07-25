import * as React from "react";

import { cn } from "@/lib/utils";

export function Label({ className, ...props }: React.ComponentProps<"label">) {
  return (
    <label
      className={cn(
        "text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70",
        className,
      )}
      {...props}
    />
  );
}

/** Helper or error text tied to a field via aria-describedby. */
export function FieldHint({
  className,
  tone = "muted",
  ...props
}: React.ComponentProps<"p"> & { tone?: "muted" | "error" }) {
  return (
    <p
      className={cn(
        "text-xs",
        tone === "error" ? "text-destructive" : "text-muted-foreground",
        className,
      )}
      {...props}
    />
  );
}
