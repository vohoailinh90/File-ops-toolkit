import * as React from "react"

import { api, ApiError, type RowResult, type RunState, type Status } from "@/lib/api"

export type RunView = {
  state: RunState
  total: number
  done: number
  counts: Record<string, number>
  copiedFiles: number
  elapsed: number
  error: string
  results: RowResult[]
}

const EMPTY: RunView = {
  state: "idle",
  total: 0,
  done: 0,
  counts: {},
  copiedFiles: 0,
  elapsed: 0,
  error: "",
  results: [],
}

// Starts a run and polls the server for progress. Results arrive in pieces (`since`), and are kept by
// Excel row number. The server's list is append-only, so `since` stays valid for the whole run.
export function useRun() {
  const [view, setView] = React.useState<RunView>(EMPTY)
  const byRow = React.useRef(new Map<number, RowResult>())
  const since = React.useRef(0)
  const polling = React.useRef(false)

  const apply = React.useCallback((status: Status) => {
    for (const result of status.results) byRow.current.set(result.row, result)
    since.current = status.next
    setView({
      state: status.state,
      total: status.total,
      done: status.done,
      counts: status.counts,
      copiedFiles: status.copied_files,
      elapsed: status.elapsed,
      error: status.error,
      results: [...byRow.current.values()].sort((a, b) => a.row - b.row),
    })
    return status.state
  }, [])

  const poll = React.useCallback(async () => {
    if (polling.current) return
    polling.current = true
    let failures = 0
    try {
      for (;;) {
        try {
          const state = apply(await api.status(since.current))
          failures = 0
          if (state !== "running") break
        } catch (error) {
          // A blip must not hide a run that is still going: give up only after three failures in a row.
          if (++failures >= 3) {
            setView((current) => ({ ...current, state: "failed", error: error instanceof ApiError ? error.code : "generic" }))
            break
          }
        }
        await new Promise((resolve) => setTimeout(resolve, 500))
      }
    } finally {
      polling.current = false
    }
  }, [apply])

  const start = React.useCallback(
    async (options: { dest: string; recursive: boolean; layout: string }) => {
      byRow.current = new Map()
      since.current = 0
      setView({ ...EMPTY, state: "running" })
      await api.run(options)
      void poll()
    },
    [poll],
  )

  // A reloaded page asks the server what it is doing: a run in progress shows its progress and Cancel again,
  // and a finished run shows its results, instead of the page believing nothing is happening.
  React.useEffect(() => {
    void api.status(0).then(
      (status) => {
        if (status.state === "idle") return
        if (apply(status) === "running") void poll()
      },
      () => undefined,
    )
  }, [apply, poll])

  const cancel = React.useCallback(() => api.cancel(), [])
  const reset = React.useCallback(() => {
    byRow.current = new Map()
    since.current = 0
    setView(EMPTY)
  }, [])

  return { view, start, cancel, reset }
}
