const terminalStatuses = new Set(['completed', 'failed', 'stopped'])

function parseTimestamp(value) {
  if (!value) return null
  const timestamp = new Date(value).getTime()
  return Number.isNaN(timestamp) ? null : timestamp
}

export function getTaskDurationSeconds(task, now = Date.now()) {
  if (!task?.started_at) return null

  const hasStoredDuration = task.duration_seconds !== null
    && task.duration_seconds !== undefined
    && task.duration_seconds !== ''
  const storedDuration = Number(task.duration_seconds)
  if (terminalStatuses.has(task.status) && hasStoredDuration && Number.isFinite(storedDuration) && storedDuration >= 0) {
    return Math.floor(storedDuration)
  }

  const startedAt = parseTimestamp(task.started_at)
  if (startedAt === null) return null

  const completedAt = parseTimestamp(task.completed_at)
  const endedAt = completedAt ?? now
  return Math.max(0, Math.floor((endedAt - startedAt) / 1000))
}

export function formatDurationSeconds(value) {
  if (value === null || value === undefined || value === '' || !Number.isFinite(Number(value))) return '-'

  const totalSeconds = Math.max(0, Math.floor(Number(value)))
  const days = Math.floor(totalSeconds / 86400)
  const hours = Math.floor((totalSeconds % 86400) / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  const clock = [hours, minutes, seconds].map((item) => String(item).padStart(2, '0')).join(':')

  return days > 0 ? `${days}天 ${clock}` : clock
}

export function formatTaskDuration(task, now = Date.now()) {
  return formatDurationSeconds(getTaskDurationSeconds(task, now))
}
