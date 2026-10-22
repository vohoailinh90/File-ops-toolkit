import { Download, Play, Square } from "lucide-react"
import * as React from "react"

import { StatusBadge } from "@/components/dashboard/status-badge"
import { useI18n } from "@/components/i18n-provider"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import type { RunView } from "@/hooks/use-run"
import { api } from "@/lib/api"
import { isProblem, toneOf } from "@/lib/status"

const PAGE = 200

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-2xl font-semibold tabular-nums">{value}</div>
    </div>
  )
}

export function RunCard({
  view,
  canStart,
  message,
  onStart,
  onCancel,
}: {
  view: RunView
  canStart: boolean
  message: string
  onStart: () => void
  onCancel: () => void
}) {
  const { t, locale } = useI18n()
  const [filter, setFilter] = React.useState("all")
  const [shown, setShown] = React.useState(PAGE)
  const running = view.state === "running"
  const problems = view.results.filter((r) => isProblem(r.status)).length
  const rows = React.useMemo(
    () => (filter === "problems" ? view.results.filter((r) => isProblem(r.status)) : view.results),
    [filter, view.results],
  )
  const percent = view.total ? Math.round((view.done / view.total) * 100) : 0
  const finished = view.state === "done" || view.state === "cancelled"

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("steps.run")}</CardTitle>
        <CardDescription aria-live="polite">
          {running && t("run.running")}
          {view.state === "done" && t("run.done")}
          {view.state === "cancelled" && t("run.cancelled")}
          {view.state === "failed" &&
            t("run.failed", { message: /^[a-z_]+$/.test(view.error) ? t(`errors.${view.error}`) : view.error })}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="flex flex-wrap items-center gap-3">
          {running ? (
            <Button variant="outline" onClick={onCancel}>
              <Square />
              {t("run.cancel")}
            </Button>
          ) : (
            <Button disabled={!canStart} onClick={onStart}>
              <Play />
              {t("run.start")}
            </Button>
          )}
          {message && !running && <p className="text-sm text-muted-foreground">{message}</p>}
        </div>

        {view.state !== "idle" && (
          <>
            <div className="space-y-1">
              <div
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={percent}
                aria-label={t("run.progress", { done: view.done, total: view.total })}
                className="h-2 overflow-hidden rounded-full bg-muted"
              >
                <div className="h-full bg-primary transition-[width]" style={{ width: `${percent}%` }} />
              </div>
              <p className="text-xs text-muted-foreground tabular-nums">
                {t("run.progress", { done: view.done, total: view.total })} · {t("run.elapsed", { seconds: view.elapsed })}
              </p>
            </div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Stat label={t("stats.rows")} value={view.done} />
              <Stat label={t("stats.copied")} value={view.copiedFiles} />
              <Stat label={t("stats.not_found")} value={view.counts.not_found ?? 0} />
              <Stat label={t("stats.problems")} value={problems} />
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3">
              <Tabs value={filter} onValueChange={(next) => { setFilter(next); setShown(PAGE) }}>
                <TabsList>
                  <TabsTrigger value="all">{t("results.all")}</TabsTrigger>
                  <TabsTrigger value="problems">{t("results.problems")}</TabsTrigger>
                </TabsList>
              </Tabs>
              <Button variant="outline" size="sm" disabled={!finished} onClick={() => void api.downloadReport(locale)}>
                <Download />
                {t("results.export")}
              </Button>
            </div>

            {rows.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("results.empty")}</p>
            ) : (
              <Table className="table-fixed">
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-16">{t("table.row")}</TableHead>
                    <TableHead className="w-[38%]">{t("table.file")}</TableHead>
                    <TableHead className="w-44">{t("table.status")}</TableHead>
                    <TableHead>{t("table.files")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.slice(0, shown).map((row) => (
                    <TableRow key={row.row}>
                      <TableCell className="tabular-nums">{row.row}</TableCell>
                      <TableCell className="whitespace-normal break-all">
                        {row.file_name}
                        <div className="text-xs text-muted-foreground break-all">{row.address}</div>
                      </TableCell>
                      <TableCell className="whitespace-normal">
                        <StatusBadge tone={toneOf(row.status)}>{t(`status.${row.status}`)}</StatusBadge>
                        {row.detail && <div className="mt-1 text-xs text-muted-foreground">{row.detail}</div>}
                      </TableCell>
                      <TableCell className="whitespace-normal text-xs break-all">
                        {row.files.map((file) => (
                          <div key={file.source}>{file.dest || file.source}</div>
                        ))}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
            {rows.length > shown && (
              <div className="flex items-center gap-3">
                <p className="text-xs text-muted-foreground">{t("table.showing", { shown, total: rows.length })}</p>
                <Button variant="outline" size="sm" onClick={() => setShown(shown + PAGE)}>
                  {t("table.show_more")}
                </Button>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
