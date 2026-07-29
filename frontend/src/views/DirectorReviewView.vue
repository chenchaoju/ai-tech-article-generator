<script setup>
import {
  ArrowLeft,
  Check,
  Clipboard,
  Eye,
  LoaderCircle,
  PenLine,
  Save,
  Send,
  ShieldCheck,
} from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { articleApi, getApiError } from '../api/articles'
import MarkdownContent from '../components/MarkdownContent.vue'
import NoticeToast from '../components/NoticeToast.vue'
import { copyText } from '../utils/clipboard'
import { reviewChangeForDisplay } from '../utils/reviewDiff'

const route = useRoute()
const router = useRouter()
const article = ref(null)
const content = ref('')
const loading = ref(true)
const saving = ref(false)
const reviewing = ref(false)
const editorTab = ref('edit')
const notice = ref('')
const noticeType = ref('success')

const wordCount = computed(() => content.value.replace(/\s/g, '').length)
const reviewChanges = computed(() => (
  (article.value?.director_review_changes || []).map(reviewChangeForDisplay)
))

function showNotice(message, type = 'success') {
  notice.value = message
  noticeType.value = type
}

async function loadArticle() {
  try {
    article.value = await articleApi.get(route.params.id)
    content.value = article.value.content || ''
  } catch (error) {
    showNotice(getApiError(error, '文章加载失败'), 'error')
  } finally {
    loading.value = false
  }
}

async function saveCurrentContent(quiet = false) {
  if (!article.value || !content.value.trim()) {
    showNotice('正文不能为空', 'error')
    return null
  }
  saving.value = true
  try {
    const updated = await articleApi.update(article.value.id, {
      content: content.value,
      status: 'generated',
    })
    article.value = updated
    content.value = updated.content
    if (!quiet) showNotice('当前修改已保存')
    return updated
  } catch (error) {
    showNotice(getApiError(error, '保存失败'), 'error')
    return null
  } finally {
    saving.value = false
  }
}

async function submitDirectorReview() {
  const saved = await saveCurrentContent(true)
  if (!saved) return
  reviewing.value = true
  try {
    const result = await articleApi.directorReview(article.value.id)
    article.value = result.article
    content.value = result.article.content
    editorTab.value = 'edit'
    showNotice(`复审完成，记录 ${result.changes.length} 处实质修改`)
  } catch (error) {
    showNotice(getApiError(error, '编辑总监复审失败'), 'error')
  } finally {
    reviewing.value = false
  }
}

async function copyMarkdown() {
  if (!content.value) return showNotice('暂无可复制的 Markdown', 'error')
  try {
    await copyText(content.value)
    showNotice('Markdown 已复制')
  } catch (error) {
    showNotice(error.message || '复制失败，请手动选择正文复制', 'error')
  }
}

async function openPublishCenter() {
  const saved = await saveCurrentContent(true)
  if (!saved) return
  await router.push(`/articles/${article.value.id}/publish`)
}

onMounted(loadArticle)
</script>

<template>
  <section class="director-workspace">
    <div v-if="loading" class="loading-state full-height">
      <LoaderCircle class="spin" :size="28" />正在打开总监复审室…
    </div>

    <template v-else-if="article">
      <header class="director-workspace-header">
        <div>
          <RouterLink :to="`/articles/${article.id}/edit`"><ArrowLeft :size="15" />返回创作台</RouterLink>
          <span>EDITORIAL DIRECTOR</span>
          <h1>资深编辑总监复审室</h1>
          <p>先在左侧修改已生成文章，再让总监按成熟编辑思路终审；右侧会标记修改内容和原因。</p>
        </div>
        <div class="director-workspace-actions">
          <button class="button button-signal" type="button" :disabled="saving || reviewing" @click="openPublishCenter">
            <Send :size="15" />发布文章
          </button>
          <button class="button button-ghost" type="button" :disabled="saving || reviewing" @click="saveCurrentContent()">
            <LoaderCircle v-if="saving" class="spin" :size="15" /><Save v-else :size="15" />
            {{ saving ? '保存中…' : '保存修改' }}
          </button>
          <button class="button button-secondary" type="button" @click="copyMarkdown">
            <Clipboard :size="15" />复制 Markdown
          </button>
          <button class="button button-signal" type="button" :disabled="saving || reviewing" @click="submitDirectorReview">
            <LoaderCircle v-if="reviewing" class="spin" :size="15" /><ShieldCheck v-else :size="15" />
            {{ reviewing ? '总监复审中（约 1–3 分钟）…' : '提交总监复审' }}
          </button>
        </div>
      </header>

      <div class="director-workspace-grid">
        <section class="director-manuscript-panel">
          <header>
            <div>
              <span>MANUSCRIPT</span>
              <h2>{{ article.title }}</h2>
              <p>当前 {{ wordCount.toLocaleString() }} 字 · 目标 {{ article.target_word_count.toLocaleString() }} 字</p>
            </div>
            <div class="editor-tabs">
              <button :class="{ active: editorTab === 'edit' }" @click="editorTab = 'edit'"><PenLine :size="13" />编辑</button>
              <button :class="{ active: editorTab === 'preview' }" @click="editorTab = 'preview'"><Eye :size="13" />预览</button>
            </div>
          </header>
          <textarea
            v-if="editorTab === 'edit'"
            v-model="content"
            class="director-manuscript-editor"
            placeholder="在这里修改已经生成的 Markdown 正文…"
          />
          <div v-else class="director-manuscript-preview">
            <MarkdownContent :content="content" empty-text="当前没有正文。" />
          </div>
        </section>

        <aside class="director-audit-panel">
          <div class="director-audit-intro">
            <ShieldCheck :size="20" />
            <div>
              <span>REVISION NOTES</span>
              <h2>修改记录</h2>
              <p v-if="article.director_review_summary">{{ article.director_review_summary }}</p>
              <p v-else>提交复审后，这里会说明每一处改动以及这样修改的原因。</p>
            </div>
          </div>

          <div v-if="reviewChanges.length" class="director-change-list">
            <article v-for="(change, index) in reviewChanges" :key="`${change.location}-${index}`" class="director-change-card">
              <div class="director-change-location"><span>{{ String(index + 1).padStart(2, '0') }}</span>{{ change.location }}</div>
              <div class="director-change-copy">
                <div><small>修改前</small><del>{{ change.before || '—' }}</del></div>
                <div><small>实际修改内容</small><ins>{{ change.after || '—' }}</ins></div>
              </div>
              <p><strong>修改原因</strong>{{ change.reason }}</p>
            </article>
          </div>
          <div v-else class="director-audit-empty">
            <Check :size="20" />
            <strong>{{ article.director_reviewed_at ? '本次没有需要记录的实质修改' : '等待提交复审' }}</strong>
            <span>纯标点和空格调整不会单独列出。</span>
          </div>
        </aside>
      </div>
    </template>

    <NoticeToast :message="notice" :type="noticeType" @close="notice = ''" />
  </section>
</template>
