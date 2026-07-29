<script setup>
import {
  ArrowRight,
  CalendarDays,
  FilePlus2,
  LoaderCircle,
  Search,
  Sparkles,
  Trash2,
} from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { articleApi, getApiError } from '../api/articles'
import EmptyState from '../components/EmptyState.vue'
import NoticeToast from '../components/NoticeToast.vue'

const articles = ref([])
const total = ref(0)
const loading = ref(true)
const keyword = ref('')
const status = ref('')
const errorMessage = ref('')
const deletingId = ref(null)

const generatedCount = computed(
  () => articles.value.filter(
    (article) => ['generated', 'published'].includes(article.status),
  ).length,
)

function formatDate(value) {
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date(value))
}

function excerpt(content) {
  if (!content) return '尚未生成正文，继续补充真实项目材料。'
  return content
    .replace(/```[\s\S]*?```/g, '[代码片段]')
    .replace(/[#>*_`[\]-]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 110)
}

function statusLabel(value) {
  if (value === 'published') return '已发布'
  if (value === 'generated') return '已完成'
  if (value === 'generating') return '生成中'
  if (value === 'generation_failed') return '生成失败'
  return '草稿'
}

async function loadArticles() {
  loading.value = true
  try {
    const data = await articleApi.list({
      keyword: keyword.value,
      status: status.value,
      page_size: 50,
    })
    articles.value = data.items
    total.value = data.total
  } catch (error) {
    errorMessage.value = getApiError(error, '文章列表加载失败')
  } finally {
    loading.value = false
  }
}

let searchTimer
function queueSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(loadArticles, 300)
}

async function deleteArticle(article) {
  if (article.status === 'generating') {
    errorMessage.value = '文章正在后台生成，完成后再删除'
    return
  }
  if (!window.confirm(`确定删除“${article.title || article.topic}”吗？删除后无法恢复。`)) return
  deletingId.value = article.id
  try {
    await articleApi.delete(article.id)
    articles.value = articles.value.filter((item) => item.id !== article.id)
    total.value = Math.max(0, total.value - 1)
  } catch (error) {
    errorMessage.value = getApiError(error, '文章删除失败')
  } finally {
    deletingId.value = null
  }
}

function refreshAfterGeneration() {
  loadArticles()
}

onMounted(() => {
  loadArticles()
  window.addEventListener('article-generation-completed', refreshAfterGeneration)
  window.addEventListener('article-generation-failed', refreshAfterGeneration)
})
onBeforeUnmount(() => {
  window.removeEventListener('article-generation-completed', refreshAfterGeneration)
  window.removeEventListener('article-generation-failed', refreshAfterGeneration)
})
</script>

<template>
  <section class="page list-page">
    <header class="page-header compact-page-header">
      <div>
        <div class="eyebrow"><span /> ARTICLE LIBRARY</div>
        <h1>文章库</h1>
      </div>
      <RouterLink class="button button-primary" to="/articles/new">
        <FilePlus2 :size="18" />
        新建文章
      </RouterLink>
    </header>

    <div class="summary-strip">
      <div>
        <span>文章总数</span>
        <strong>{{ total }}</strong>
      </div>
      <div>
        <span>已完成文章</span>
        <strong>{{ generatedCount }}</strong>
      </div>
      <div class="summary-message">
        <Sparkles :size="19" />
        <p><strong>事实优先</strong><br />没有提供的结果，AI 不会替你补写。</p>
      </div>
    </div>

    <div class="toolbar">
      <label class="search-box">
        <Search :size="18" />
        <input
          v-model="keyword"
          type="search"
          placeholder="搜索标题或主题"
          @input="queueSearch"
        />
      </label>
      <select v-model="status" aria-label="筛选文章状态" @change="loadArticles">
        <option value="">全部状态</option>
        <option value="draft">草稿</option>
        <option value="generating">生成中</option>
        <option value="generation_failed">生成失败</option>
        <option value="generated">已完成</option>
        <option value="published">已发布</option>
      </select>
    </div>

    <div v-if="loading" class="loading-state">
      <LoaderCircle class="spin" :size="28" />
      正在读取文章…
    </div>

    <EmptyState
      v-else-if="articles.length === 0"
      :title="keyword || status ? '没有匹配的文章' : '还没有文章'"
      :description="keyword || status ? '换一个关键词或筛选条件试试。' : '记录第一个真实项目问题，让 AI 帮你整理成文。'"
    >
      <RouterLink v-if="!keyword && !status" class="button button-primary" to="/articles/new">
        创建第一篇
      </RouterLink>
    </EmptyState>

    <div v-else class="article-grid">
      <article
        v-for="article in articles"
        :key="article.id"
        class="article-card"
      >
        <RouterLink class="article-card-main" :to="`/articles/${article.id}`">
          <div class="card-topline">
            <span class="status-badge" :class="article.status">
              {{ statusLabel(article.status) }}
            </span>
            <span class="date"><CalendarDays :size="14" />{{ formatDate(article.updated_at) }}</span>
          </div>
          <h2>{{ article.title || article.topic }}</h2>
          <p class="topic"># {{ article.topic }}</p>
          <p class="excerpt">{{ excerpt(article.content) }}</p>
          <p v-if="article.generated_word_count || article.total_tokens" class="card-generation-stats">
            {{ article.generated_word_count.toLocaleString() }} 字
            <span v-if="article.total_tokens">· {{ article.total_tokens.toLocaleString() }} Token</span>
          </p>
          <span class="card-link">查看文章 <ArrowRight :size="16" /></span>
        </RouterLink>
        <button
          class="article-card-delete"
          type="button"
          :disabled="deletingId === article.id || article.status === 'generating'"
          aria-label="删除文章"
          title="快捷删除"
          @click="deleteArticle(article)"
        >
          <LoaderCircle v-if="deletingId === article.id" class="spin" :size="15" />
          <Trash2 v-else :size="15" />
        </button>
      </article>
    </div>

    <NoticeToast
      :message="errorMessage"
      type="error"
      @close="errorMessage = ''"
    />
  </section>
</template>
