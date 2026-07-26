import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Native select.
 *
 * Deliberately not a custom listbox: the native control brings keyboard
 * behaviour, screen-reader support, and mobile pickers that a div-based
 * replacement has to reimplement and usually gets partly wrong.
 */
export function Select({ className, children, ...props }: React.ComponentProps<"select">) {
  return (
    <select
      className={cn(
        "flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    >
      {children}
    </select>
  );
}
