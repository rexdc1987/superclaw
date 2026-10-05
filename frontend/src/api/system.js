import api from './index'

// Build & update metadata
export const getBuildInfo = () => api.get('/system/version')
export const checkUpdate = () => api.get('/system/update/check')
export const getUpdateStatus = () => api.get('/system/update/status')
export const downloadUpdate = (data) => api.post('/system/update/download', data || {})
export const applyUpdate = () => api.post('/system/update/apply')
