<script setup>
import { BarChart3, FilePlus2, Images, Library, LoaderCircle, Settings2 } from 'lucide-vue-next'
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { articleApi } from './api/articles'
import NoticeToast from './components/NoticeToast.vue'
import {
  clearGeneratedWorkspace,
  loadGenerationJobs,
  removeGenerationJob,
} from './utils/generationJobs'

const activeJobs = ref(loadGenerationJobs())
const globalNotice = reactive({ message: '', type: 'success' })
let pollTimer
let noticeTimer
let polling = false

function showGlobalNotice(message, type = 'success') {
  clearTimeout(noticeTimer)
  globalNotice.message = message
  globalNotice.type = type
  noticeTimer = setTimeout(() => {
    globalNotice.message = ''
  }, 2000)
}

async function pollGenerationJobs() {
  if (polling) return
  activeJobs.value = loadGenerationJobs()
  if (!activeJobs.value.length) return
  polling = true
  try {
    for (const job of [...activeJobs.value]) {
      try {
        const article = await articleApi.get(job.article_id)
        if (['generated', 'published'].includes(article.status)) {
          removeGenerationJob(job.article_id)
          clearGeneratedWorkspace(job.article_id)
          showGlobalNotice(`《${article.title}》文章完成`)
          window.dispatchEvent(new CustomEvent('article-generation-completed', {
            detail: { article },
          }))
        } else if (article.status === 'generation_failed') {
          removeGenerationJob(job.article_id)
          showGlobalNotice(
            article.review_notes || `《${job.title}》生成失败，草稿已经保留`,
            'error',
          )
          window.dispatchEvent(new CustomEvent('article-generation-failed', {
            detail: { article },
          }))
        }
      } catch (error) {
        if (error?.response?.status === 404) {
          removeGenerationJob(job.article_id)
          showGlobalNotice(`后台任务对应的文章已不存在`, 'error')
        }
      }
    }
  } finally {
    activeJobs.value = loadGenerationJobs()
    polling = false
  }
}

function refreshGenerationJobs() {
  activeJobs.value = loadGenerationJobs()
  pollGenerationJobs()
}

onMounted(() => {
  window.addEventListener('article-generation-jobs-changed', refreshGenerationJobs)
  pollGenerationJobs()
  pollTimer = setInterval(pollGenerationJobs, 3000)
})

onBeforeUnmount(() => {
  clearInterval(pollTimer)
  clearTimeout(noticeTimer)
  window.removeEventListener('article-generation-jobs-changed', refreshGenerationJobs)
})
</script>

<template>
  <div class="app-frame">
    <header class="topbar">
      <RouterLink class="wordmark" to="/articles">
        <strong>文章工坊</strong>
      </RouterLink>

      <nav class="topnav" aria-label="主导航">
        <RouterLink to="/articles"><Library :size="16" />文章库</RouterLink>
        <RouterLink to="/articles/new"><FilePlus2 :size="16" />创作台</RouterLink>
        <RouterLink to="/media"><Images :size="16" />图片素材</RouterLink>
        <RouterLink to="/usage"><BarChart3 :size="16" />Token 统计</RouterLink>
        <RouterLink to="/settings"><Settings2 :size="16" />模型设置</RouterLink>
      </nav>

      <div v-if="activeJobs.length" class="background-generation-indicator">
        <LoaderCircle class="spin" :size="14" />
        后台生成 {{ activeJobs.length }} 篇
      </div>
    </header>

    <main class="main-content">
      <RouterView />
    </main>

    <nav class="mobile-bottom-nav" aria-label="手机版主导航">
      <RouterLink to="/articles"><Library :size="19" /><span>文章</span></RouterLink>
      <RouterLink to="/articles/new"><FilePlus2 :size="19" /><span>创作</span></RouterLink>
      <RouterLink to="/media"><Images :size="19" /><span>素材</span></RouterLink>
      <RouterLink to="/usage"><BarChart3 :size="19" /><span>统计</span></RouterLink>
      <RouterLink to="/settings"><Settings2 :size="19" /><span>设置</span></RouterLink>
    </nav>
    <NoticeToast
      :message="globalNotice.message"
      :type="globalNotice.type"
      @close="globalNotice.message = ''"
    />
  </div>
</template>
