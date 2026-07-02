const EVENT_URL = '/api/v1/client-events'
const MAX_DETAIL_LENGTH = 1200

function sessionId() {
  const key = 'superclaw_client_session_id'
  let value = sessionStorage.getItem(key)
  if (!value) {
    value = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
    sessionStorage.setItem(key, value)
  }
  return value
}

function currentUser() {
  try {
    const userInfo = JSON.parse(localStorage.getItem('userInfo') || '{}')
    return userInfo.username || userInfo.name || ''
  } catch {
    return ''
  }
}

function trimDetail(value) {
  if (typeof value === 'string') return value.slice(0, MAX_DETAIL_LENGTH)
  if (Array.isArray(value)) return value.slice(0, 50).map(trimDetail)
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value)
        .slice(0, 80)
        .map(([key, item]) => [String(key).slice(0, 80), trimDetail(item)])
    )
  }
  return value
}

export function logClientEvent(eventType, detail = {}, message = '') {
  const payload = {
    event_type: eventType,
    route: window.location.pathname + window.location.search,
    session_id: sessionId(),
    user: currentUser(),
    message: String(message || '').slice(0, 500),
    detail: trimDetail(detail),
    created_at: new Date().toISOString(),
  }
  const body = JSON.stringify(payload)
  try {
    if (navigator.sendBeacon) {
      const blob = new Blob([body], { type: 'application/json' })
      if (navigator.sendBeacon(EVENT_URL, blob)) return
    }
    fetch(EVENT_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      keepalive: true,
    }).catch(() => {})
  } catch {
    // Logging must never break user workflows.
  }
}

function targetLabel(target) {
  const element = target?.closest?.('button, a, .el-button, .el-menu-item, [data-log-action]')
  if (!element) return null
  const text = (element.innerText || element.getAttribute('aria-label') || element.getAttribute('title') || '')
    .replace(/\s+/g, ' ')
    .trim()
  return {
    tag: element.tagName,
    text: text.slice(0, 120),
    action: element.getAttribute('data-log-action') || '',
    path: window.location.pathname,
  }
}

export function installClientLogger(app, router) {
  logClientEvent('app_loaded', {
    userAgent: navigator.userAgent,
    language: navigator.language,
    viewport: `${window.innerWidth}x${window.innerHeight}`,
  })

  router.afterEach((to, from) => {
    logClientEvent('route_change', {
      from: from.fullPath,
      to: to.fullPath,
      title: to.meta?.title || '',
    })
  })

  app.config.errorHandler = (error, instance, info) => {
    logClientEvent('vue_error', {
      message: error?.message || String(error),
      stack: error?.stack || '',
      info,
      component: instance?.type?.name || '',
    })
    console.error(error)
  }

  window.addEventListener('error', (event) => {
    logClientEvent('window_error', {
      message: event.message,
      source: event.filename,
      line: event.lineno,
      column: event.colno,
      stack: event.error?.stack || '',
    })
  })

  window.addEventListener('unhandledrejection', (event) => {
    logClientEvent('unhandled_rejection', {
      reason: event.reason?.message || String(event.reason || ''),
      stack: event.reason?.stack || '',
    })
  })

  document.addEventListener(
    'click',
    (event) => {
      const label = targetLabel(event.target)
      if (label) logClientEvent('ui_click', label, label.text)
    },
    true
  )
}
