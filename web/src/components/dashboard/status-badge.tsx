import * as React from "react"

import { cn } from "@/lib/utils"

export type StatusTone = "success" | "warning" | "failed" | "info" | "neutral"

const dotClass: Record<StatusTone, string> = {
  success: "bg-success-fill",
  warning: "bg-warning",
  failed: "bg-destructive",
  info: "bg-info",
  neutral: "bg-muted-foreground",
}

/**
 * Badge trạng thái dạng **chấm màu + chữ trung tính** (kiểu Linear/Vercel).
 *
 * Khác `Badge variant="success"` ở chỗ chữ không mang màu: vàng cam của
 * "cảnh báo" mà làm chữ trên nền sáng thì không bao giờ đạt 4.5:1, nên trạng
 * thái được nói bằng chữ, còn màu chỉ là chấm phụ trợ (≥ 3:1 như mảng màu).
 * Cùng một kiểu cho mọi tone thì bảng cũng đỡ loè loẹt hơn.
 */
export function StatusBadge({
  tone,
  className,
  children,
  ...props
}: React.ComponentProps<"span"> & { tone: StatusTone }) {
  return (
    <span
      data-slot="status-badge"
      data-tone={tone}
      className={cn(
        "inline-flex w-fit items-center gap-1.5 whitespace-nowrap rounded-md border px-2 py-0.5 text-xs font-medium",
        className,
      )}
      {...props}
    >
      <span aria-hidden className={cn("size-1.5 shrink-0 rounded-full", dotClass[tone])} />
      {children}
    </span>
  )
}
