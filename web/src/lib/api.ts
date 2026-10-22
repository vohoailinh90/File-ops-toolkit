// Client for the local Python server (file_ops_toolkit/server.py). Every call carries the
// per-launch token the server put in the page; errors come back as catalog codes.

export type JobRow = { row: number; address: string; file_name: string; error: string | null }
export type UploadInfo = { file: string; rows: JobRow[]; invalid: number; folders: number }
export type FileResult = { source: string; dest: string; outcome: string; detail: string }
export type RowResult = {
  row: number
  address: string
  file_name: string
  status: string
  files: FileResult[]
  detail: string
  warning: string
}
export type RunState = "idle" | "running" | "done" | "cancelled" | "failed"
export type Status = {
  state: RunState
  total: number
  done: number
  counts: Record<string, number>
  copied_files: number
  next: number
  results: RowResult[]
  error: string
  elapsed: number
}
export type FsListing = { path: string; parent: string | null; entries: { name: string; path: string }[] }

export class ApiError extends Error {
  code: string
  constructor(code: string) {
    super(code)
    this.code = code
  }
}

function token(): string {
  const meta = document.querySelector<HTMLMetaElement>('meta[name="fot-token"]')
  return meta?.content ?? import.meta.env.VITE_FOT_TOKEN ?? ""
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "X-Token": token(), ...(init.headers as Record<string, string> | undefined) },
  })
  if (!response.ok) {
    let code = "generic"
    try {
      code = ((await response.json()) as { error?: string }).error ?? code
    } catch {
      // not JSON: keep the generic code
    }
    throw new ApiError(code)
  }
  return (await response.json()) as T
}

export const api = {
  upload: (file: File) =>
    call<UploadInfo>("/api/upload", { method: "POST", body: file, headers: { "X-File-Name": encodeURIComponent(file.name) } }),
  defaults: () => call<{ dest: string }>("/api/defaults"),
  fs: (path: string) => call<FsListing>(`/api/fs?path=${encodeURIComponent(path)}`),
  run: (options: { dest: string; recursive: boolean; layout: string }) =>
    call<{ ok: boolean }>("/api/run", { method: "POST", body: JSON.stringify(options) }),
  cancel: () => call<{ ok: boolean }>("/api/cancel", { method: "POST", body: "{}" }),
  status: (since: number) => call<Status>(`/api/status?since=${since}`),
  async downloadReport(lang: string) {
    const response = await fetch(`/api/report.csv?lang=${lang}`, { headers: { "X-Token": token() } })
    if (!response.ok) throw new ApiError("no_results")
    const url = URL.createObjectURL(await response.blob())
    const link = document.createElement("a")
    link.href = url
    link.download = "fetch-report.csv"
    link.click()
    URL.revokeObjectURL(url)
  },
}
