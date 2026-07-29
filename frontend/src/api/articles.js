import axios from 'axios'

const client = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: 200000,
})

export const articleApi = {
  list(params = {}) {
    return client.get('/articles', { params }).then((response) => response.data)
  },
  tokenUsage() {
    return client.get('/articles/statistics/tokens').then((response) => response.data)
  },
  get(id) {
    return client.get(`/articles/${id}`).then((response) => response.data)
  },
  create(payload) {
    return client.post('/articles', payload).then((response) => response.data)
  },
  update(id, payload) {
    return client.put(`/articles/${id}`, payload).then((response) => response.data)
  },
  delete(id) {
    return client.delete(`/articles/${id}`)
  },
  generate(id) {
    return client
      .post(`/articles/${id}/generate`, null, { timeout: 360000 })
      .then((response) => response.data)
  },
  generateAsync(id) {
    return client
      .post(`/articles/${id}/generate-async`)
      .then((response) => response.data)
  },
  publishWechat(id) {
    return client
      .post(`/articles/${id}/wechat-publish`, null, { timeout: 600000 })
      .then((response) => response.data)
  },
  listPublishSchedules(id) {
    return client
      .get(`/articles/${id}/publish-schedules`)
      .then((response) => response.data)
  },
  scheduleWechatPublish(id, scheduledAt) {
    return client
      .post(`/articles/${id}/publish-schedules`, {
        platform: 'wechat',
        scheduled_at: scheduledAt,
      })
      .then((response) => response.data)
  },
  cancelPublishSchedule(articleId, scheduleId) {
    return client
      .delete(`/articles/${articleId}/publish-schedules/${scheduleId}`)
      .then((response) => response.data)
  },
  research(query, options = {}) {
    return client.post('/research/search', { query, ...options }).then((response) => response.data)
  },
  readSourceContent(source) {
    return client
      .post('/research/content', source, { timeout: 90000 })
      .then((response) => response.data)
  },
  suggestTitles(payload) {
    return client.post('/research/titles', payload).then((response) => response.data)
  },
  getSettings() {
    return client.get('/settings').then((response) => response.data)
  },
  listModelProfiles() {
    return client.get('/settings/profiles').then((response) => response.data)
  },
  createModelProfile(payload) {
    return client.post('/settings/profiles', payload).then((response) => response.data)
  },
  updateModelProfile(id, payload) {
    return client.put(`/settings/profiles/${id}`, payload).then((response) => response.data)
  },
  activateModelProfile(id) {
    return client.post(`/settings/profiles/${id}/activate`).then((response) => response.data)
  },
  updateSettings(payload) {
    return client.put('/settings', payload).then((response) => response.data)
  },
  testSettings(payload) {
    return client.post('/settings/test', payload).then((response) => response.data)
  },
  testWechat(payload) {
    return client.post('/settings/test-wechat', payload).then((response) => response.data)
  },
  searchImages(query, count = 10, page = 1, excludeUrls = [], engine = 'bing', preferClean = true) {
    return client.post('/media/search', {
      query,
      count,
      page,
      exclude_urls: excludeUrls,
      engine,
      prefer_clean: preferClean,
    }).then((response) => response.data)
  },
  listImageAssets() {
    return client.get('/media/assets').then((response) => response.data)
  },
  listImageAssetCategories() {
    return client.get('/media/categories').then((response) => response.data)
  },
  createImageAssetCategory(name) {
    return client.post('/media/categories', { name }).then((response) => response.data)
  },
  updateImageAssetCategory(id, name) {
    return client.patch(`/media/categories/${id}`, { name }).then((response) => response.data)
  },
  deleteImageAssetCategory(id) {
    return client.delete(`/media/categories/${id}`)
  },
  reorderImageAssetCategories(orderedIds) {
    return client.post('/media/categories/reorder', { ordered_ids: orderedIds }).then((response) => response.data)
  },
  saveImageAsset(payload) {
    return client.post('/media/assets', payload).then((response) => response.data)
  },
  updateImageAsset(id, payload) {
    return client.patch(`/media/assets/${id}`, payload).then((response) => response.data)
  },
  reorderImageAssets(orderedIds) {
    return client.post('/media/assets/reorder', { ordered_ids: orderedIds }).then((response) => response.data)
  },
  deleteImageAsset(id) {
    return client.delete(`/media/assets/${id}`)
  },
}

export function getApiError(error, fallback = '请求失败，请稍后重试') {
  if (error?.code === 'ECONNABORTED') {
    return '模型生成等待超时，请稍后重试；已经保存的草稿不会丢失'
  }
  return error?.response?.data?.detail || error?.message || fallback
}
