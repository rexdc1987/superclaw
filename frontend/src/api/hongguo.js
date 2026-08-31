import axios from 'axios'
import { ElMessage } from 'element-plus'

const api = axios.create({
  baseURL: '/api/v1/hongguo',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

const settingsApi = axios.create({
  baseURL: '/api/v1/settings',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

function attachAuth(config) {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = 'Bearer ' + token
  return config
}

api.interceptors.request.use(attachAuth)
settingsApi.interceptors.request.use(attachAuth)

function handleResponseError(error) {
  if (!error.config?.silent) {
    const msg = error.response?.data?.detail || error.message || '请求失败'
    ElMessage.error(msg)
  }
  if (error.response?.status === 401) {
    localStorage.removeItem('token')
    localStorage.removeItem('userInfo')
    window.location.href = '/login'
  }
  return Promise.reject(error)
}

api.interceptors.response.use((response) => response.data, handleResponseError)
settingsApi.interceptors.response.use((response) => response.data, handleResponseError)

export const createTask = (data) => api.post('/tasks', data)
export const getTasks = (params) => api.get('/tasks', { params })
export const getTask = (id) => api.get('/tasks/' + id)
export const updateTask = (id, data) => api.put('/tasks/' + id, data)
export const deleteTask = (id) => api.delete('/tasks/' + id)
export const startTask = (id) => api.post('/tasks/' + id + '/start')
export const pauseTask = (id) => api.post('/tasks/' + id + '/pause')
export const resumeTask = (id) => api.post('/tasks/' + id + '/resume')
export const stopTask = (id) => api.post('/tasks/' + id + '/stop')
export const runDebugStep = (id, step) => api.post('/tasks/' + id + '/debug/' + step, null, { timeout: 240000 })
export const runPrepareTask = (id) => api.post('/tasks/' + id + '/prepare-run', null, { timeout: 300000 })
export const runStageTask = (id, data) => api.post('/tasks/' + id + '/stage-run', data, { timeout: 90000 })
export const checkLogin = () => api.post('/check-login', null, { timeout: 240000 })
export const getDevices = () => api.get('/devices', { timeout: 90000 })
export const getMultiDevices = () => api.get('/multi/devices', { timeout: 300000 })
export const createMultiTasks = (data) => api.post('/multi/tasks', data)
export const getMultiRuns = (params, config = {}) => api.get('/multi/runs', { ...config, params })
export const getMultiRun = (runId, config = {}) => api.get('/multi/runs/' + runId, config)
export const startMultiRun = (runId) => api.post('/multi/runs/' + runId + '/start', null, { timeout: 300000 })
export const stopMultiRun = (runId) => api.post('/multi/runs/' + runId + '/stop', null, { timeout: 120000 })
export const getAISettings = () => settingsApi.get('/ai')
export const updateAISettings = (data) => settingsApi.put('/ai', data)
export const testAISettings = (data) => settingsApi.post('/ai/test', data, { timeout: 90000 })
export const getAIUsage = () => settingsApi.get('/ai/usage')
export const resetAIUsage = () => settingsApi.post('/ai/usage/reset')
export const getHongguoSettings = () => settingsApi.get('/hongguo')
export const updateHongguoSettings = (data) => settingsApi.put('/hongguo', data)

export const getRecords = (taskId, params) => api.get('/tasks/' + taskId + '/records', { params })
export const getLogs = (taskId, params, config = {}) => api.get('/tasks/' + taskId + '/logs', { ...config, params })

export const getTemplates = (params) => api.get('/templates', { params })
export const createTemplate = (data) => api.post('/templates', data)
export const updateTemplate = (id, data) => api.put('/templates/' + id, data)
export const deleteTemplate = (id) => api.delete('/templates/' + id)
