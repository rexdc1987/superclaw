import axios from 'axios'
import { ElMessage } from 'element-plus'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = 'Bearer ' + token
  return config
}, (error) => Promise.reject(error))

api.interceptors.response.use((response) => response.data, (error) => {
  const msg = error.response?.data?.detail || error.message || '请求失败'
  ElMessage.error(msg)
  if (error.response?.status === 401) {
    localStorage.removeItem('token')
    window.location.href = '/login'
  }
  return Promise.reject(error)
})

export default api

// Accounts
export const getAccounts = (params) => api.get('/accounts/', { params })
export const getAccount = (id) => api.get('/accounts/' + id)
export const createAccount = (data) => api.post('/accounts/', data)
export const updateAccount = (id, data) => api.put('/accounts/' + id, data)
export const deleteAccount = (id) => api.delete('/accounts/' + id)
export const batchDeleteAccounts = (ids) => api.post('/accounts/batch-delete', { ids })
export const batchUpdateAccountStatus = (ids, status) => api.post('/accounts/batch-status', { ids, status })

// Account Groups
export const getAccountGroups = () => api.get('/accounts/groups/')
export const createAccountGroup = (data) => api.post('/accounts/groups/', data)
export const deleteAccountGroup = (id) => api.delete('/accounts/groups/' + id)

// Account Health
export const getAccountHealthReport = () => api.get('/accounts/health/report')

// Tasks
export const getTasks = (params) => api.get('/tasks/', { params })
export const getTask = (id) => api.get('/tasks/' + id)
export const createTask = (data) => api.post('/tasks/', data)
export const updateTask = (id, data) => api.put('/tasks/' + id, data)
export const deleteTask = (id) => api.delete('/tasks/' + id)
export const startTask = (id) => api.post('/tasks/' + id + '/start')
export const pauseTask = (id) => api.post('/tasks/' + id + '/pause')
export const resumeTask = (id) => api.post('/tasks/' + id + '/resume')
export const cancelTask = (id) => api.post('/tasks/' + id + '/cancel')

// Leads
export const getLeads = (params) => api.get('/leads/', { params })
export const getLead = (id) => api.get('/leads/' + id)
export const createLead = (data) => api.post('/leads/', data)
export const updateLead = (id, data) => api.put('/leads/' + id, data)
export const deleteLead = (id) => api.delete('/leads/' + id)
export const exportLeads = () => api.get('/export/leads', { responseType: 'blob' })

// Playbooks
export const getPlaybooks = (params) => api.get('/playbooks/', { params })
export const getPlaybook = (id) => api.get('/playbooks/' + id)
export const createPlaybook = (data) => api.post('/playbooks/', data)
export const updatePlaybook = (id, data) => api.put('/playbooks/' + id, data)
export const deletePlaybook = (id) => api.delete('/playbooks/' + id)

// Users
export const getUsers = (params) => api.get('/users/', { params })
export const getUser = (id) => api.get('/users/' + id)
export const createUser = (data) => api.post('/users/', data)
export const updateUser = (id, data) => api.put('/users/' + id, data)
export const deleteUser = (id) => api.delete('/users/' + id)

// Keywords & Risk
export const getKeywords = (params) => api.get('/keywords/', { params })
export const createKeyword = (data) => api.post('/keywords/', data)
export const getRiskRules = () => api.get('/risk/')
export const createRiskRule = (data) => api.post('/risk/', data)

// Actions (Review queue)
export const getActions = (params) => api.get('/actions/', { params })
export const createAction = (data) => api.post('/actions/', data)

// Keyword Groups
export const getKeywordGroups = () => api.get('/keywords/groups')
export const createKeywordGroup = (data) => api.post('/keywords/groups', data)
export const updateKeywordGroup = (id, data) => api.put('/keywords/groups/' + id, data)
export const deleteKeywordGroup = (id) => api.delete('/keywords/groups/' + id)
export const getKeywordGroupDetail = (id) => api.get('/keywords/groups/' + id)
export const getGroupKeywords = (groupId) => api.get('/keywords/groups/' + groupId + '/keywords')
export const importKeywords = (groupId, data) => api.post('/keywords/groups/' + groupId + '/import', data)
export const getNextKeyword = (groupId) => api.get('/keywords/groups/' + groupId + '/next')
