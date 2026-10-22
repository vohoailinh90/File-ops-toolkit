import { ArrowUp, Folder } from "lucide-react"
import * as React from "react"

import { useI18n } from "@/components/i18n-provider"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { api, type FsListing } from "@/lib/api"

// Browser pages cannot read a folder path, so the server (which runs on this PC) lists folders.
export function FolderPicker({
  open,
  start,
  onOpenChange,
  onPick,
}: {
  open: boolean
  start: string
  onOpenChange: (open: boolean) => void
  onPick: (path: string) => void
}) {
  const { t } = useI18n()
  const [listing, setListing] = React.useState<FsListing | null>(null)
  const [error, setError] = React.useState(false)

  const go = React.useCallback(async (path: string) => {
    try {
      setListing(await api.fs(path))
      setError(false)
    } catch {
      setError(true)
    }
  }, [])

  React.useEffect(() => {
    if (!open) return
    void api.fs(start).then(
      (found) => {
        setListing(found)
        setError(false)
      },
      () => void go(""),
    )
  }, [open, start, go])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t("picker.title")}</DialogTitle>
          <DialogDescription className="break-all">
            {listing?.path || t("picker.drives")}
          </DialogDescription>
        </DialogHeader>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {t("picker.error")}
          </p>
        )}
        <div className="max-h-72 overflow-y-auto rounded-md border" tabIndex={0} role="group" aria-label={t("picker.current")}>
          {listing?.path !== "" && listing && (
            <button
              type="button"
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted"
              onClick={() => void go(listing.parent ?? "")}
            >
              <ArrowUp className="size-4" aria-hidden />
              {t("picker.up")}
            </button>
          )}
          {listing?.entries.map((entry) => (
            <button
              key={entry.path}
              type="button"
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted"
              onClick={() => void go(entry.path)}
            >
              <Folder className="size-4 text-muted-foreground" aria-hidden />
              <span className="break-all">{entry.name}</span>
            </button>
          ))}
          {listing && listing.entries.length === 0 && (
            <p className="px-3 py-4 text-sm text-muted-foreground">{t("picker.empty")}</p>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("run.cancel")}
          </Button>
          <Button
            disabled={!listing?.path}
            onClick={() => {
              if (listing?.path) onPick(listing.path)
              onOpenChange(false)
            }}
          >
            {t("picker.select")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
