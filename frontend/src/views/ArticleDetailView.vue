<script setup>
import {
  ArrowLeft,
  CalendarDays,
  Check,
  ChevronDown,
  Clipboard,
  Edit3,
  LoaderCircle,
  Send,
  ShieldCheck,
} from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { articleApi, getApiError } from '../api/articles'
import MarkdownContent from '../components/MarkdownContent.vue'
import NoticeToast from '../components/NoticeToast.vue'
import { copyText } from '../utils/clipboard'
import { reviewChangeForDisplay } from '../utils/reviewDiff'

const route = useRoute()
const article = ref(null)
const loading = ref(true)
const notice = ref('')
const noticeType = ref('success')
const reviewChanges = computed(() => (
  (article.value?.director_review_changes || []).map(reviewChangeForDisplay).filter(
    (change) => String(change.before || '').replace(/\s/g, '')
      !== String(change.after || '').replace(/\s/g, ''),
  )
))
const displayContent = computed(() => {
  const content = article.value?.content || ''
  if (!content) return ''
  const normalize = (value) => String(value || '').replace(/[\W_]+/g, '').toLocaleLowerCase()
  const titleKey = normalize(article.value?.title)
  return content
    .split(/\r?\n/)
    .filter((line) => {
      const stripped = line.trim()
      if (/^(?:>\s*)?(?:文章)?主题\s*[/：:]/i.test(stripped)) return false
      const heading = stripped.match(/^#{1,6}\s+(.+)$/)
      return !(heading && titleKey && normalize(heading[1]) === titleKey)
    })
    .join('\n')
    .replace(/^\s*\n+/, '')
})

function formatDate(value) {
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function statusLabel(value) {
  if (value === 'published') return '已发布'
  if (value === 'generated') return '已完成'
  if (value === 'generating') return '生成中'
  if (value === 'generation_failed') return '生成失败'
  return '草稿'
}

async function loadArticle() {
  try {
    article.value = await articleApi.get(route.params.id)
  } catch (error) {
    notice.value = getApiError(error, '文章加载失败')
    noticeType.value = 'error'
  } finally {
    loading.value = false
  }
}

async function copyMarkdown() {
  if (!displayContent.value) {
    notice.value = '暂无可复制的 Markdown 内容'
    noticeType.value = 'error'
    return
  }
  try {
    await copyText(displayContent.value)
    notice.value = 'Markdown 已复制，可直接粘贴到 CSDN'
    noticeType.value = 'success'
  } catch (error) {
    notice.value = error.message || '复制失败，请手动选择正文复制'
    noticeType.value = 'error'
  }
}

onMounted(loadArticle)
</script>

<template>
  <section class="page detail-page">
    <div v-if="loading" class="loading-state full-height">
      <LoaderCircle class="spin" :size="30" />
      正在读取文章…
    </div>

    <template v-else-if="article">
      <header class="detail-header">
        <RouterLink class="back-link" to="/articles"><ArrowLeft :size="17" />返回文章列表</RouterLink>
        <div class="detail-actions">
          <RouterLink
            v-if="['generated', 'published'].includes(article.status)"
            class="button button-signal"
            :to="`/articles/${article.id}/publish`"
          >
            <Send :size="17" />{{ article.status === 'published' ? '发布记录' : '发布文章' }}
          </RouterLink>
          <button class="button button-secondary" type="button" @click="copyMarkdown">
            <Clipboard :size="17" />复制 Markdown
          </button>
          <RouterLink class="button button-primary" :to="`/articles/${article.id}/edit`">
            <Edit3 :size="17" />进入编辑界面
          </RouterLink>
        </div>
      </header>

      <article class="article-document">
        <p class="detail-readonly-notice">
          当前为只读详情页；标题、正文和图片的所有改动均在编辑界面完成。
        </p>
        <div class="document-meta">
          <span class="status-badge" :class="article.status">
            <Check v-if="['generated', 'published'].includes(article.status)" :size="13" />
            {{ statusLabel(article.status) }}
          </span>
          <span><CalendarDays :size="15" />更新于 {{ formatDate(article.updated_at) }}</span>
          <span v-if="article.model_name">模型：{{ article.model_name }}</span>
          <span v-if="article.generated_word_count">{{ article.generated_word_count.toLocaleString() }} 字</span>
          <span v-if="article.total_tokens">Token：{{ article.total_tokens.toLocaleString() }}（输入 {{ article.prompt_tokens.toLocaleString() }} / 输出 {{ article.completion_tokens.toLocaleString() }}）</span>
        </div>
        <h1 class="document-title">{{ article.title }}</h1>
        <MarkdownContent
          :content="displayContent"
          :empty-text="article.status === 'generating' ? '文章正在后台生成，可以离开本页，完成后系统会提示。' : '这篇文章还没有正文，请进入编辑界面补充材料或开始写作。'"
        />
        <details
          v-if="article.review_notes || article.director_review_summary || reviewChanges.length"
          class="director-review-panel detail-director-review generation-review-details"
        >
          <summary>
            <Check :size="18" />
            <div>
              <strong>文章生成优化记录</strong>
              <p>{{ article.director_review_summary || '专家、写手、审核官与编辑总监已完成协作处理。' }}</p>
            </div>
            <span>{{ reviewChanges.length }} 条记录</span>
            <ChevronDown class="review-toggle" :size="16" />
          </summary>
          <div class="generation-role-flow">
            <span>01 专家</span><i>→</i><span>02 写手</span><i>→</i><span>03 审核官</span><i>→</i><span>04 编辑总监</span>
          </div>
          <div v-if="article.review_notes" class="inline-review"><ShieldCheck :size="16" /><div><strong>审核官记录</strong><p>{{ article.review_notes }}</p></div></div>
          <div v-if="reviewChanges.length" class="director-change-list">
            <article v-for="(change, index) in reviewChanges" :key="`${change.location}-${index}`" class="director-change-card">
              <div class="director-change-location"><span>{{ String(index + 1).padStart(2, '0') }}</span><b>{{ change.role || '编辑总监' }}</b>{{ change.location }}</div>
              <div class="director-change-copy">
                <div><small>修改前</small><del>{{ change.before || '—' }}</del></div>
                <div><small>实际修改内容</small><ins>{{ change.after || '—' }}</ins></div>
              </div>
              <p><strong>修改原因</strong>{{ change.reason }}</p>
            </article>
          </div>
          <p v-else class="director-no-change">当前没有可核对的实质修改记录。</p>
        </details>
      </article>
    </template>

    <NoticeToast :message="notice" :type="noticeType" @close="notice = ''" />
  </section>
</template>
