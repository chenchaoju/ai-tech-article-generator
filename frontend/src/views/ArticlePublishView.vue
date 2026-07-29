<script setup>
import {
  ArrowLeft,
  CalendarClock,
  Check,
  Clipboard,
  ExternalLink,
  FileText,
  LoaderCircle,
  RotateCcw,
  ShieldCheck,
  Smartphone,
  X,
} from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { articleApi, getApiError } from '../api/articles'
import NoticeToast from '../components/NoticeToast.vue'
import { copyText } from '../utils/clipboard'

const PLATFORMS = [
  {
    id: 'wechat',
    name: '微信公众号',
    mark: '微',
    color: '#07c160',
    automatic: true,
    url: 'https://mp.weixin.qq.com/',
    note: '官方 API 自动上传正文图片、创建草稿并提交发布。',
  },
  {
    id: 'csdn',
    name: 'CSDN',
    mark: 'C',
    color: '#fc5531',
    url: 'https://editor.csdn.net/md/',
    note: '适合技术教程和项目复盘，支持 Markdown 编辑。',
  },
  {
    id: 'toutiao',
    name: '今日头条',
    mark: '头',
    color: '#f04142',
    url: 'https://mp.toutiao.com/profile_v4/graphic/publish',
    note: '适合新闻、生活、娱乐和大众化技术内容。',
  },
  {
    id: 'zhihu',
    name: '知乎',
    mark: '知',
    color: '#1677ff',
    url: 'https://zhuanlan.zhihu.com/write',
    note: '适合有分析、有判断和完整论证的长文章。',
  },
  {
    id: 'xiaohongshu',
    name: '小红书',
    mark: '红',
    color: '#ff2442',
    url: 'https://creator.xiaohongshu.com/publish/publish',
    note: '适合移动端阅读，可复制正文后在创作服务平台继续排版。',
  },
  {
    id: 'juejin',
    name: '掘金',
    mark: '掘',
    color: '#1e80ff',
    url: 'https://juejin.cn/editor/drafts/new?v=2',
    note: '适合开发实践、工具教程和技术经验总结。',
  },
  {
    id: 'cnblogs',
    name: '博客园',
    mark: '博',
    color: '#2b6695',
    url: 'https://i.cnblogs.com/posts/edit',
    note: '适合代码密集型技术文章和长期知识沉淀。',
  },
]

const route = useRoute()
const article = ref(null)
const loading = ref(true)
const workingPlatform = ref('')
const scheduleWorking = ref(false)
const schedules = ref([])
const scheduleTime = ref('')
const notice = ref('')
const noticeType = ref('success')

const publishedCount = computed(
  () => article.value?.publish_records?.filter(
    (item) => ['published', 'submitted'].includes(item.status),
  ).length || 0,
)
const currentWechatSchedule = computed(
  () => schedules.value.find((item) => ['pending', 'processing'].includes(item.status))
    || schedules.value.find((item) => item.status === 'failed')
    || null,
)

function toDateTimeLocal(value) {
  const date = new Date(value)
  const pad = (number) => String(number).padStart(2, '0')
  return [
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`,
    `${pad(date.getHours())}:${pad(date.getMinutes())}`,
  ].join('T')
}

const minScheduleTime = computed(() => toDateTimeLocal(Date.now() + 60 * 1000))

function initializeScheduleTime() {
  const next = new Date(Date.now() + 60 * 60 * 1000)
  next.setSeconds(0, 0)
  scheduleTime.value = toDateTimeLocal(next)
}

function showNotice(message, type = 'success') {
  notice.value = message
  noticeType.value = type
}

function recordFor(platformId) {
  return article.value?.publish_records?.find((item) => item.platform === platformId) || null
}

function statusLabel(platformId) {
  const status = recordFor(platformId)?.status
  if (status === 'published') return '已确认发布'
  if (status === 'submitted') return '已提交微信发布'
  if (status === 'prepared') return '已打开发布页'
  return '尚未发布'
}

function scheduleStatusLabel(status) {
  if (status === 'pending') return '等待定时发布'
  if (status === 'processing') return '正在自动发布'
  if (status === 'failed') return '自动发布失败'
  if (status === 'published') return '已按时发布'
  return '已取消'
}

async function autoPublishWechat(platform) {
  if (!article.value?.content?.trim()) {
    showNotice('当前文章没有可发布的正文', 'error')
    return
  }
  workingPlatform.value = platform.id
  try {
    const result = await articleApi.publishWechat(article.value.id)
    article.value = result.article
    showNotice(`${result.message} 已上传 ${result.uploaded_image_count} 张正文图片。`)
  } catch (error) {
    showNotice(getApiError(error, '微信公众号自动发布失败'), 'error')
  } finally {
    workingPlatform.value = ''
  }
}

async function scheduleWechatPublish() {
  if (!scheduleTime.value) {
    showNotice('请选择定时发布时间', 'error')
    return
  }
  const scheduledAt = new Date(scheduleTime.value)
  if (Number.isNaN(scheduledAt.getTime()) || scheduledAt <= new Date()) {
    showNotice('定时发布时间必须晚于当前时间', 'error')
    return
  }
  scheduleWorking.value = true
  try {
    const schedule = await articleApi.scheduleWechatPublish(
      article.value.id,
      scheduledAt.toISOString(),
    )
    schedules.value = [
      schedule,
      ...schedules.value.filter((item) => item.id !== schedule.id),
    ]
    showNotice(`已设置 ${formatTime(schedule.scheduled_at)} 自动发布到微信公众号`)
  } catch (error) {
    showNotice(getApiError(error, '定时发布设置失败'), 'error')
  } finally {
    scheduleWorking.value = false
  }
}

async function cancelWechatSchedule() {
  const schedule = currentWechatSchedule.value
  if (!schedule) return
  scheduleWorking.value = true
  try {
    const cancelled = await articleApi.cancelPublishSchedule(article.value.id, schedule.id)
    schedules.value = schedules.value.map(
      (item) => item.id === cancelled.id ? cancelled : item,
    )
    showNotice('微信公众号定时发布已取消')
  } catch (error) {
    showNotice(getApiError(error, '取消定时发布失败'), 'error')
  } finally {
    scheduleWorking.value = false
  }
}

function formatTime(value) {
  if (!value) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function markdownForPublishing() {
  const body = (article.value?.content || '').trim()
  if (/^#\s+\S+/.test(body)) return body
  return `# ${article.value?.title || '未命名文章'}\n\n${body}`.trim()
}

async function saveRecord(platform, status) {
  const now = new Date().toISOString()
  const existing = [...(article.value.publish_records || [])]
  const index = existing.findIndex((item) => item.platform === platform.id)
  const previous = index >= 0 ? existing[index] : {}
  const record = {
    ...previous,
    platform: platform.id,
    platform_name: platform.name,
    status,
    prepared_at: previous.prepared_at || now,
    published_at: status === 'published' ? now : null,
  }
  if (index >= 0) existing.splice(index, 1, record)
  else existing.push(record)
  article.value = await articleApi.update(article.value.id, { publish_records: existing })
}

async function preparePublish(platform) {
  if (!article.value?.content?.trim()) {
    showNotice('当前文章没有可发布的正文', 'error')
    return
  }
  workingPlatform.value = platform.id
  const publisherWindow = window.open(platform.url, '_blank')
  if (publisherWindow) publisherWindow.opener = null
  try {
    await copyText(markdownForPublishing())
    await saveRecord(platform, 'prepared')
    showNotice(
      publisherWindow
        ? `已复制全文并打开${platform.name}发布页，登录后粘贴即可`
        : `全文已复制；浏览器拦截了新窗口，请允许弹窗后重试`,
      publisherWindow ? 'success' : 'error',
    )
  } catch (error) {
    showNotice(getApiError(error, `打开${platform.name}发布流程失败`), 'error')
  } finally {
    workingPlatform.value = ''
  }
}

async function confirmPublished(platform) {
  workingPlatform.value = platform.id
  try {
    await saveRecord(platform, 'published')
    showNotice(`已记录文章发布到${platform.name}`)
  } catch (error) {
    showNotice(getApiError(error, '发布状态保存失败'), 'error')
  } finally {
    workingPlatform.value = ''
  }
}

async function resetPlatform(platform) {
  workingPlatform.value = platform.id
  try {
    const records = (article.value.publish_records || []).filter(
      (item) => item.platform !== platform.id,
    )
    article.value = await articleApi.update(article.value.id, { publish_records: records })
    showNotice(`${platform.name}发布状态已重置`)
  } catch (error) {
    showNotice(getApiError(error, '状态重置失败'), 'error')
  } finally {
    workingPlatform.value = ''
  }
}

async function loadArticle() {
  try {
    article.value = await articleApi.get(route.params.id)
    schedules.value = await articleApi.listPublishSchedules(route.params.id)
    const pending = currentWechatSchedule.value
    if (pending?.scheduled_at && pending.status === 'pending') {
      scheduleTime.value = toDateTimeLocal(pending.scheduled_at)
    } else {
      initializeScheduleTime()
    }
  } catch (error) {
    showNotice(getApiError(error, '文章加载失败'), 'error')
  } finally {
    loading.value = false
  }
}

onMounted(loadArticle)
</script>

<template>
  <section class="publish-page">
    <div v-if="loading" class="loading-state full-height">
      <LoaderCircle class="spin" :size="28" />正在打开发布中心…
    </div>

    <template v-else-if="article">
      <header class="publish-hero">
        <div>
          <RouterLink :to="`/articles/${article.id}`"><ArrowLeft :size="15" />返回文章详情</RouterLink>
          <span>OMNICHANNEL PUBLISHING</span>
          <h1>把好文章，送到更多读者面前。</h1>
          <p>一次准备，多平台发布。系统复制完整 Markdown 并打开平台编辑器，最终发布由你在登录后的平台页面确认。</p>
        </div>
        <div class="publish-summary">
          <strong>{{ publishedCount }}<small>/ {{ PLATFORMS.length }}</small></strong>
          <span>已确认发布平台</span>
        </div>
      </header>

      <section class="publish-article-strip">
        <div><FileText :size="18" /><span><small>READY TO PUBLISH</small><strong>{{ article.title }}</strong></span></div>
        <div>
          <span>{{ article.generated_word_count || article.content.replace(/\s/g, '').length }} 字</span>
          <span>{{ article.content.match(/!\[/g)?.length || 0 }} 张图片</span>
          <span>{{ article.total_tokens.toLocaleString() }} Tokens</span>
        </div>
      </section>

      <div class="publish-platform-grid">
        <article
          v-for="platform in PLATFORMS"
          :key="platform.id"
          class="publish-platform-card"
          :class="{ published: ['published', 'submitted'].includes(recordFor(platform.id)?.status) }"
        >
          <header>
            <span class="platform-mark" :style="{ background: platform.color }">{{ platform.mark }}</span>
            <div><strong>{{ platform.name }}</strong><small>{{ statusLabel(platform.id) }}</small></div>
            <ShieldCheck v-if="['published', 'submitted'].includes(recordFor(platform.id)?.status)" :size="18" />
          </header>
          <p>{{ platform.note }}</p>
          <div v-if="recordFor(platform.id)" class="publish-record-time">
            {{ recordFor(platform.id).status === 'submitted' ? '自动提交' : (recordFor(platform.id).status === 'published' ? '发布确认' : '发布页打开') }}
            · {{ formatTime(recordFor(platform.id).submitted_at || recordFor(platform.id).published_at || recordFor(platform.id).prepared_at) }}
          </div>
          <div v-if="platform.automatic" class="wechat-publish-controls">
            <div class="publish-platform-actions publish-platform-actions-auto">
              <button
                class="button button-primary"
                type="button"
                :disabled="workingPlatform || article.status === 'published'"
                @click="autoPublishWechat(platform)"
              >
                <LoaderCircle v-if="workingPlatform === platform.id" class="spin" :size="14" />
                <ShieldCheck v-else :size="14" />
                {{ article.status === 'published' ? '文章已发布' : (workingPlatform === platform.id ? '正在上传并发布…' : '立即发布到公众号') }}
              </button>
              <RouterLink class="button button-quiet" to="/settings">配置公众号</RouterLink>
            </div>

            <section class="wechat-schedule-box">
              <header><CalendarClock :size="16" /><strong>定时发布</strong></header>
              <div
                v-if="currentWechatSchedule"
                class="wechat-schedule-state"
                :class="currentWechatSchedule.status"
              >
                <div>
                  <strong>{{ scheduleStatusLabel(currentWechatSchedule.status) }}</strong>
                  <span>{{ formatTime(currentWechatSchedule.scheduled_at) }}</span>
                  <small v-if="currentWechatSchedule.last_error">{{ currentWechatSchedule.last_error }}</small>
                </div>
                <button
                  v-if="['pending', 'failed'].includes(currentWechatSchedule.status)"
                  type="button"
                  aria-label="取消定时发布"
                  :disabled="scheduleWorking"
                  @click="cancelWechatSchedule"
                >
                  <X :size="15" />
                </button>
              </div>
              <div v-if="article.status === 'generated'" class="wechat-schedule-form">
                <input
                  v-model="scheduleTime"
                  type="datetime-local"
                  :min="minScheduleTime"
                  :disabled="scheduleWorking || currentWechatSchedule?.status === 'processing'"
                  aria-label="微信公众号定时发布时间"
                />
                <button
                  class="button button-secondary"
                  type="button"
                  :disabled="scheduleWorking || currentWechatSchedule?.status === 'processing'"
                  @click="scheduleWechatPublish"
                >
                  <LoaderCircle v-if="scheduleWorking" class="spin" :size="14" />
                  <CalendarClock v-else :size="14" />
                  {{ currentWechatSchedule?.status === 'pending' ? '修改时间' : '加入定时发布' }}
                </button>
              </div>
              <p>任务保存在服务器，关闭电脑页面后仍会在设定时间自动执行。</p>
            </section>

            <button v-if="recordFor(platform.id)" class="publish-reset" type="button" :disabled="workingPlatform" @click="resetPlatform(platform)">
              <RotateCcw :size="13" />重置发布记录
            </button>
          </div>
          <div v-else class="publish-platform-actions">
            <button class="button button-primary" type="button" :disabled="workingPlatform" @click="preparePublish(platform)">
              <LoaderCircle v-if="workingPlatform === platform.id" class="spin" :size="14" />
              <ExternalLink v-else :size="14" />
              {{ recordFor(platform.id) ? '重新打开发布页' : '复制并打开发布页' }}
            </button>
            <button
              v-if="recordFor(platform.id)?.status !== 'published'"
              class="button button-quiet"
              type="button"
              :disabled="workingPlatform || !recordFor(platform.id)"
              @click="confirmPublished(platform)"
            >
              <Check :size="14" />确认已发布
            </button>
            <button v-else class="publish-reset" type="button" :disabled="workingPlatform" @click="resetPlatform(platform)">
              <RotateCcw :size="13" />重置状态
            </button>
          </div>
        </article>
      </div>

      <aside class="publish-safety-note">
        <Smartphone :size="19" />
        <div><strong>电脑和手机都可以继续发布</strong><p>发布记录保存在项目数据库。平台登录状态由浏览器自己管理，系统不会保存你的平台密码。</p></div>
        <Clipboard :size="19" />
      </aside>
    </template>

    <NoticeToast :message="notice" :type="noticeType" @close="notice = ''" />
  </section>
</template>
