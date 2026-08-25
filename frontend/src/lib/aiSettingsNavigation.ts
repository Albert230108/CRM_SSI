export const AI_SETTINGS_RETURN_PARAM = 'from=ai-settings'
export const AI_SETTINGS_HUB_PATH = '/settings/ai-templates'

export function withAiSettingsReturn(path: string) {
  return path.includes('?') ? `${path}&${AI_SETTINGS_RETURN_PARAM}` : `${path}?${AI_SETTINGS_RETURN_PARAM}`
}

export function getAiSettingsReturnHref(search: string, fallback: string) {
  return new URLSearchParams(search).get('from') === 'ai-settings' ? AI_SETTINGS_HUB_PATH : fallback
}
