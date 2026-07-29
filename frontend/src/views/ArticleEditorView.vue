<script setup>
import {
  ArrowLeft,
  ArrowUpDown,
  CalendarDays,
  Check,
  ChevronDown,
  Clipboard,
  Eye,
  ExternalLink,
  FileText,
  Globe2,
  ImagePlus,
  Images,
  Link2,
  LockKeyhole,
  LogIn,
  LoaderCircle,
  PenLine,
  Plus,
  RefreshCw,
  Save,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  Trash2,
  X,
} from 'lucide-vue-next'
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { articleApi, getApiError } from '../api/articles'
import MarkdownContent from '../components/MarkdownContent.vue'
import NoticeToast from '../components/NoticeToast.vue'
import {
  addGenerationJob,
  loadWritingPreferences,
  saveWritingPreferences,
} from '../utils/generationJobs'
import { copyText } from '../utils/clipboard'
import { reviewChangeForDisplay } from '../utils/reviewDiff'

const TITLE_ANGLES = ['推荐', '贴近原文', '直叙', '自然', '简短', '信息型', '有温度', '具体', '轻巧', '克制']
const PUBLISH_PLATFORMS = [
  { value: '微信公众号', label: '公众号' },
  { value: 'CSDN', label: 'CSDN' },
  { value: '小红书', label: '小红书' },
  { value: '知乎', label: '知乎' },
  { value: '其他平台', label: '其他平台' },
]
const DEFAULT_SOURCE_SITES = [
  { id: 'all', name: '全网', domain: '', url: '' },
  {
    id: 'toutiao',
    name: '今日头条',
    domain: 'toutiao.com',
    url: 'https://www.toutiao.com/?wid=1784877606428',
  },
  { id: 'csdn', name: 'CSDN', domain: 'csdn.net', url: 'https://www.csdn.net/' },
  { id: 'juejin', name: '掘金', domain: 'juejin.cn', url: 'https://juejin.cn/' },
  { id: 'zhihu', name: '知乎', domain: 'zhihu.com', url: 'https://www.zhihu.com/' },
  { id: 'cnblogs', name: '博客园', domain: 'cnblogs.com', url: 'https://www.cnblogs.com/' },
]
const DEFAULT_WRITING_INSTRUCTION = '保留原文主题和观点，用更自然、更有人情味的方式重新叙述'
const savedWritingPreferences = loadWritingPreferences()

function loadCustomSites() {
  try {
    const value = JSON.parse(localStorage.getItem('article-custom-source-sites') || '[]')
    return Array.isArray(value)
      ? value
        .filter((site) => site?.id && site?.domain && site?.url)
        .map((site) => ({ ...site, name: site.name || site.domain }))
      : []
  } catch {
    return []
  }
}

function loadLoginStates() {
  try {
    const value = JSON.parse(localStorage.getItem('article-source-login-states') || '{}')
    return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
  } catch {
    return {}
  }
}

const route = useRoute()
const router = useRouter()
const articleId = ref(route.params.id ? Number(route.params.id) : null)
const loading = ref(Boolean(articleId.value))
const saving = ref(false)
const discovering = ref(false)
const loadingMore = ref(false)
const loadingTitles = ref(false)
const generating = ref(false)
const loadingSourceUrl = ref('')
const editorTab = ref('edit')
const manuscriptEditorRef = ref(null)
const libraryAssets = ref([])
const libraryCategories = ref([])
const selectedImageCategory = ref('全部')
const loadingLibraryAssets = ref(true)
const searchQuery = ref('')
const searchResults = ref([])
const titleSuggestions = ref([])
const titleHistory = ref([])
const customTitle = ref('')
const showCustomSite = ref(false)
const customSiteUrl = ref('')
const customSiteName = ref('')
const selectedSourceId = ref('all')
const sourceSort = ref('newest')
const sourceDateFilter = ref('all')
const customSites = ref(loadCustomSites())
const sourceLoginStates = ref(loadLoginStates())
const targetWordCountCustomized = ref(false)
const pendingLoginSiteId = ref('')
const notice = reactive({ message: '', type: 'success' })
const autosaveState = ref('正在准备自动保存')
const workspaceReady = ref(false)
let workspaceSaveTimer
let noticeTimer

const form = reactive({
  title: '',
  topic: '',
  article_type: savedWritingPreferences.article_type,
  custom_type_description: '',
  writing_style: savedWritingPreferences.writing_style || DEFAULT_WRITING_INSTRUCTION,
  layout_style: '跟随原文',
  target_word_count: 1500,
  target_platform: '微信公众号',
  custom_platform: '',
  project_background: '',
  problems: '',
  solution_process: '',
  author_voice: '',
  code_snippets: '',
  reference_materials: '',
  content: '',
  status: 'draft',
  selected_sources: [],
  include_source_images: false,
  manual_images: [],
  review_notes: '',
  director_review_summary: '',
  director_review_changes: [],
  director_reviewed_at: null,
  director_model_name: null,
  generated_word_count: 0,
  prompt_tokens: 0,
  completion_tokens: 0,
  total_tokens: 0,
})

const isEditing = computed(() => Boolean(articleId.value))
const isBackgroundGenerating = computed(() => form.status === 'generating')
const wordCount = computed(() => (form.content || '').replace(/\s/g, '').length)
const imageCategoryOptions = computed(() => {
  const names = [
    ...libraryCategories.value.map((item) => item.name),
    ...libraryAssets.value.map((item) => item.category || '未分类'),
  ].filter(Boolean)
  return ['全部', ...new Set(names)]
})
const filteredLibraryAssets = computed(() => (
  selectedImageCategory.value === '全部'
    ? libraryAssets.value
    : libraryAssets.value.filter(
      (item) => (item.category || '未分类') === selectedImageCategory.value,
    )
))
const canGenerate = computed(
  () => (
    form.topic.trim()
    && form.title.trim()
    && form.article_type.trim()
    && form.writing_style.trim()
    && (form.target_platform !== '其他平台' || form.custom_platform.trim())
    && Number(form.selected_sources[0]?.word_count || 0) >= 200
    && Boolean(form.selected_sources[0]?.source_content)
  ),
)
const sourceSites = computed(() => [...DEFAULT_SOURCE_SITES, ...customSites.value])
const selectedSourceSite = computed(
  () => sourceSites.value.find((site) => site.id === selectedSourceId.value) || DEFAULT_SOURCE_SITES[0],
)
const searchStrategyLabel = computed(() => {
  const domain = selectedSourceSite.value.domain || ''
  if (domain.endsWith('juejin.cn')) return '掘金站内模糊检索 · 最新优先'
  if (domain.endsWith('toutiao.com')) return '头条站内模糊检索 · 最新优先'
  if (domain.endsWith('csdn.net')) return 'CSDN 站内完整正文 · 最新优先'
  if (domain.endsWith('zhihu.com')) return '知乎深度正文提取 · 最新优先'
  if (domain.endsWith('cnblogs.com')) return '博客园正文专项提取 · 最新优先'
  if (domain) return '站点模糊检索 · 最新优先'
  return '全网深度检索 · 完整正文优先'
})
const pendingLoginSite = computed(
  () => sourceSites.value.find((site) => site.id === pendingLoginSiteId.value),
)
const visibleSearchResults = computed(() => {
  const now = Date.now()
  const days = {
    '7d': 7,
    '30d': 30,
    '1y': 365,
  }[sourceDateFilter.value]
  let items = [...searchResults.value]
  if (days) {
    const cutoff = now - days * 24 * 60 * 60 * 1000
    items = items.filter((item) => {
      if (item.date_type !== '发布日期') return false
      const value = Date.parse(item.publish_date || '')
      return Number.isFinite(value) && value >= cutoff
    })
  }
  if (sourceSort.value === 'newest') {
    items.sort((a, b) => {
      const aDate = a.date_type === '发布日期' ? Date.parse(a.publish_date || '') : 0
      const bDate = b.date_type === '发布日期' ? Date.parse(b.publish_date || '') : 0
      return (Number.isFinite(bDate) ? bDate : 0) - (Number.isFinite(aDate) ? aDate : 0)
    })
  } else {
    items.sort((a, b) => {
      const aDate = a.date_type === '发布日期' ? Date.parse(a.publish_date || '') : Number.NaN
      const bDate = b.date_type === '发布日期' ? Date.parse(b.publish_date || '') : Number.NaN
      if (!Number.isFinite(aDate)) return 1
      if (!Number.isFinite(bDate)) return -1
      return aDate - bDate
    })
  }
  return items
})
const manuscriptImageCount = computed(() => {
  const markdownImages = form.content.match(/!\[[^\]]*]\([^)]+\)/g)?.length || 0
  const htmlImages = form.content.match(/<img\b[^>]*>/gi)?.length || 0
  return markdownImages + htmlImages
})
const resolvedPlatformName = computed(
  () => (
    form.target_platform === '其他平台'
      ? (form.custom_platform.trim() || '其他平台')
      : form.target_platform
  ),
)
const displayReviewChanges = computed(() => {
  return (form.director_review_changes || [])
    .map(reviewChangeForDisplay)
    .filter(
      (change) => change.before.replace(/\s/g, '') !== change.after.replace(/\s/g, ''),
    )
})

function showNotice(message, type = 'success', duration = 0) {
  clearTimeout(noticeTimer)
  notice.message = message
  notice.type = type
  if (duration > 0) {
    noticeTimer = setTimeout(() => {
      notice.message = ''
    }, duration)
  }
}

function normalizeTargetWordCount() {
  const value = Number(form.target_word_count) || 1500
  form.target_word_count = Math.min(5000, Math.max(200, Math.round(value)))
}

function useSourceWordCountAsDefault(source) {
  if (targetWordCountCustomized.value) return
  const reportedWordCount = Number(source?.word_count)
  const sourceContentWordCount = String(source?.source_content || source?.summary || '')
    .replace(/\s/g, '')
    .length
  const sourceWordCount = Number.isFinite(reportedWordCount) && reportedWordCount > 0
    ? reportedWordCount
    : sourceContentWordCount
  if (!Number.isFinite(sourceWordCount) || sourceWordCount <= 0) return
  form.target_word_count = Math.min(5000, Math.max(200, Math.ceil(sourceWordCount * 1.1)))
}

async function addImageMaterial(material) {
  const url = material?.image_url || material?.url
  if (!url) return
  const imageRecord = {
    url,
    title: material.title || '图片素材',
    source: material.source_name || material.source || '图片素材库',
  }
  if (!form.manual_images.some((item) => item.url === url)) {
    form.manual_images.push(imageRecord)
  }
  if (form.content.includes(`](${url})`) || form.content.includes(url)) {
    showNotice('这张图片已经在正文中')
    return
  }
  editorTab.value = 'edit'
  await nextTick()
  const editor = manuscriptEditorRef.value
  const safeTitle = String(material.title || '文章图片').replace(/[[\]]/g, '')
  const block = `\n\n![${safeTitle}](${url})\n\n`
  const start = editor?.selectionStart ?? form.content.length
  const end = editor?.selectionEnd ?? start
  form.content = `${form.content.slice(0, start)}${block}${form.content.slice(end)}`
  await nextTick()
  editor?.focus()
  const cursor = start + block.length
  editor?.setSelectionRange(cursor, cursor)
  const saved = await persistArticleImages()
  if (saved) {
    showNotice('图片已加入正文并保存到文章')
  }
}

async function loadImageAssets() {
  try {
    const [assets, categories] = await Promise.all([
      articleApi.listImageAssets(),
      articleApi.listImageAssetCategories(),
    ])
    libraryAssets.value = assets
    libraryCategories.value = categories
    if (!imageCategoryOptions.value.includes(selectedImageCategory.value)) {
      selectedImageCategory.value = '全部'
    }
  } catch (error) {
    showNotice(getApiError(error, '图片素材库加载失败'), 'error')
  } finally {
    loadingLibraryAssets.value = false
  }
}

function imageCategoryCount(category) {
  if (category === '全部') return libraryAssets.value.length
  return libraryAssets.value.filter(
    (item) => (item.category || '未分类') === category,
  ).length
}

async function clearAllImageLinks() {
  form.content = form.content
    .replace(/!\[[^\]]*]\([^)]+\)/g, '')
    .replace(/<img\b[^>]*>/gi, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
  form.manual_images = []
  form.include_source_images = false
  const saved = await persistArticleImages()
  if (saved) {
    showNotice('已清除并保存文章中的全部图片链接')
  }
}

function workspaceKey(id = articleId.value) {
  return `article-studio-workspace-${id || 'new'}`
}

function normalizeWritingInstruction() {
  const style = String(form.writing_style || '').trim()
  const prompt = String(form.project_background || '').trim()
  const parts = [style, prompt].filter(Boolean)
  form.writing_style = (
    parts.length ? [...new Set(parts)].join('；') : DEFAULT_WRITING_INSTRUCTION
  ).slice(0, 1000)
  form.project_background = ''
}

function saveWorkspaceSnapshot() {
  if (!workspaceReady.value) return
  clearTimeout(workspaceSaveTimer)
  try {
    localStorage.setItem(
      workspaceKey(),
      JSON.stringify({
        saved_at: new Date().toISOString(),
        form: { ...form },
        search_query: searchQuery.value,
        search_results: searchResults.value,
        title_suggestions: titleSuggestions.value,
        title_history: titleHistory.value,
        custom_title: customTitle.value,
        selected_source_id: selectedSourceId.value,
        source_sort: sourceSort.value,
        source_date_filter: sourceDateFilter.value,
        editor_tab: editorTab.value,
      }),
    )
    autosaveState.value = `已自动保存 ${new Intl.DateTimeFormat('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    }).format(new Date())}`
  } catch {
    autosaveState.value = '本机自动保存空间不足，请点击保存'
  }
}

function queueWorkspaceSave() {
  if (!workspaceReady.value) return
  autosaveState.value = '正在自动保存…'
  clearTimeout(workspaceSaveTimer)
  workspaceSaveTimer = setTimeout(saveWorkspaceSnapshot, 250)
}

function restoreWorkspaceSnapshot() {
  try {
    const snapshot = JSON.parse(localStorage.getItem(workspaceKey()) || 'null')
    if (!snapshot?.form) return false
    Object.assign(form, snapshot.form)
    normalizeWritingInstruction()
    normalizeTargetWordCount()
    if (form.selected_sources.length > 1) {
      form.selected_sources.splice(0, form.selected_sources.length - 1)
    }
    searchQuery.value = snapshot.search_query || snapshot.form.topic || ''
    searchResults.value = Array.isArray(snapshot.search_results) ? snapshot.search_results : []
    titleSuggestions.value = Array.isArray(snapshot.title_suggestions) ? snapshot.title_suggestions : []
    titleHistory.value = Array.isArray(snapshot.title_history) ? snapshot.title_history : []
    customTitle.value = snapshot.custom_title || ''
    selectedSourceId.value = snapshot.selected_source_id || 'all'
    sourceSort.value = 'newest'
    sourceDateFilter.value = ['all', '7d', '30d', '1y'].includes(snapshot.source_date_filter)
      ? snapshot.source_date_filter
      : 'all'
    form.include_source_images = false
    editorTab.value = snapshot.editor_tab || 'edit'
    autosaveState.value = '已恢复上次未完成内容'
    return true
  } catch {
    return false
  }
}

function payload(statusOverride) {
  normalizeWritingInstruction()
  return {
    ...form,
    title: form.title.trim() || '未命名文章',
    topic: form.topic.trim(),
    layout_style: '跟随原文',
    project_background: '',
    status: statusOverride || form.status || 'draft',
  }
}

async function loadArticle() {
  if (!articleId.value) {
    restoreWorkspaceSnapshot()
    workspaceReady.value = true
    loading.value = false
    return
  }
  try {
    const data = await articleApi.get(articleId.value)
    Object.assign(form, data)
    normalizeWritingInstruction()
    normalizeTargetWordCount()
    form.layout_style = '跟随原文'
    searchQuery.value = data.topic
    restoreWorkspaceSnapshot()
    normalizeTargetWordCount()
    if (form.selected_sources.length > 1) {
      form.selected_sources.splice(0, form.selected_sources.length - 1)
    }
  } catch (error) {
    showNotice(getApiError(error, '文章加载失败'), 'error')
  } finally {
    workspaceReady.value = true
    loading.value = false
  }
}

async function persist(statusOverride = 'draft', quiet = false, navigate = true) {
  if (!form.topic.trim()) {
    showNotice('请先输入文章主题', 'error')
    return null
  }
  saving.value = true
  try {
    const previousWorkspaceKey = workspaceKey()
    const data = articleId.value
      ? await articleApi.update(articleId.value, payload(statusOverride))
      : await articleApi.create(payload(statusOverride))
    articleId.value = data.id
    Object.assign(form, data)
    if (previousWorkspaceKey !== workspaceKey()) {
      localStorage.removeItem(previousWorkspaceKey)
    }
    saveWorkspaceSnapshot()
    if (navigate && Number(route.params.id) !== data.id) {
      await router.replace(`/articles/${data.id}/edit`)
    }
    if (!quiet) showNotice('工作区已保存')
    return data
  } catch (error) {
    showNotice(getApiError(error, '保存失败'), 'error')
    return null
  } finally {
    saving.value = false
  }
}

async function persistArticleImages() {
  if (!form.topic.trim()) {
    showNotice('请先填写文章主题，再插入并保存图片', 'error')
    return false
  }
  saving.value = true
  try {
    const previousWorkspaceKey = workspaceKey()
    const data = articleId.value
      ? await articleApi.update(articleId.value, {
        content: form.content,
        manual_images: form.manual_images,
        include_source_images: false,
        status: form.status || 'draft',
      })
      : await articleApi.create(payload(form.status || 'draft'))
    articleId.value = data.id
    form.content = data.content
    form.manual_images = Array.isArray(data.manual_images) ? data.manual_images : []
    form.include_source_images = false
    if (previousWorkspaceKey !== workspaceKey()) {
      localStorage.removeItem(previousWorkspaceKey)
    }
    saveWorkspaceSnapshot()
    if (Number(route.params.id) !== data.id) {
      await router.replace(`/articles/${data.id}/edit`)
    }
    autosaveState.value = '图片已保存到文章'
    return true
  } catch (error) {
    showNotice(getApiError(error, '图片已插入编辑区，但保存到文章失败'), 'error')
    return false
  } finally {
    saving.value = false
  }
}

async function resetWorkspaceForNewArticle(preserveWritingPreferences = false) {
  const rememberedArticleType = preserveWritingPreferences ? form.article_type : ''
  const rememberedWritingStyle = preserveWritingPreferences
    ? form.writing_style
    : DEFAULT_WRITING_INSTRUCTION
  workspaceReady.value = false
  clearTimeout(workspaceSaveTimer)
  localStorage.removeItem(workspaceKey())
  articleId.value = null
  Object.assign(form, {
    title: '',
    topic: '',
    article_type: rememberedArticleType,
    custom_type_description: '',
    writing_style: rememberedWritingStyle,
    layout_style: '跟随原文',
    target_word_count: 1500,
    target_platform: '微信公众号',
    custom_platform: '',
    project_background: '',
    problems: '',
    solution_process: '',
    author_voice: '',
    code_snippets: '',
    reference_materials: '',
    content: '',
    status: 'draft',
    selected_sources: [],
    include_source_images: false,
    manual_images: [],
    review_notes: '',
    director_review_summary: '',
    director_review_changes: [],
    director_reviewed_at: null,
    director_model_name: null,
    model_name: null,
    reviewer_model_name: null,
    publish_records: [],
    generated_word_count: 0,
    prompt_tokens: 0,
    completion_tokens: 0,
    total_tokens: 0,
  })
  searchQuery.value = ''
  searchResults.value = []
  titleSuggestions.value = []
  titleHistory.value = []
  customTitle.value = ''
  selectedSourceId.value = 'all'
  sourceSort.value = 'newest'
  sourceDateFilter.value = 'all'
  editorTab.value = 'edit'
  targetWordCountCustomized.value = false
  autosaveState.value = '新稿件'
  await router.replace('/articles/new')
  await nextTick()
  workspaceReady.value = true
}

async function handleSaveAction() {
  if (['generated', 'published'].includes(form.status)) {
    const saved = await persist(form.status, true)
    if (saved) showNotice('文章修改已保存')
    return
  }
  const saved = await persist('draft', true, false)
  if (!saved) return
  await resetWorkspaceForNewArticle()
  showNotice('草稿已保存，创作台已清空，可以开始下一篇文章')
}

function usesMobileResearch() {
  return typeof window !== 'undefined' && window.matchMedia('(max-width: 780px)').matches
}

let researchRequestVersion = 0

function clearResearchQuery() {
  researchRequestVersion += 1
  titleRequestVersion += 1
  clearTimeout(selectedTitleRefreshTimer)
  searchQuery.value = ''
  searchResults.value = []
  titleSuggestions.value = []
  titleHistory.value = []
  customTitle.value = ''
  loadingSourceUrl.value = ''
  form.topic = ''
  form.title = ''
  form.selected_sources = []
  sourceSort.value = 'newest'
  sourceDateFilter.value = 'all'
  targetWordCountCustomized.value = false
  form.target_word_count = 1500
  discovering.value = false
  loadingTitles.value = false
  localStorage.removeItem(workspaceKey())
  autosaveState.value = '本次查询已清空'
}

function handleSearchQueryInput() {
  if (!searchQuery.value.trim()) clearResearchQuery()
}

async function discover(requestCount = 10, broadSearch = false) {
  requestCount = Number.isInteger(requestCount) ? requestCount : 10
  broadSearch = broadSearch === true
  const query = (searchQuery.value || form.topic).trim()
  if (!query) {
    showNotice('先输入想查找的主题或关键词', 'error')
    return
  }
  const requestVersion = ++researchRequestVersion
  form.topic = query
  sourceSort.value = 'newest'
  searchResults.value = []
  titleSuggestions.value = []
  form.title = ''
  form.selected_sources = []
  targetWordCountCustomized.value = false
  discovering.value = true
  loadingTitles.value = true
  let sourceError = null
  let titleError = null
  try {
    try {
      const sources = await articleApi.research(query, {
        count: requestCount,
        title_only: true,
        broad_search: broadSearch,
        exclude_urls: [],
        source_domain: selectedSourceSite.value.domain,
        source_name: selectedSourceSite.value.name,
        date_range: sourceDateFilter.value,
        sort_order: sourceSort.value,
      })
      if (requestVersion !== researchRequestVersion) return
      searchResults.value = sources.items
      if (sources.items.length < 5) {
        showNotice(
          `在${selectedSourceSite.value.name}只找到 ${sources.items.length} 篇相关文章，可以点“更多来源”或切换网站`,
          'error',
        )
      }
    } catch (error) {
      sourceError = error
    }

    try {
      const titles = await articleApi.suggestTitles({
        topic: query,
        article_type: form.article_type,
        custom_type_description: form.custom_type_description,
        writing_style: form.writing_style,
        layout_style: '跟随原文',
        excluded_titles: [],
        source_titles: searchResults.value.slice(0, 8).map((item) => item.title),
      })
      if (requestVersion !== researchRequestVersion) return
      titleSuggestions.value = titles.titles
      titleHistory.value = [...titles.titles]
      if (titles.titles.length && !form.title.trim()) form.title = titles.titles[0]
    } catch (error) {
      titleError = error
    }

    if (sourceError) {
      showNotice(getApiError(sourceError, '来源检索失败，但标题仍可继续选择'), 'error')
    } else if (titleError) {
      showNotice(getApiError(titleError, '标题准备失败，但来源已经显示'), 'error')
    }
  } finally {
    if (requestVersion === researchRequestVersion) {
      discovering.value = false
      loadingTitles.value = false
    }
  }
}

function discoverMobile() {
  return discover(20, true)
}

async function loadMoreSources(requestCount = 10, broadSearch = false) {
  requestCount = Number.isInteger(requestCount) ? requestCount : 10
  broadSearch = broadSearch === true
  loadingMore.value = true
  try {
    const data = await articleApi.research(form.topic, {
      count: requestCount,
      title_only: true,
      broad_search: broadSearch,
      exclude_urls: searchResults.value.map((item) => item.url),
      source_domain: selectedSourceSite.value.domain,
      source_name: selectedSourceSite.value.name,
      date_range: sourceDateFilter.value,
      sort_order: sourceSort.value,
    })
    const known = new Set(searchResults.value.map((item) => item.url))
    const fresh = data.items.filter((item) => !known.has(item.url))
    searchResults.value.push(...fresh)
    if (!fresh.length) showNotice('暂时没有更多不同来源，稍后换个关键词试试', 'error')
  } catch (error) {
    showNotice(getApiError(error, '加载更多来源失败'), 'error')
  } finally {
    loadingMore.value = false
  }
}

function loadMoreMobileSources() {
  return loadMoreSources(20, true)
}

async function refreshSourceFilters() {
  const query = (searchQuery.value || form.topic).trim()
  if (!query || discovering.value) return
  discovering.value = true
  try {
    const mobileResearch = usesMobileResearch()
    const data = await articleApi.research(query, {
      count: 20,
      title_only: true,
      broad_search: mobileResearch,
      exclude_urls: [],
      source_domain: selectedSourceSite.value.domain,
      source_name: selectedSourceSite.value.name,
      date_range: sourceDateFilter.value,
      sort_order: sourceSort.value,
    })
    searchResults.value = data.items
    const selectedUrl = form.selected_sources[0]?.url
    if (selectedUrl && !data.items.some((item) => item.url === selectedUrl)) {
      form.selected_sources = []
      form.title = ''
      titleSuggestions.value = []
    }
    if (!data.items.length) {
      showNotice(
        `当前日期范围内没有找到相关文章，请放宽时间范围`,
        'error',
      )
    } else {
      const orderLabel = sourceSort.value === 'oldest' ? '从旧到新' : '从新到旧'
      showNotice(`筛选已更新，共 ${data.items.length} 篇，按发布日期${orderLabel}排列`)
    }
  } catch (error) {
    showNotice(getApiError(error, '更新日期筛选失败'), 'error')
  } finally {
    discovering.value = false
  }
}

function selectSourceSite(site) {
  selectedSourceId.value = site.id
  sourceSort.value = 'newest'
  sourceDateFilter.value = 'all'
  searchResults.value = []
  if ((searchQuery.value || form.topic).trim()) {
    if (usesMobileResearch()) discoverMobile()
    else discover()
  }
}

function addCustomSite() {
  try {
    const name = customSiteName.value.trim()
    if (!name) {
      showNotice('请给这个网址填写一个便于识别的名称', 'error')
      return
    }
    const parsed = new URL(customSiteUrl.value.trim())
    const domain = parsed.hostname.replace(/^www\./, '')
    if (!domain) throw new Error('invalid')
    const normalizedUrl = parsed.toString().replace(/\/$/, '')
    const customIndex = customSites.value.findIndex(
      (site) => String(site.url || '').replace(/\/$/, '') === normalizedUrl,
    )
    if (customIndex >= 0) {
      customSites.value[customIndex] = {
        ...customSites.value[customIndex],
        name,
        domain,
        url: parsed.toString(),
      }
      localStorage.setItem('article-custom-source-sites', JSON.stringify(customSites.value))
      showCustomSite.value = false
      customSiteUrl.value = ''
      customSiteName.value = ''
      selectSourceSite(customSites.value[customIndex])
      showNotice(`已更新并显示网址“${name}”`)
      return
    }
    const site = {
      id: `custom-${Date.now()}`,
      name,
      domain,
      url: parsed.toString(),
    }
    customSites.value.push(site)
    localStorage.setItem('article-custom-source-sites', JSON.stringify(customSites.value))
    showCustomSite.value = false
    customSiteUrl.value = ''
    customSiteName.value = ''
    selectSourceSite(site)
    showNotice(`已保存网址“${name}”，现在可以从来源选项中选择`)
  } catch {
    showNotice('请输入完整网址，例如 https://www.toutiao.com/', 'error')
  }
}

function siteLoginKey(site) {
  return site?.domain || site?.id || ''
}

function isSiteLoggedIn(site) {
  return Boolean(sourceLoginStates.value[siteLoginKey(site)]?.confirmed)
}

function loginStateTime(site) {
  const value = sourceLoginStates.value[siteLoginKey(site)]?.confirmed_at
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

function beginSiteLogin(site) {
  pendingLoginSiteId.value = site.id
}

function confirmSiteLogin(site) {
  if (!site) return
  sourceLoginStates.value = {
    ...sourceLoginStates.value,
    [siteLoginKey(site)]: {
      confirmed: true,
      confirmed_at: new Date().toISOString(),
    },
  }
  localStorage.setItem('article-source-login-states', JSON.stringify(sourceLoginStates.value))
  pendingLoginSiteId.value = ''
  showNotice(`${site.name}登录状态已刷新并保存在本机浏览器`)
}

let titleRequestVersion = 0
async function reloadTitles() {
  if (!form.topic.trim()) {
    showNotice('请先输入文章主题', 'error')
    return
  }
  const requestVersion = ++titleRequestVersion
  loadingTitles.value = true
  try {
    const data = await articleApi.suggestTitles({
      topic: form.topic,
      article_type: form.article_type,
      custom_type_description: form.custom_type_description,
      writing_style: form.writing_style,
      layout_style: '跟随原文',
      excluded_titles: titleHistory.value.slice(-100),
      source_titles: (
        form.selected_sources.length ? form.selected_sources : searchResults.value
      ).slice(0, 8).map((item) => item.title),
    })
    if (requestVersion === titleRequestVersion) {
      titleSuggestions.value = data.titles
      titleHistory.value = [...titleHistory.value, ...data.titles].slice(-100)
      if (data.titles.length) form.title = data.titles[0]
    }
  } catch (error) {
    if (requestVersion === titleRequestVersion) {
      showNotice(getApiError(error, '标题生成失败'), 'error')
    }
  } finally {
    if (requestVersion === titleRequestVersion) loadingTitles.value = false
  }
}

function sourceSelected(source) {
  return form.selected_sources.some((item) => item.url === source.url)
}

async function toggleSource(source) {
  if (loadingSourceUrl.value) return
  const index = form.selected_sources.findIndex((item) => item.url === source.url)
  if (index >= 0) {
    form.selected_sources.splice(index, 1)
    targetWordCountCustomized.value = false
    return
  }
  loadingSourceUrl.value = source.url
  form.selected_sources.splice(0, form.selected_sources.length, {
    ...source,
    source_content: '',
  })
  showNotice('正在深度提取已选文章正文，请稍候')
  try {
    const hydrated = await articleApi.readSourceContent(source)
    const resultIndex = searchResults.value.findIndex((item) => item.url === source.url)
    if (resultIndex >= 0) searchResults.value.splice(resultIndex, 1, hydrated)
    form.selected_sources.splice(0, form.selected_sources.length, hydrated)
    useSourceWordCountAsDefault(hydrated)
    showNotice(`正文提取完成，共 ${hydrated.word_count.toLocaleString()} 字`)
    queueSelectedTitleRefresh()
  } catch (error) {
    form.selected_sources = []
    targetWordCountCustomized.value = false
    showNotice(getApiError(error, '正文提取失败，请选择另一篇文章'), 'error')
  } finally {
    loadingSourceUrl.value = ''
  }
}

let selectedTitleRefreshTimer
function queueSelectedTitleRefresh() {
  clearTimeout(selectedTitleRefreshTimer)
  if (!form.selected_sources.length) return
  selectedTitleRefreshTimer = setTimeout(reloadTitles, 700)
}

function addCustomTitle() {
  const value = customTitle.value.trim()
  if (!value) {
    showNotice('先写下你想使用的标题', 'error')
    return
  }
  form.title = value.slice(0, 255)
  if (!titleSuggestions.value.includes(form.title)) {
    titleSuggestions.value = [form.title, ...titleSuggestions.value].slice(0, 10)
  }
  if (!titleHistory.value.includes(form.title)) {
    titleHistory.value.push(form.title)
  }
  customTitle.value = ''
  showNotice('已加入并选中你的标题')
}

async function handleGenerate() {
  if (!form.article_type.trim() || !form.writing_style.trim()) {
    showNotice('请填写文章类型和表达风格', 'error')
    return
  }
  if (!canGenerate.value) {
    showNotice('请先选择标题和一篇参考文章', 'error')
    return
  }
  if (['generated', 'published'].includes(form.status)) {
    localStorage.removeItem(workspaceKey())
    articleId.value = null
    Object.assign(form, {
      content: '',
      status: 'draft',
      review_notes: '',
      director_review_summary: '',
      director_review_changes: [],
      director_reviewed_at: null,
      director_model_name: null,
      model_name: null,
      reviewer_model_name: null,
      publish_records: [],
      generated_word_count: 0,
      prompt_tokens: 0,
      completion_tokens: 0,
      total_tokens: 0,
    })
  }
  const saved = await persist('draft', true, false)
  if (!saved) return
  generating.value = true
  try {
    const queuedArticleId = articleId.value
    const queuedTitle = form.title
    saveWritingPreferences(form.article_type, form.writing_style)
    const result = await articleApi.generateAsync(queuedArticleId)
    addGenerationJob({
      article_id: result.article_id,
      title: queuedTitle,
    })
    form.status = 'generating'
    if (Number(route.params.id) !== queuedArticleId) {
      await router.replace(`/articles/${queuedArticleId}/edit`)
    }
    showNotice('文章正在后台生成，可以切换到其他页面', 'success', 2000)
  } catch (error) {
    showNotice(getApiError(error, '后台生成任务提交失败，草稿已经保留'), 'error')
  } finally {
    generating.value = false
  }
}

async function openPublishCenter() {
  if (form.status !== 'generated' || !form.content.trim()) {
    showNotice('请先完成文章生成，再进入发布中心', 'error')
    return
  }
  const saved = await persist('generated', true)
  if (!saved) return
  await router.push(`/articles/${articleId.value}/publish`)
}

async function copyMarkdown() {
  if (!form.content) return showNotice('暂无可复制的 Markdown', 'error')
  try {
    await copyText(form.content)
    showNotice('Markdown 已复制')
  } catch (error) {
    showNotice(error.message || '复制失败，请手动选择正文复制', 'error')
  }
}

async function handleBackgroundGenerationCompleted(event) {
  const completedArticle = event.detail?.article
  if (!completedArticle || Number(completedArticle.id) !== Number(articleId.value)) return
  await resetWorkspaceForNewArticle(true)
}

function handleBackgroundGenerationFailed(event) {
  const failedArticle = event.detail?.article
  if (!failedArticle || Number(failedArticle.id) !== Number(articleId.value)) return
  Object.assign(form, failedArticle)
  showNotice(failedArticle.review_notes || '后台生成失败，草稿已经保留', 'error')
}

onMounted(() => {
  loadArticle()
  loadImageAssets()
  window.addEventListener('article-generation-completed', handleBackgroundGenerationCompleted)
  window.addEventListener('article-generation-failed', handleBackgroundGenerationFailed)
})
watch(
  [
    form,
    searchQuery,
    searchResults,
    titleSuggestions,
    titleHistory,
    customTitle,
    selectedSourceId,
    sourceSort,
    sourceDateFilter,
    editorTab,
  ],
  queueWorkspaceSave,
  { deep: true },
)
onBeforeUnmount(() => {
  clearTimeout(noticeTimer)
  window.removeEventListener('article-generation-completed', handleBackgroundGenerationCompleted)
  window.removeEventListener('article-generation-failed', handleBackgroundGenerationFailed)
  saveWorkspaceSnapshot()
})
</script>

<template>
  <section class="studio-page">
    <div v-if="loading" class="loading-state full-height">
      <LoaderCircle class="spin" :size="25" />正在打开创作台…
    </div>

    <template v-else>
      <header class="studio-header">
        <div class="studio-breadcrumb">
          <RouterLink to="/articles"><ArrowLeft :size="15" />文章库</RouterLink>
          <span>/</span><strong>{{ isEditing ? `稿件 #${articleId}` : '新稿件' }}</strong>
          <small class="workspace-autosave-state"><Save :size="11" />{{ autosaveState }}</small>
        </div>
        <div class="workflow-rail">
          <span :class="{ done: searchResults.length }"><Search :size="12" />选题与来源</span>
          <span>→</span>
          <span :class="{ done: form.title }"><PenLine :size="12" />标题与风格</span>
          <span>→</span>
          <span :class="{ active: generating || isBackgroundGenerating, done: form.status === 'generated' }"><Sparkles :size="12" />专家</span>
          <span>→</span>
          <span :class="{ active: generating || isBackgroundGenerating, done: form.status === 'generated' }"><Sparkles :size="12" />写手</span>
          <span>→</span>
          <span :class="{ done: form.status === 'generated' }"><ShieldCheck :size="12" />审核官</span>
          <span>→</span>
          <span :class="{ done: form.status === 'generated' }"><ShieldCheck :size="12" />编辑总监</span>
        </div>
        <div class="studio-actions">
          <button class="button button-ghost" type="button" :disabled="saving || isBackgroundGenerating" @click="handleSaveAction">
            <LoaderCircle v-if="saving" class="spin" :size="15" /><Save v-else :size="15" />{{ ['generated', 'published'].includes(form.status) ? '保存修改' : '保存草稿' }}
          </button>
          <button
            v-if="form.status === 'generated' && form.content"
            class="button button-signal"
            type="button"
            :disabled="generating || saving"
            @click="openPublishCenter"
          >
            <Send :size="15" />发布
          </button>
          <button class="button button-signal" type="button" :disabled="generating || saving || isBackgroundGenerating" @click="handleGenerate">
            <LoaderCircle v-if="generating" class="spin" :size="15" /><Sparkles v-else :size="15" />
            {{ generating ? '正在提交后台任务…' : (isBackgroundGenerating ? '后台生成中…' : '生成文章') }}
          </button>
        </div>
      </header>

      <section class="mobile-research-first">
        <header>
          <span>01 / 先搜索文章</span>
          <h2>搜索并选择参考文章</h2>
          <p>先确定主题和原文，再继续选择类型、标题和表达方式。</p>
        </header>
        <div class="mobile-research-controls">
          <select v-model="selectedSourceId" aria-label="选择文章来源" @change="selectSourceSite(selectedSourceSite)">
            <option v-for="site in sourceSites" :key="site.id" :value="site.id">{{ site.name }}</option>
          </select>
          <div class="mobile-public-search-note">
            <Globe2 :size="14" />
            无需登录，直接检索公开文章；首次最多显示 20 篇，还可以继续加载。
          </div>
          <button class="mobile-custom-site-trigger" type="button" @click="showCustomSite = !showCustomSite">
            <Link2 :size="14" />{{ showCustomSite ? '收起自定义网址' : '添加自定义网址查找' }}
          </button>
          <div v-if="showCustomSite" class="custom-site-input mobile-custom-site-input">
            <Link2 :size="14" />
            <div class="custom-site-fields">
              <label><span>网站名称</span><input v-model="customSiteName" class="custom-site-name" placeholder="如：AI前线" /></label>
              <label><span>网站地址</span><input v-model="customSiteUrl" placeholder="https://example.com/" @keyup.enter="addCustomSite" /></label>
            </div>
            <button type="button" @click="addCustomSite">添加并查找</button>
            <button type="button" aria-label="关闭" @click="showCustomSite = false"><X :size="13" /></button>
          </div>
          <div class="research-input">
            <Search :size="17" />
            <input v-model="searchQuery" placeholder="输入文章标题或关键词" @input="handleSearchQueryInput" @keyup.enter="discoverMobile" />
            <button
              v-if="searchQuery"
              class="research-clear-button"
              type="button"
              aria-label="清空本次查询"
              title="清空本次查询"
              @click="clearResearchQuery"
            ><X :size="14" /></button>
            <button type="button" :disabled="discovering" @click="discoverMobile">
              <LoaderCircle v-if="discovering" class="spin" :size="15" />{{ discovering ? '查找中' : '查找' }}
            </button>
          </div>
          <div v-if="searchResults.length" class="mobile-source-filters">
            <label><CalendarDays :size="13" /><select v-model="sourceDateFilter" :disabled="discovering" @change="refreshSourceFilters">
              <option value="all">不限日期</option>
              <option value="7d">近 7 天</option>
              <option value="30d">近 30 天</option>
              <option value="1y">近 1 年</option>
            </select></label>
            <label><ArrowUpDown :size="13" /><select v-model="sourceSort" :disabled="discovering" @change="refreshSourceFilters">
              <option value="newest">日期从新到旧</option>
              <option value="oldest">日期从旧到新</option>
            </select></label>
          </div>
        </div>
        <div v-if="searchResults.length" class="mobile-source-list">
          <article
            v-for="(source, index) in visibleSearchResults"
            :key="source.url"
            class="mobile-source-card"
            :class="{ selected: sourceSelected(source) }"
          >
            <button type="button" :disabled="Boolean(loadingSourceUrl)" @click="toggleSource(source)">
              <span>{{ String(index + 1).padStart(2, '0') }}</span>
              <div>
                <small>
                  {{ source.source || '网页来源' }} · {{ source.publish_date || '日期未知' }} ·
                  {{ source.word_count ? `约 ${source.word_count.toLocaleString()} 字` : '选中后统计字数' }}
                </small>
                <strong>{{ source.title }}</strong>
                <p v-if="loadingSourceUrl === source.url">正在深度提取正文…</p>
                <p v-else>{{ sourceSelected(source) && source.source_content ? '正文已提取，可以生成文章' : '点击后提取完整正文' }}</p>
              </div>
              <LoaderCircle v-if="loadingSourceUrl === source.url" class="spin" :size="15" />
              <Check v-else :size="15" />
            </button>
            <a :href="source.url" target="_blank" rel="noreferrer"><ExternalLink :size="12" />打开原文</a>
          </article>
          <button class="mobile-more-sources" type="button" :disabled="loadingMore" @click="loadMoreMobileSources">
            <LoaderCircle v-if="loadingMore" class="spin" :size="14" /><Plus v-else :size="14" />
            {{ loadingMore ? '继续查找中…' : '查找更多文章' }}
          </button>
        </div>
        <div v-else class="mobile-research-empty">
          <Search :size="22" />输入主题后，查找到的文章会优先显示在这里。
        </div>
      </section>

      <div class="studio-grid preference-studio">
        <aside class="source-desk">
          <div class="desk-body guided-desk">
            <section class="choice-section topic-section">
              <div class="choice-heading"><span>01</span><div><strong>输入主题或关键词</strong><small>自动扩展相关说法，并优先显示最近发布的文章</small></div></div>
              <div class="source-picker-label"><Globe2 :size="13" />从哪里查找相似文章</div>
              <div class="source-site-picker">
                <div
                  v-for="site in sourceSites"
                  :key="site.id"
                  class="source-site-item"
                  :class="{ selected: selectedSourceId === site.id }"
                >
                  <button type="button" @click="selectSourceSite(site)">
                    <Check :size="11" />{{ site.name }}<i v-if="isSiteLoggedIn(site)" class="login-dot">已登录</i>
                  </button>
                  <a v-if="site.url" :href="site.url" target="_blank" rel="noreferrer" :aria-label="`打开${site.name}`" @click="beginSiteLogin(site)">
                    <ExternalLink :size="10" />
                  </a>
                </div>
                <button class="add-site-button" type="button" @click="showCustomSite = !showCustomSite">
                  <Plus :size="11" />添加网址
                </button>
              </div>
              <div class="cookie-safety-note">
                <LockKeyhole :size="13" />
                <span>
                  <strong>登录会话由浏览器保存</strong>点击网站旁的 ↗ 完成登录；重新登录后再点下方按钮刷新确认时间。系统不读取跨站 Cookie。
                  <small v-if="isSiteLoggedIn(selectedSourceSite)">当前已登录 · 最近刷新 {{ loginStateTime(selectedSourceSite) }}</small>
                </span>
                <button v-if="pendingLoginSite" type="button" @click="confirmSiteLogin(pendingLoginSite)">
                  <ShieldCheck :size="12" />{{ isSiteLoggedIn(pendingLoginSite) ? '刷新登录状态' : '我已完成登录' }} · {{ pendingLoginSite.name }}
                </button>
              </div>
              <div v-if="showCustomSite" class="custom-site-input">
                <Link2 :size="14" />
                <div class="custom-site-fields">
                  <label><span>网站名称</span><input v-model="customSiteName" class="custom-site-name" placeholder="如：AI前线" /></label>
                  <label><span>网站地址</span><input v-model="customSiteUrl" placeholder="https://example.com/" @keyup.enter="addCustomSite" /></label>
                </div>
                <button type="button" @click="addCustomSite">添加</button>
                <button type="button" aria-label="关闭" @click="showCustomSite = false"><X :size="13" /></button>
              </div>
              <div class="research-input">
                <Search :size="17" />
                <input v-model="searchQuery" placeholder="例如：AI 应用、Codex、牛油果营养" @input="handleSearchQueryInput" @keyup.enter="discover" />
                <button
                  v-if="searchQuery"
                  class="research-clear-button"
                  type="button"
                  aria-label="清空本次查询"
                  title="清空本次查询"
                  @click="clearResearchQuery"
                ><X :size="14" /></button>
                <button type="button" :disabled="discovering" @click="discover">
                  <LoaderCircle v-if="discovering" class="spin" :size="15" />{{ discovering ? '准备中' : '开始' }}
                </button>
              </div>
            </section>

            <section class="choice-section">
              <div class="choice-heading"><span>02</span><div><strong>文章类型</strong></div></div>
              <input
                v-model="form.article_type"
                class="custom-preference-input"
                maxlength="64"
                placeholder="例如：技术教程、新闻解读、美食分享、生活经验"
              />
            </section>

            <section class="choice-section">
              <div class="choice-heading"><span>03</span><div><strong>表达风格与提示词</strong></div></div>
              <textarea
                v-model="form.writing_style"
                class="custom-preference-input writing-instruction-input"
                maxlength="1000"
                rows="3"
                :placeholder="DEFAULT_WRITING_INSTRUCTION"
              ></textarea>
            </section>

            <section class="choice-section">
              <div class="choice-heading"><span>04</span><div><strong>字数与发布平台</strong></div></div>
              <div class="custom-word-count-picker">
                <div>
                  <strong>生成字数</strong>
                  <small>选择原文后，默认按原文字数增加 10%</small>
                </div>
                <label>
                  <input
                    v-model.number="form.target_word_count"
                    type="number"
                    min="200"
                    max="5000"
                    step="100"
                    @input="targetWordCountCustomized = true"
                    @blur="normalizeTargetWordCount"
                    @change="normalizeTargetWordCount"
                  />
                  <span>字</span>
                </label>
              </div>
              <div class="publish-platform-picker">
                <strong>发布平台</strong>
                <div class="platform-option-grid">
                  <button
                    v-for="platform in PUBLISH_PLATFORMS"
                    :key="platform.value"
                    type="button"
                    :class="{ selected: form.target_platform === platform.value }"
                    @click="form.target_platform = platform.value"
                  >
                    <Check :size="12" />{{ platform.label }}
                  </button>
                </div>
                <input
                  v-if="form.target_platform === '其他平台'"
                  v-model="form.custom_platform"
                  maxlength="500"
                  placeholder="输入发布平台名称，例如：博客园、今日头条"
                />
              </div>
            </section>
          </div>
        </aside>

        <main class="discovery-desk">
          <div v-if="discovering && !searchResults.length" class="discovery-loading">
            <LoaderCircle class="spin" :size="27" /><strong>正在扩展关键词并检索最新来源</strong><span>会校验正文长度，同时准备 10 个标题建议</span>
          </div>

          <template v-else>
            <section class="result-section source-result-section">
              <div class="result-section-head">
                <div><span>01 / SOURCES · {{ selectedSourceSite.name }}</span><h2>选择一篇参考文章</h2><p>检索阶段只读取标题、日期等信息；选中后才深度提取完整正文，并保留“打开原文”供你核对。</p></div>
                <strong>{{ form.selected_sources.length ? '已选择 1 篇' : '尚未选择' }} / {{ visibleSearchResults.length }} 当前显示</strong>
              </div>

              <div v-if="searchResults.length" class="source-filterbar">
                <label><CalendarDays :size="13" /><select v-model="sourceDateFilter" :disabled="discovering" @change="refreshSourceFilters">
                  <option value="all">不限日期</option>
                  <option value="7d">近 7 天</option>
                  <option value="30d">近 30 天</option>
                  <option value="1y">近 1 年</option>
                </select></label>
                <label><ArrowUpDown :size="13" /><select v-model="sourceSort" :disabled="discovering" @change="refreshSourceFilters">
                  <option value="newest">日期从新到旧</option>
                  <option value="oldest">日期从旧到新</option>
                </select></label>
                <span v-if="isSiteLoggedIn(selectedSourceSite)" class="source-login-confirmed">
                  <ShieldCheck :size="13" />已登录
                </span>
                <span class="source-strategy-badge">{{ searchStrategyLabel }}</span>
                <a v-if="selectedSourceSite.url" :href="selectedSourceSite.url" target="_blank" rel="noreferrer" @click="beginSiteLogin(selectedSourceSite)">
                  <LogIn :size="13" />{{ isSiteLoggedIn(selectedSourceSite) ? `重新登录${selectedSourceSite.name}` : `打开${selectedSourceSite.name}并登录` }}
                </a>
                <span>{{ searchResults.length }} 条结果</span>
              </div>

              <div v-if="searchResults.length" class="compact-source-grid">
                <article v-for="(source, index) in visibleSearchResults" :key="source.url" class="compact-source" :class="{ selected: sourceSelected(source) }">
                  <button type="button" :disabled="Boolean(loadingSourceUrl)" @click="toggleSource(source)">
                    <span class="source-number">{{ String(index + 1).padStart(2, '0') }}</span>
                    <span class="source-main">
                      <small>{{ source.source || 'WEB SOURCE' }}<i> · {{ source.date_type || '发布日期' }} {{ source.publish_date }}</i></small>
                      <strong>{{ source.title }}</strong>
                      <span class="source-word-count">{{ source.word_count ? `约 ${source.word_count.toLocaleString()} 字` : '选中后统计字数' }}</span>
                      <p v-if="loadingSourceUrl === source.url">正在深度提取正文，请稍候…</p>
                      <p v-else>{{ sourceSelected(source) && source.source_content ? '正文已提取，可以生成文章' : '点击选择后再提取正文' }}</p>
                    </span>
                    <span class="source-check"><LoaderCircle v-if="loadingSourceUrl === source.url" class="spin" :size="13" /><Check v-else :size="13" /></span>
                  </button>
                  <a :href="source.url" target="_blank" rel="noreferrer"><ExternalLink :size="11" />打开原文</a>
                </article>
              </div>
              <div v-if="searchResults.length && !visibleSearchResults.length" class="filter-empty">
                当前筛选条件下没有来源，试试“不限日期”或“全部文章”。
              </div>
              <div v-else-if="!searchResults.length" class="section-placeholder"><Search :size="24" /><span>选择来源网站，输入文章标题并点击“开始”。系统先返回文章元数据，选中后再提取完整正文。</span></div>
              <button v-if="searchResults.length" class="more-button" type="button" :disabled="loadingMore" @click="loadMoreSources">
                <LoaderCircle v-if="loadingMore" class="spin" :size="14" /><Plus v-else :size="14" />{{ loadingMore ? '继续检索中…' : '更多来源' }}
              </button>
            </section>

            <section class="result-section title-result-section">
              <div class="result-section-head">
                <div><span>02 / HEADLINE SUGGESTIONS</span><h2>标题建议</h2><p>{{ form.selected_sources.length ? '根据当前选中的原文给出 10 个最合适的标题；不满意也可以自己添加。' : '先完成来源检索，系统会给出 10 个标题建议。' }}</p></div>
                <button class="reload-button" type="button" :disabled="loadingTitles" @click="reloadTitles">
                  <LoaderCircle v-if="loadingTitles" class="spin" :size="14" /><RefreshCw v-else :size="14" />{{ form.selected_sources.length ? '按已选文章换一批' : '换一批' }}
                </button>
              </div>
              <div class="custom-title-entry">
                <PenLine :size="15" />
                <input v-model="customTitle" maxlength="255" placeholder="没有喜欢的？写一个自己的标题" @keyup.enter="addCustomTitle" />
                <button type="button" @click="addCustomTitle"><Plus :size="14" />加入并选中</button>
              </div>
              <div v-if="titleSuggestions.length" class="title-options">
                <button v-for="(title, index) in titleSuggestions" :key="title" type="button" :class="{ selected: form.title === title }" @click="form.title = title">
                  <span>{{ String(index + 1).padStart(2, '0') }}<small>{{ TITLE_ANGLES[index] }}</small></span><strong>{{ title }}</strong><i><Check :size="13" /></i>
                </button>
              </div>
              <div v-else class="section-placeholder"><PenLine :size="24" /><span>完成主题检索后，这里会出现 10 个标题候选。</span></div>
            </section>

            <section class="result-section manuscript-section">
              <div class="result-section-head manuscript-head">
                <div>
                  <span>03 / MANUSCRIPT</span>
                  <h2>{{ form.title || '等待选择标题' }}</h2>
                  <p>{{ form.article_type }} · {{ form.writing_style }} · 发布到 {{ resolvedPlatformName }} · 目标 {{ form.target_word_count }} 字 · 当前 {{ wordCount.toLocaleString() }} 字</p>
                  <p v-if="form.total_tokens" class="generation-statline">
                    本次生成：{{ form.generated_word_count.toLocaleString() }} 字 · 输入 {{ form.prompt_tokens.toLocaleString() }} Token · 输出 {{ form.completion_tokens.toLocaleString() }} Token · 合计 {{ form.total_tokens.toLocaleString() }} Token
                  </p>
                </div>
                <div class="manuscript-actions">
                  <button :class="{ active: editorTab === 'edit' }" @click="editorTab = 'edit'"><FileText :size="13" />编辑</button>
                  <button :class="{ active: editorTab === 'preview' }" @click="editorTab = 'preview'"><Eye :size="13" />预览</button>
                  <button @click="copyMarkdown"><Clipboard :size="13" />复制</button>
                </div>
              </div>
              <section class="image-material-bank">
                <header>
                  <div><Images :size="15" /><span><strong>我的图片素材库</strong><small>已收藏 {{ libraryAssets.length }} 张，可插入正文光标位置</small></span></div>
                  <div>
                    <RouterLink class="image-library-link" to="/media"><Search :size="13" />搜索/管理素材</RouterLink>
                    <button class="clear-images-button" type="button" :disabled="!manuscriptImageCount" @click="clearAllImageLinks"><Trash2 :size="13" />清除全部图片链接</button>
                  </div>
                </header>
                <div v-if="loadingLibraryAssets" class="image-material-loading"><LoaderCircle class="spin" :size="16" />读取图片素材库…</div>
                <template v-else-if="libraryAssets.length">
                  <nav class="image-category-tabs" aria-label="图片素材分类">
                    <button
                      v-for="category in imageCategoryOptions"
                      :key="category"
                      type="button"
                      :class="{ active: selectedImageCategory === category }"
                      @click="selectedImageCategory = category"
                    >
                      {{ category }} <span>{{ imageCategoryCount(category) }}</span>
                    </button>
                  </nav>
                  <div v-if="filteredLibraryAssets.length" class="image-material-strip">
                    <button v-for="material in filteredLibraryAssets" :key="material.id" type="button" @click="addImageMaterial(material)">
                      <img :src="material.image_url" :alt="material.title" loading="lazy" referrerpolicy="no-referrer" @error="$event.currentTarget.parentElement.remove()" />
                      <span><strong>{{ material.title }}</strong><small>{{ material.category || '未分类' }} · {{ material.source_name || '图片素材库' }}</small></span>
                      <i><ImagePlus :size="13" />加入图片</i>
                    </button>
                  </div>
                  <p v-else>当前分类还没有图片，可前往“图片素材”页面添加。</p>
                </template>
                <p v-else>素材库还是空的，前往“图片素材”页面搜索并收藏图片。</p>
              </section>
              <textarea
                v-if="editorTab === 'edit'"
                ref="manuscriptEditorRef"
                v-model="form.content"
                class="new-manuscript-editor"
                placeholder="选择来源和标题后点击右上角“生成文章”。你也可以在这里直接写或修改 Markdown。"
              />
              <div v-else class="new-manuscript-preview"><MarkdownContent :content="form.content" empty-text="生成后的文章会显示在这里。" /></div>
              <p v-if="form.status === 'generated' && form.content" class="editable-manuscript-hint">正文已经过专家、写手、审核官和编辑总监协作处理，仍可在这里继续手动修改并自动保存。</p>
              <details
                v-if="form.review_notes || form.director_review_summary || displayReviewChanges.length"
                class="director-review-panel generation-review-details"
              >
                <summary>
                  <ShieldCheck :size="18" />
                  <div>
                    <strong>文章生成优化记录</strong>
                    <p>{{ form.director_review_summary || '专家、写手、审核官与编辑总监已完成协作处理。' }}</p>
                  </div>
                  <span>{{ displayReviewChanges.length }} 条记录</span>
                  <ChevronDown class="review-toggle" :size="16" />
                </summary>
                <div class="generation-role-flow">
                  <span>01 专家</span><i>→</i><span>02 写手</span><i>→</i><span>03 审核官</span><i>→</i><span>04 编辑总监</span>
                </div>
                <div v-if="form.review_notes" class="inline-review"><ShieldCheck :size="16" /><div><strong>审核官记录</strong><p>{{ form.review_notes }}</p></div></div>
                <div v-if="displayReviewChanges.length" class="director-change-list">
                  <article v-for="(change, index) in displayReviewChanges" :key="`${change.location}-${index}`" class="director-change-card">
                    <div class="director-change-location"><span>{{ String(index + 1).padStart(2, '0') }}</span><b>{{ change.role || '编辑总监' }}</b>{{ change.location }}</div>
                    <div class="director-change-copy">
                      <div><small>修改前</small><del>{{ change.before || '旧记录未返回修改前原文' }}</del></div>
                      <div><small>实际修改内容</small><ins>{{ change.after || '已删除' }}</ins></div>
                    </div>
                    <p><strong>修改原因</strong>{{ change.reason }}</p>
                  </article>
                </div>
                <p v-else class="director-no-change">当前没有可核对的实质修改记录。</p>
              </details>
            </section>
          </template>
        </main>
      </div>

      <section class="mobile-studio-actions">
        <div>
          <strong>保存草稿或生成文章</strong>
          <small>{{ wordCount.toLocaleString() }} 字 · {{ autosaveState }}</small>
        </div>
        <button class="button button-secondary" type="button" :disabled="saving || isBackgroundGenerating" @click="handleSaveAction">
          <LoaderCircle v-if="saving" class="spin" :size="15" /><Save v-else :size="15" />{{ ['generated', 'published'].includes(form.status) ? '保存修改' : '保存草稿' }}
        </button>
        <button class="button button-signal" type="button" :disabled="generating || saving || isBackgroundGenerating" @click="handleGenerate">
          <LoaderCircle v-if="generating" class="spin" :size="15" /><Sparkles v-else :size="15" />
          {{ generating ? '正在提交…' : (isBackgroundGenerating ? '后台生成中…' : '生成文章') }}
        </button>
        <button
          v-if="form.status === 'generated' && form.content"
          class="button button-secondary"
          type="button"
          :disabled="generating || saving"
          @click="openPublishCenter"
        >
          <Send :size="15" />发布文章
        </button>
      </section>
    </template>

    <NoticeToast :message="notice.message" :type="notice.type" @close="notice.message = ''" />
  </section>
</template>
