import type { StatusTone } from "@/components/dashboard/status-badge"

// A row's status code (the keys under `status` in the catalogs) to the badge's dot colour.
export function toneOf(status: string): StatusTone {
  switch (status) {
    case "copied":
      return "success"
    case "already_copied":
      return "info"
    case "not_found":
      return "warning"
    default:
      return "failed"
  }
}

export const PROBLEM_STATUSES = new Set(["copied", "already_copied"])
export const isProblem = (status: string) => !PROBLEM_STATUSES.has(status)
