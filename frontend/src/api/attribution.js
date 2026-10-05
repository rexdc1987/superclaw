import axios from 'axios'
import { ElMessage } from 'element-plus'

const api = axios.create({
  baseURL: '/api/v1/attribution',
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

// 以下三个都是 admin-only 的只读接口：能看全部账号的机器与产出，跨租户。
// 机器档案 + 产出统计（含 by_owner / by_owner_effective 两种口径）
export const getAttributionMachines = () => api.get('/machines')
// 归属缺口：无主任务 / 无机器任务
export const getAttributionGaps = () => api.get('/gaps')
// 从历史任务反推归属建议，只给建议不改数据
export const getAttributionInference = () => api.get('/inference')
// 写操作：把机器绑定给某个账号。
// backfill=true 会顺带把这台机器上 owner_user_id=0 的历史任务认领过去。
export const bindMachine = (workerId, data, backfill = false) =>
  api.post('/machines/' + encodeURIComponent(workerId) + '/bind', data, { params: { backfill } })
