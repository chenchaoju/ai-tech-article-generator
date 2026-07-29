const JOBS_KEY = 'article-background-generation-jobs'
const PREFERENCES_KEY = 'article-studio-writing-preferences'

export function loadGenerationJobs() {
  try {
    const value = JSON.parse(localStorage.getItem(JOBS_KEY) || '[]')
    return Array.isArray(value) ? value.filter((item) => Number(item?.article_id)) : []
  } catch {
    return []
  }
}

export function saveGenerationJobs(jobs) {
  localStorage.setItem(JOBS_KEY, JSON.stringify(jobs))
  window.dispatchEvent(new CustomEvent('article-generation-jobs-changed'))
}

export function addGenerationJob(job) {
  const jobs = loadGenerationJobs().filter(
    (item) => Number(item.article_id) !== Number(job.article_id),
  )
  jobs.push({
    article_id: Number(job.article_id),
    title: job.title || '未命名文章',
    started_at: job.started_at || new Date().toISOString(),
  })
  saveGenerationJobs(jobs)
}

export function removeGenerationJob(articleId) {
  saveGenerationJobs(
    loadGenerationJobs().filter(
      (item) => Number(item.article_id) !== Number(articleId),
    ),
  )
}

export function saveWritingPreferences(articleType, writingStyle) {
  localStorage.setItem(
    PREFERENCES_KEY,
    JSON.stringify({
      article_type: String(articleType || '').trim(),
      writing_style: String(writingStyle || '').trim(),
    }),
  )
}

export function loadWritingPreferences() {
  try {
    const value = JSON.parse(localStorage.getItem(PREFERENCES_KEY) || '{}')
    return {
      article_type: String(value?.article_type || ''),
      writing_style: String(value?.writing_style || ''),
    }
  } catch {
    return { article_type: '', writing_style: '' }
  }
}

export function clearGeneratedWorkspace(articleId) {
  localStorage.removeItem(`article-studio-workspace-${articleId}`)
}
