export type AiTemplateOption = {
  id: number
  name: string
}

export type TenantTemplateSettings = {
  available_template_ids: number[]
  default_email_template_id: number | null
  default_whatsapp_template_id: number | null
  auto_draft_email: boolean
  auto_draft_whatsapp: boolean
  auto_send_email: boolean
  auto_send_whatsapp: boolean
  planner_mode?: 'off' | 'manual' | 'auto-draft' | 'auto-send'
}

type TenantAiSettingsControlsProps<T extends TenantTemplateSettings> = {
  templates: AiTemplateOption[]
  settings: T
  onChange: (settings: T) => void
  idPrefix: string
}

export default function TenantAiSettingsControls<T extends TenantTemplateSettings>({
  templates,
  settings,
  onChange,
  idPrefix,
}: TenantAiSettingsControlsProps<T>) {
  const update = (changes: Partial<TenantTemplateSettings>) => onChange({ ...settings, ...changes })

  const toggleAvailableTemplate = (templateId: number) => {
    const isAvailable = settings.available_template_ids.includes(templateId)
    const availableTemplateIds = isAvailable
      ? settings.available_template_ids.filter((id) => id !== templateId)
      : [...settings.available_template_ids, templateId]
    update({
      available_template_ids: availableTemplateIds,
      default_email_template_id:
        isAvailable && settings.default_email_template_id === templateId ? null : settings.default_email_template_id,
      default_whatsapp_template_id:
        isAvailable && settings.default_whatsapp_template_id === templateId ? null : settings.default_whatsapp_template_id,
    })
  }

  const setAutoDraft = (channel: 'email' | 'whatsapp', value: boolean) => {
    update({
      [channel === 'email' ? 'auto_draft_email' : 'auto_draft_whatsapp']: value,
      ...(value ? {} : { [channel === 'email' ? 'auto_send_email' : 'auto_send_whatsapp']: false }),
    })
  }

  const setAutoSend = (channel: 'email' | 'whatsapp', value: boolean) => {
    const draftEnabled = channel === 'email' ? settings.auto_draft_email : settings.auto_draft_whatsapp
    if (value && (!draftEnabled || settings.planner_mode === 'auto-draft')) return
    update({ [channel === 'email' ? 'auto_send_email' : 'auto_send_whatsapp']: value })
  }

  const plannerControlsDrafting = settings.planner_mode === 'auto-draft' || settings.planner_mode === 'auto-send'
  const availableTemplates = templates.filter((template) => settings.available_template_ids.includes(template.id))

  const renderAutomation = (channel: 'email' | 'whatsapp') => {
    const isEmail = channel === 'email'
    const autoDraft = isEmail ? settings.auto_draft_email : settings.auto_draft_whatsapp
    const autoSend = isEmail ? settings.auto_send_email : settings.auto_send_whatsapp
    const channelLabel = isEmail ? 'Email' : 'WhatsApp'
    return (
      <div className="rounded-xl border border-gray-200 p-2.5">
        <p className="text-sm font-semibold text-gray-900">{channelLabel} automation</p>
        <label className="mt-1.5 flex items-center gap-3 text-sm text-gray-700">
          <input
            type="checkbox"
            checked={autoDraft}
            disabled={plannerControlsDrafting}
            onChange={(event) => setAutoDraft(channel, event.target.checked)}
            className="h-4 w-4 rounded border-gray-300 disabled:cursor-not-allowed"
          />
          {plannerControlsDrafting
            ? `Auto-draft on new ${isEmail ? 'email' : 'WhatsApp message'} (required by Planner mode)`
            : `Auto-draft on new ${isEmail ? 'email' : 'WhatsApp message'}`}
        </label>
        <label className="mt-1.5 flex items-center gap-3 text-sm text-gray-700">
          <input
            type="checkbox"
            checked={autoSend}
            disabled={!autoDraft || settings.planner_mode === 'auto-draft'}
            onChange={(event) => setAutoSend(channel, event.target.checked)}
            className="h-4 w-4 rounded border-gray-300 disabled:cursor-not-allowed"
          />
          {settings.planner_mode === 'auto-draft'
            ? 'Auto-send (disabled by Auto-draft mode)'
            : 'Auto-send (requires auto-draft)'}
        </label>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">Available templates</p>
        <div className="mt-1.5 space-y-1.5">
          {templates.map((template) => (
            <label key={template.id} className="flex items-center gap-3 text-sm text-gray-700">
              <input
                type="checkbox"
                checked={settings.available_template_ids.includes(template.id)}
                onChange={() => toggleAvailableTemplate(template.id)}
                className="h-4 w-4 rounded border-gray-300"
              />
              {template.name}
            </label>
          ))}
          {!templates.length ? <p className="text-sm text-gray-500">No shared templates yet. Add one in Settings.</p> : null}
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {(['email', 'whatsapp'] as const).map((channel) => (
          <div key={channel}>
            <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor={`${idPrefix}-${channel}-template`}>
              Default template - {channel === 'email' ? 'Email' : 'WhatsApp'}
            </label>
            <select
              id={`${idPrefix}-${channel}-template`}
              value={(channel === 'email' ? settings.default_email_template_id : settings.default_whatsapp_template_id) ?? ''}
              onChange={(event) => update({
                [channel === 'email' ? 'default_email_template_id' : 'default_whatsapp_template_id']:
                  event.target.value ? Number(event.target.value) : null,
              })}
              className="mt-1.5 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-brand-500"
            >
              <option value="">No default</option>
              {availableTemplates.map((template) => (
                <option key={template.id} value={template.id}>{template.name}</option>
              ))}
            </select>
          </div>
        ))}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {renderAutomation('email')}
        {renderAutomation('whatsapp')}
      </div>
    </div>
  )
}
