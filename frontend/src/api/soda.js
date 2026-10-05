import axios from 'axios'
import { ElMessage } from 'element-plus'

const api = axios.create({
  baseURL: '/api/v1/soda',
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
    localStorage.removeItem('userInfo')
    window.location.href = '/login'
  }
  return Promise.reject(error)
})

export const getSodaStats = () => api.get('/stats')
export const getSodaFilters = () => api.get('/filters')
export const getSodaSongs = (params) => api.get('/songs', { params })
export const getSodaSong = (id) => api.get('/songs/' + id)
export const createSodaSong = (data) => api.post('/songs', data)
export const updateSodaSong = (id, data) => api.put('/songs/' + id, data)
export const deleteSodaSong = (id) => api.delete('/songs/' + id)
export const seedSodaSongs = (reset = false) => api.post('/seed', null, { params: { reset } })
