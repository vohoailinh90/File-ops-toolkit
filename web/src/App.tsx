import { FolderInput } from "lucide-react"
import * as React from "react"

import { DestinationCard, type DestinationValue } from "@/components/destination-card"
import { useI18n } from "@/components/i18n-provider"
import { LanguageToggle } from "@/components/language-toggle"
import { RunCard } from "@/components/run-card"
import { ThemeToggle } from "@/components/theme-toggle"
import { UploadCard } from "@/components/upload-card"
import { useRun } from "@/hooks/use-run"
import { api, ApiError, type UploadInfo } from "@/lib/api"

export default function App() {
  const { t } = useI18n()
  const { view, start, cancel, reset } = useRun()
  const [info, setInfo] = React.useState<UploadInfo | null>(null)
  const [target, setTarget] = React.useState<DestinationValue>({ dest: "", recursive: true, layout: "flat" })
  const [message, setMessage] = React.useState("")
  const running = view.state === "running"

  React.useEffect(() => {
    void api.defaults().then(
      ({ dest }) => setTarget((current) => (current.dest ? current : { ...current, dest })),
      () => undefined,
    )
  }, [])

  async function begin() {
    if (!info) return setMessage(t("run.need_list"))
    if (!target.dest.trim()) return setMessage(t("run.need_dest"))
    setMessage("")
    try {
      await start({ ...target, dest: target.dest.trim() })
    } catch (failure) {
      reset()
      setMessage(t(`errors.${failure instanceof ApiError ? failure.code : "generic"}`))
    }
  }

  return (
    <div className="min-h-svh bg-background text-foreground">
      <header className="border-b">
        <div className="mx-auto flex max-w-5xl items-center gap-3 px-4 py-3">
          <FolderInput className="size-6" aria-hidden />
          <div className="min-w-0 flex-1">
            <h1 className="text-lg font-semibold leading-tight">{t("app.title")}</h1>
            <p className="text-sm text-muted-foreground">{t("app.subtitle")}</p>
          </div>
          <LanguageToggle />
          <ThemeToggle />
        </div>
      </header>
      <main className="mx-auto max-w-5xl space-y-6 px-4 py-6">
        <UploadCard
          info={info}
          disabled={running}
          onLoaded={(loaded) => {
            setInfo(loaded)
            setMessage("")
            reset()
          }}
        />
        <DestinationCard value={target} disabled={running} onChange={setTarget} />
        <RunCard
          view={view}
          canStart={!!info && !running}
          message={message}
          onStart={() => void begin()}
          onCancel={() => void cancel()}
        />
      </main>
    </div>
  )
}
