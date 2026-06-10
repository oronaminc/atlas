import { Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";

export function LoadingSpinner({ className }: { className?: string }) {
  return (
    <div className="flex items-center justify-center py-8">
      <Loader2
        className={cn("h-6 w-6 animate-spin text-muted-foreground", className)}
      />
    </div>
  );
}
