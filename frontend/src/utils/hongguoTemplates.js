export function normalizeTemplateList(response) {
  if (Array.isArray(response)) return response
  return response?.items || response?.data || []
}

export function parseTemplateText(value) {
  return String(value || '')
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean)
}

export function resolveTemplateContents(savedTemplates, selectedIds, manualText) {
  const selected = new Set(selectedIds || [])
  const contents = (savedTemplates || [])
    .filter((item) => selected.has(item.id))
    .flatMap((item) => parseTemplateText(item.content))
  return [...new Set([...contents, ...parseTemplateText(manualText)])]
}

export function partitionTemplateContents(contents, savedTemplates) {
  const selectedIds = []
  const matchedContents = new Set()
  const requested = new Set((contents || []).map((item) => String(item || '').trim()).filter(Boolean))
  for (const item of savedTemplates || []) {
    const templateContents = parseTemplateText(item.content)
    if (templateContents.length && templateContents.every((content) => requested.has(content))) {
      selectedIds.push(item.id)
      templateContents.forEach((content) => matchedContents.add(content))
    }
  }
  return {
    selectedIds,
    manualText: [...requested].filter((item) => !matchedContents.has(item)).join('\n'),
  }
}

export function templateOptionLabel(item) {
  const name = String(item?.name || '').trim()
  return name || `未命名模板 #${item?.id || '-'}`
}
