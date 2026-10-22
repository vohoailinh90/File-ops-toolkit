import type { StatusTone } from "@/components/dashboard/status-badge"

// A row's status code (the keys under `status` in the catalogs) to the badge's dot colour.
export function toneOf(status: string): StatusTone {
  switch (status) {
    case "copied":
      return "success"
    case "already_copied":
      return "info"
    case "not_found":
    case "scan_incomplete":
      return "warning"
    default:
      return "failed"
  }
}

const OK_STATUSES = new Set(["copied", "already_copied"])
// A row needs attention when it did not copy, or copied from a search that could not look everywhere.
export const isProblem = (result: { status: string; warning: string }) =>
  !OK_STATUSES.has(result.status) || result.warning !== ""
