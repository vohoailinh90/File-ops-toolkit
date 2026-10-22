import { FileSpreadsheet, Upload } from "lucide-react"
import * as React from "react"

import { StatusBadge } from "@/components/dashboard/status-badge"
import { useI18n } from "@/components/i18n-provider"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { api, ApiError, type UploadInfo } from "@/lib/api"
import { toneOf } from "@/lib/status"
import { cn } from "@/lib/utils"

const PREVIEW_ROWS = 8

export function UploadCard({
  info,
  disabled,
  onLoaded,
}: {
  info: UploadInfo | null
  disabled: boolean
  onLoaded: (info: UploadInfo) => void
}) {
  const { t } = useI18n()
  const input = React.useRef<HTMLInputElement>(null)
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState("")
  const [dragging, setDragging] = React.useState(false)

  async function load(file: File | undefined) {
    if (!file || disabled) return
    setBusy(true)
    setError("")
    try {
      onLoaded(await api.upload(file))
    } catch (failure) {
      const code = failure instanceof ApiError ? failure.code : "generic"
      setError(t(`errors.${code}`))
    } finally {
      setBusy(false)
      if (input.current) input.current.value = ""
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("steps.upload")}</CardTitle>
        <CardDescription>{t("upload.hint")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <input
          ref={input}
          type="file"
          accept=".xlsx,.xlsm"
          className="sr-only"
          tabIndex={-1}
          aria-hidden
          onChange={(event) => void load(event.target.files?.[0])}
        />
        {info ? (
          <div className="flex flex-wrap items-center gap-3">
            <FileSpreadsheet className="size-5 text-muted-foreground" aria-hidden />
            <span className="font-medium break-all">{info.file}</span>
            <Badge variant="secondary">{t("upload.rows", { count: info.rows.length })}</Badge>
            <Badge variant="secondary">{t("upload.folders", { count: info.folders })}</Badge>
            {info.invalid > 0 && <Badge variant="destructive">{t("upload.invalid", { count: info.invalid })}</Badge>}
            <Button variant="outline" size="sm" disabled={disabled || busy} onClick={() => input.current?.click()}>
              {t("upload.change")}
            </Button>
          </div>
        ) : (
          <button
            type="button"
            disabled={disabled || busy}
            onClick={() => input.current?.click()}
            onDragOver={(event) => {
              event.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault()
              setDragging(false)
              void load(event.dataTransfer.files[0])
            }}
            className={cn(
              "flex w-full flex-col items-center gap-2 rounded-lg border border-dashed px-6 py-10 text-sm text-muted-foreground transition-colors hover:bg-muted/50 focus-visible:ring-2 focus-visible:ring-ring/40 outline-none",
              dragging && "border-primary bg-muted/50",
            )}
          >
            <Upload className="size-6" aria-hidden />
            {busy ? t("upload.reading") : t("upload.drop")}
          </button>
        )}
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        {info && (
          <div className="space-y-2">
            <Table className="table-fixed">
              <TableHeader>
                <TableRow>
                  <TableHead className="w-16">{t("table.row")}</TableHead>
                  <TableHead className="w-[44%]">{t("table.folder")}</TableHead>
                  <TableHead className="w-[26%]">{t("table.file")}</TableHead>
                  <TableHead>{t("table.status")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {info.rows.slice(0, PREVIEW_ROWS).map((row) => (
                  <TableRow key={row.row}>
                    <TableCell className="tabular-nums">{row.row}</TableCell>
                    <TableCell className="whitespace-normal break-all">{row.address}</TableCell>
                    <TableCell className="whitespace-normal break-all">{row.file_name}</TableCell>
                    <TableCell className="whitespace-normal">
                      {row.error && <StatusBadge tone={toneOf(row.error)}>{t(`status.${row.error}`)}</StatusBadge>}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {info.rows.length > PREVIEW_ROWS && (
              <p className="text-xs text-muted-foreground">
                {t("table.showing", { shown: PREVIEW_ROWS, total: info.rows.length })}
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
