import { FolderOpen } from "lucide-react"
import * as React from "react"

import { FolderPicker } from "@/components/folder-picker"
import { useI18n } from "@/components/i18n-provider"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"

export type DestinationValue = { dest: string; recursive: boolean; layout: string }

export function DestinationCard({
  value,
  disabled,
  onChange,
}: {
  value: DestinationValue
  disabled: boolean
  onChange: (value: DestinationValue) => void
}) {
  const { t } = useI18n()
  const [picking, setPicking] = React.useState(false)
  const id = React.useId()

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("steps.dest")}</CardTitle>
        <CardDescription>{t("dest.hint")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="space-y-2">
          <Label htmlFor={`${id}-dest`}>{t("dest.label")}</Label>
          <div className="flex gap-2">
            <Input
              id={`${id}-dest`}
              value={value.dest}
              disabled={disabled}
              placeholder={t("dest.placeholder")}
              spellCheck={false}
              onChange={(event) => onChange({ ...value, dest: event.target.value })}
            />
            <Button variant="outline" disabled={disabled} onClick={() => setPicking(true)}>
              <FolderOpen />
              {t("dest.browse")}
            </Button>
          </div>
        </div>
        <div className="flex items-start gap-3">
          <Switch
            id={`${id}-recursive`}
            checked={value.recursive}
            disabled={disabled}
            onCheckedChange={(recursive) => onChange({ ...value, recursive })}
          />
          <div className="space-y-1">
            <Label htmlFor={`${id}-recursive`}>{t("dest.recursive")}</Label>
            <p className="text-xs text-muted-foreground">{t("dest.recursive_hint")}</p>
          </div>
        </div>
        <div className="space-y-2">
          <Label htmlFor={`${id}-layout`}>{t("dest.layout")}</Label>
          <Select value={value.layout} disabled={disabled} onValueChange={(layout) => onChange({ ...value, layout })}>
            <SelectTrigger id={`${id}-layout`} className="w-full sm:w-80">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="flat">{t("dest.layout_flat")}</SelectItem>
              <SelectItem value="by_folder">{t("dest.layout_by_folder")}</SelectItem>
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">{t("dest.layout_hint")}</p>
        </div>
      </CardContent>
      <FolderPicker
        open={picking}
        start={value.dest}
        onOpenChange={setPicking}
        onPick={(dest) => onChange({ ...value, dest })}
      />
    </Card>
  )
}
