<script setup>
import {
  ArrowLeft,
  BarChart3,
  ExternalLink,
  FileText,
  Gauge,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Settings2,
  WalletCards,
} from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { articleApi, getApiError } from '../api/articles'
import NoticeToast from '../components/NoticeToast.vue'

const loading = ref(true)
const errorMessage = ref('')
const usage = ref(null)

const inputShare = computed(() => {
  if (!usage.value?.total_tokens) return 0
  return Math.round((usage.value.prompt_tokens / usage.value.total_tokens) * 100)
})

const outputShare = computed(() => Math.max(0, 100 - inputShare.value))
const budgetUsedPercent = computed(() => {
  if (!usage.value?.configured_token_budget) return 0
  return Math.min(
    100,
    Math.round((usage.value.total_tokens / usage.value.configured_token_budget) * 100),
  )
})

function formatNumber(value) {
  return Number(value || 0).toLocaleString('zh-CN')
}

function formatDate(value) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

async function loadUsage() {
  loading.value = true
  try {
    usage.value = await articleApi.tokenUsage()
  } catch (error) {
    errorMessage.value = getApiError(error, 'Token 统计加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(loadUsage)
</script>

<template>
  <section class="page usage-page">
    <header class="usage-header">
      <div>
        <RouterLink class="back-link" to="/articles"><ArrowLeft :size="16" />返回文章库</RouterLink>
        <h1>Token 统计</h1>
      </div>
      <button class="button button-secondary" type="button" :disabled="loading" @click="loadUsage">
        <LoaderCircle v-if="loading" class="spin" :size="16" /><RefreshCw v-else :size="16" />刷新统计
      </button>
    </header>

    <div v-if="loading && !usage" class="loading-state">
      <LoaderCircle class="spin" :size="27" />正在汇总 Token 用量…
    </div>

    <template v-else-if="usage">
      <section class="usage-kpi-grid">
        <article class="usage-kpi usage-kpi-total">
          <span><Sparkles :size="17" />累计消耗</span>
          <strong>{{ formatNumber(usage.total_tokens) }}</strong>
          <small>Token</small>
        </article>
        <article class="usage-kpi">
          <span><FileText :size="17" />输入 Token</span>
          <strong>{{ formatNumber(usage.prompt_tokens) }}</strong>
          <small>提示词、原文材料与稿件</small>
        </article>
        <article class="usage-kpi">
          <span><BarChart3 :size="17" />输出 Token</span>
          <strong>{{ formatNumber(usage.completion_tokens) }}</strong>
          <small>标题、正文与审核结果</small>
        </article>
        <article class="usage-kpi">
          <span><Gauge :size="17" />成功调用</span>
          <strong>{{ formatNumber(usage.request_count) }}</strong>
          <small>平均 {{ formatNumber(usage.average_tokens_per_request) }} Token / 次</small>
        </article>
      </section>

      <section class="usage-balance-panel">
        <div class="usage-balance-main">
          <span><WalletCards :size="18" />平台额度与预计剩余</span>
          <template v-if="usage.configured_token_budget">
            <strong>{{ formatNumber(usage.estimated_remaining_tokens) }} <small>Token</small></strong>
            <p>手动总额度 {{ formatNumber(usage.configured_token_budget) }}，本项目已记录使用 {{ budgetUsedPercent }}%</p>
            <div class="budget-progress"><i :style="{ width: `${budgetUsedPercent}%` }" /></div>
          </template>
          <template v-else>
            <strong class="balance-unavailable">官方接口暂不可查</strong>
            <p>智谱没有公开账户余额或资源包剩余 Token 查询 API，因此系统不会编造余额。</p>
          </template>
        </div>
        <div class="usage-balance-actions">
          <p>{{ usage.balance_note }}</p>
          <div>
            <RouterLink class="button button-secondary" to="/settings"><Settings2 :size="15" />填写总额度</RouterLink>
            <a class="button button-secondary" :href="usage.provider_console_url" target="_blank" rel="noreferrer">
              <ExternalLink :size="15" />查看智谱控制台
            </a>
          </div>
        </div>
      </section>

      <section class="usage-breakdown">
        <div class="usage-section-title">
          <div><span>01 / TOKEN MIX</span><h2>输入与输出占比</h2></div>
          <small>更新于 {{ formatDate(usage.updated_at) }}</small>
        </div>
        <div class="token-share-bar" aria-label="Token 输入输出占比">
          <span class="token-share-input" :style="{ width: `${inputShare}%` }" />
          <span class="token-share-output" :style="{ width: `${outputShare}%` }" />
        </div>
        <div class="token-share-legend">
          <span><i class="input" />输入 {{ inputShare }}%</span>
          <span><i class="output" />输出 {{ outputShare }}%</span>
        </div>
        <div class="usage-operation-grid">
          <div><strong>{{ formatNumber(usage.article_count) }}</strong><span>文章总数</span></div>
          <div><strong>{{ formatNumber(usage.generated_article_count) }}</strong><span>已完成文章</span></div>
          <div><strong>{{ formatNumber(usage.director_review_count) }}</strong><span>已完成终审</span></div>
          <div><strong>{{ formatDate(usage.initialized_at) }}</strong><span>统计起点</span></div>
        </div>
      </section>

      <section class="usage-detail-section">
        <div class="usage-section-title">
          <div><span>02 / ARTICLE BREAKDOWN</span><h2>最近文章消耗</h2></div>
          <small>显示最近 20 篇有 Token 记录的文章</small>
        </div>
        <div v-if="usage.recent_articles.length" class="usage-table-wrap">
          <table class="usage-table">
            <thead>
              <tr><th>文章</th><th>输入</th><th>输出</th><th>合计</th><th>更新时间</th></tr>
            </thead>
            <tbody>
              <tr v-for="article in usage.recent_articles" :key="article.id">
                <td><RouterLink :to="`/articles/${article.id}`"><strong>{{ article.title }}</strong><small>{{ article.topic }}</small></RouterLink></td>
                <td>{{ formatNumber(article.prompt_tokens) }}</td>
                <td>{{ formatNumber(article.completion_tokens) }}</td>
                <td><strong>{{ formatNumber(article.total_tokens) }}</strong></td>
                <td>{{ formatDate(article.updated_at) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="usage-empty"><BarChart3 :size="24" />还没有文章 Token 记录，生成第一篇文章后这里会自动更新。</div>
      </section>

      <div class="usage-scope-note">
        <ShieldCheck :size="16" />
        <p><strong>统计口径</strong>{{ usage.scope_note }}</p>
      </div>
    </template>

    <NoticeToast :message="errorMessage" type="error" @close="errorMessage = ''" />
  </section>
</template>
