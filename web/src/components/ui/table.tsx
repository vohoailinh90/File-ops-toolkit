import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * Bảng tràn ngang thì vùng cuộn phải **Tab tới được**: người dùng bàn phím
 * không có chuột để kéo, nên vùng cuộn không nhận focus là phần bị che mãi mãi
 * (WCAG 2.1.1, axe `scrollable-region-focusable`). Chỉ bật `tabIndex` khi bảng
 * thật sự tràn — bảng vừa khung mà cũng thành một điểm dừng Tab thì chỉ làm
 * người dùng bàn phím phải bấm thêm một lần vô ích ở mọi bảng.
 */
function useHorizontalOverflow(ref: React.RefObject<HTMLDivElement | null>) {
  const [overflowing, setOverflowing] = React.useState(false)

  React.useEffect(() => {
    const el = ref.current
    if (!el) return
    const update = () => setOverflowing(el.scrollWidth > el.clientWidth)
    update()
    // Quan sát cả bảng lẫn khung: thêm dòng dài hơn làm bảng rộng ra mà khung
    // không đổi kích thước, còn thu cửa sổ thì ngược lại.
    const observer = new ResizeObserver(update)
    observer.observe(el)
    if (el.firstElementChild) observer.observe(el.firstElementChild)
    return () => observer.disconnect()
  }, [ref])

  return overflowing
}

function Table({ className, ...props }: React.ComponentProps<"table">) {
  const containerRef = React.useRef<HTMLDivElement>(null)
  const overflowing = useHorizontalOverflow(containerRef)

  return (
    <div
      ref={containerRef}
      data-slot="table-container"
      data-overflowing={overflowing || undefined}
      tabIndex={overflowing ? 0 : undefined}
      className="relative w-full overflow-x-auto rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
    >
      <table
        data-slot="table"
        className={cn("w-full caption-bottom text-sm", className)}
        {...props}
      />
    </div>
  )
}

function TableHeader({ className, ...props }: React.ComponentProps<"thead">) {
  return (
    <thead
      data-slot="table-header"
      className={cn("[&_tr]:border-b", className)}
      {...props}
    />
  )
}

function TableBody({ className, ...props }: React.ComponentProps<"tbody">) {
  return (
    <tbody
      data-slot="table-body"
      className={cn("[&_tr:last-child]:border-0", className)}
      {...props}
    />
  )
}

function TableFooter({ className, ...props }: React.ComponentProps<"tfoot">) {
  return (
    <tfoot
      data-slot="table-footer"
      className={cn(
        "border-t bg-muted/50 font-medium [&>tr]:last:border-b-0",
        className,
      )}
      {...props}
    />
  )
}

function TableRow({ className, ...props }: React.ComponentProps<"tr">) {
  return (
    <tr
      data-slot="table-row"
      className={cn(
        "border-b transition-colors hover:bg-muted/50 data-[state=selected]:bg-muted",
        className,
      )}
      {...props}
    />
  )
}

function TableHead({ className, ...props }: React.ComponentProps<"th">) {
  return (
    <th
      data-slot="table-head"
      className={cn(
        "h-10 whitespace-nowrap px-3 text-left align-middle font-medium text-muted-foreground [&:has([role=checkbox])]:pr-0",
        className,
      )}
      {...props}
    />
  )
}

function TableCell({ className, ...props }: React.ComponentProps<"td">) {
  return (
    <td
      data-slot="table-cell"
      className={cn(
        "whitespace-nowrap p-3 align-middle [&:has([role=checkbox])]:pr-0",
        className,
      )}
      {...props}
    />
  )
}

function TableCaption({ className, ...props }: React.ComponentProps<"caption">) {
  return (
    <caption
      data-slot="table-caption"
      className={cn("mt-4 text-sm text-muted-foreground", className)}
      {...props}
    />
  )
}

export {
  Table,
  TableHeader,
  TableBody,
  TableFooter,
  TableHead,
  TableRow,
  TableCell,
  TableCaption,
}
