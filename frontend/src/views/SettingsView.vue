<script setup>
import {
  ArrowLeft,
  CheckCircle2,
  CirclePlus,
  Eye,
  EyeOff,
  KeyRound,
  LoaderCircle,
  MessageSquareText,
  Radar,
  Save,
  ShieldCheck,
  SlidersHorizontal,
  TestTube2,
  Send,
} from 'lucide-vue-next'
import { onMounted, reactive, ref } from 'vue'
import { articleApi, getApiError } from '../api/articles'
import NoticeToast from '../components/NoticeToast.vue'

const loading = ref(true)
const saving = ref(false)
const testing = ref(false)
const showKey = ref(false)
const showWechatSecret = ref(false)
const wechatTesting = ref(false)
const switchingProfileId = ref('')
const configured = ref(false)
const wechatConfigured = ref(false)
const maskedKey = ref('')
const maskedWechatSecret = ref('')
const profiles = ref([])
const activeProfileId = ref('')
const profileName = ref('默认模型')
const creatingProfile = ref(false)
const notice = reactive({ message: '', type: 'success' })

const form = reactive({
  api_key: '',
  base_url: 'https://open.bigmodel.cn/api/paas/v4',
  title_model: 'glm-4-flash-250414',
  expert_model: 'glm-4.6',
  writer_model: 'glm-4.6',
  reviewer_model: 'glm-4-flash-250414',
  director_model: 'glm-4.6',
  temperature: 0.5,
  max_tokens: 50000,
  enable_thinking: false,
  search_engine: 'search_std',
  search_count: 10,
  proxy_url: '',
  token_budget: 0,
  wechat_app_id: '',
  wechat_app_secret: '',
  wechat_author: '',
})

function toast(message, type = 'success') {
  notice.message = message
  notice.type = type
}

function applySettings(data) {
  configured.value = data.api_key_configured
  maskedKey.value = data.api_key_masked
  wechatConfigured.value = data.wechat_configured
  maskedWechatSecret.value = data.wechat_secret_masked
  Object.assign(form, {
    base_url: data.base_url,
    title_model: data.title_model,
    expert_model: data.expert_model,
    writer_model: data.writer_model,
    reviewer_model: data.reviewer_model,
    director_model: data.director_model,
    temperature: data.temperature,
    max_tokens: data.max_tokens,
    enable_thinking: data.enable_thinking,
    search_engine: data.search_engine,
    search_count: data.search_count,
    proxy_url: data.proxy_url,
    token_budget: data.token_budget,
    wechat_app_id: data.wechat_app_id,
    wechat_author: data.wechat_author,
  })
}

function applyProfiles(data) {
  profiles.value = data.profiles || []
  activeProfileId.value = data.active_profile_id || ''
  const activeProfile = profiles.value.find((profile) => profile.id === activeProfileId.value)
  profileName.value = activeProfile?.name || '默认模型'
  creatingProfile.value = false
}

function modelProfilePayload() {
  return {
    name: profileName.value.trim(),
    api_key: form.api_key.trim() || undefined,
    base_url: form.base_url,
    title_model: form.title_model,
    expert_model: form.expert_model,
    writer_model: form.writer_model,
    reviewer_model: form.reviewer_model,
    director_model: form.director_model,
    temperature: form.temperature,
    max_tokens: form.max_tokens,
    enable_thinking: form.enable_thinking,
    proxy_url: form.proxy_url,
    token_budget: form.token_budget,
  }
}

async function load() {
  try {
    const [settingsData, profileData] = await Promise.all([
      articleApi.getSettings(),
      articleApi.listModelProfiles(),
    ])
    applySettings(settingsData)
    applyProfiles(profileData)
  } catch (error) {
    toast(getApiError(error, '模型设置加载失败'), 'error')
  } finally {
    loading.value = false
  }
}

function startNewProfile() {
  creatingProfile.value = true
  profileName.value = ''
  configured.value = false
  maskedKey.value = ''
  form.api_key = ''
  form.base_url = 'https://api.openai.com/v1'
  form.title_model = ''
  form.expert_model = ''
  form.writer_model = ''
  form.reviewer_model = ''
  form.director_model = ''
  form.temperature = 0.5
  form.max_tokens = 50000
  form.enable_thinking = false
  form.proxy_url = ''
  form.token_budget = 0
}

async function switchProfile(profile) {
  if (profile.id === activeProfileId.value && !creatingProfile.value) return
  switchingProfileId.value = profile.id
  try {
    applySettings(await articleApi.activateModelProfile(profile.id))
    applyProfiles(await articleApi.listModelProfiles())
    form.api_key = ''
    toast(`已切换到“${profile.name}”，后续生成将使用这套模型`)
  } catch (error) {
    toast(getApiError(error, '模型切换失败'), 'error')
  } finally {
    switchingProfileId.value = ''
  }
}

async function save() {
  saving.value = true
  try {
    if (!profileName.value.trim()) {
      toast('请先填写配置名称', 'error')
      return
    }
    const profilePayload = modelProfilePayload()
    const profileData = creatingProfile.value
      ? await articleApi.createModelProfile(profilePayload)
      : await articleApi.updateModelProfile(activeProfileId.value, profilePayload)
    applyProfiles(profileData)

    const payload = { ...form }
    if (!payload.api_key.trim()) delete payload.api_key
    if (!payload.wechat_app_secret.trim()) delete payload.wechat_app_secret
    const data = await articleApi.updateSettings(payload)
    applySettings(data)
    form.api_key = ''
    form.wechat_app_secret = ''
    toast(`“${profileName.value}”已保存并设为当前模型`)
  } catch (error) {
    toast(getApiError(error, '保存失败'), 'error')
  } finally {
    saving.value = false
  }
}

async function testWechatConnection() {
  wechatTesting.value = true
  try {
    const payload = { app_id: form.wechat_app_id }
    if (form.wechat_app_secret.trim()) payload.app_secret = form.wechat_app_secret
    const result = await articleApi.testWechat(payload)
    toast(result.message)
  } catch (error) {
    toast(getApiError(error, '微信公众号连接测试失败'), 'error')
  } finally {
    wechatTesting.value = false
  }
}

async function testConnection() {
  testing.value = true
  try {
    const payload = { ...form }
    if (!payload.api_key.trim()) delete payload.api_key
    const result = await articleApi.testSettings(payload)
    toast(result.message)
  } catch (error) {
    toast(getApiError(error, '连接测试失败'), 'error')
  } finally {
    testing.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="page settings-page">
    <header class="settings-hero">
      <div>
        <RouterLink class="back-link" to="/articles"><ArrowLeft :size="16" />返回文章库</RouterLink>
        <h1>模型设置</h1>
      </div>
      <div class="config-status" :class="{ ready: configured }">
        <span class="status-light" />
        <div>
          <small>API STATUS</small>
          <strong>{{ creatingProfile ? '新建配置' : profileName }}</strong>
          <span>{{ configured ? maskedKey : '等待填写 API Key' }}</span>
        </div>
      </div>
    </header>

    <div v-if="loading" class="loading-state"><LoaderCircle class="spin" :size="24" />读取设置中…</div>

    <form v-else class="settings-layout" @submit.prevent="save">
      <section class="model-profile-panel">
        <div class="model-profile-head">
          <div>
            <span class="eyebrow">MODEL PROFILES</span>
            <h2>模型配置方案</h2>
            <p>点击已保存的配置即可切换，下一次搜索、写作和审核会立即使用当前方案。</p>
          </div>
          <button class="button button-secondary" type="button" @click="startNewProfile">
            <CirclePlus :size="16" />新增配置
          </button>
        </div>
        <div class="model-profile-list">
          <button
            v-for="profile in profiles"
            :key="profile.id"
            class="model-profile-item"
            :class="{ active: profile.id === activeProfileId && !creatingProfile }"
            type="button"
            :disabled="Boolean(switchingProfileId)"
            @click="switchProfile(profile)"
          >
            <span class="model-profile-check">
              <LoaderCircle v-if="switchingProfileId === profile.id" class="spin" :size="17" />
              <CheckCircle2 v-else-if="profile.id === activeProfileId && !creatingProfile" :size="17" />
              <span v-else />
            </span>
            <span class="model-profile-copy">
              <strong>{{ profile.name }}</strong>
              <small>{{ profile.writer_model }} · {{ profile.api_key_masked || '未配置密钥' }}</small>
            </span>
            <em>{{ profile.id === activeProfileId && !creatingProfile ? '当前使用' : '点击切换' }}</em>
          </button>
          <div v-if="creatingProfile" class="model-profile-item active model-profile-draft">
            <span class="model-profile-check"><CirclePlus :size="17" /></span>
            <span class="model-profile-copy">
              <strong>正在新建配置</strong>
              <small>填写下方信息并保存后自动启用</small>
            </span>
            <em>未保存</em>
          </div>
        </div>
      </section>

      <section class="settings-card settings-card-key">
        <div class="settings-card-index">01</div>
        <div class="settings-card-head">
          <KeyRound :size="20" />
          <div><h2>访问凭证</h2></div>
        </div>
        <label class="field field-dark">
          <span>配置名称</span>
          <input v-model="profileName" maxlength="60" required placeholder="例如：GLM 主力、GPT 写作、低成本备用" />
        </label>
        <label class="field field-dark">
          <span>API Key / Token</span>
          <div class="password-field">
            <input
              v-model="form.api_key"
              :type="showKey ? 'text' : 'password'"
              :placeholder="configured ? `已配置：${maskedKey}（留空表示不修改）` : '输入当前模型服务的 API Key'"
              autocomplete="off"
            />
            <button type="button" :aria-label="showKey ? '隐藏密钥' : '显示密钥'" @click="showKey = !showKey">
              <EyeOff v-if="showKey" :size="17" /><Eye v-else :size="17" />
            </button>
          </div>
        </label>
        <label class="field field-dark">
          <span>API Base URL</span>
          <input v-model="form.base_url" required />
        </label>
        <label class="field field-dark">
          <span>网络代理（可选）</span>
          <input v-model="form.proxy_url" placeholder="例如：http://127.0.0.1:7897" />
        </label>
        <div class="security-note"><ShieldCheck :size="17" /><span>所有模型方案写入项目根目录 <code>.env</code>，接口只返回脱敏密钥。</span></div>
      </section>

      <section class="settings-card">
        <div class="settings-card-index">02</div>
        <div class="settings-card-head">
          <SlidersHorizontal :size="20" />
          <div><h2>标题与角色模型</h2></div>
        </div>
        <label class="field">
          <span>标题模型（建议使用快速模型）</span>
          <input v-model="form.title_model" required />
        </label>
        <div class="four-fields">
          <label class="field">
            <span>内容专家模型</span>
            <input v-model="form.expert_model" required />
            <small>先整理可拓展论点、依据、字数规划和事实边界。</small>
          </label>
          <label class="field">
            <span>写手模型</span>
            <input v-model="form.writer_model" required />
          </label>
          <label class="field">
            <span>首轮备用模型</span>
            <input v-model="form.reviewer_model" required />
            <small>写手与审核官共用一次调用；主模型失败时才使用这里的备用模型。</small>
          </label>
          <label class="field">
            <span>编辑总监模型</span>
            <input v-model="form.director_model" required />
          </label>
        </div>
        <div class="two-fields">
          <label class="field">
            <span>Temperature</span>
            <input v-model.number="form.temperature" type="number" min="0" max="2" step="0.1" />
          </label>
          <label class="field">
            <span>最大输出 Tokens（最高 50,000）</span>
            <input v-model.number="form.max_tokens" type="number" min="1024" max="50000" step="1024" />
          </label>
        </div>
        <label class="field">
          <span>账户或资源包 Token 总额度（可选，手动填写）</span>
          <input v-model.number="form.token_budget" type="number" min="0" step="1000000" placeholder="例如：20000000" />
          <small>智谱暂未开放余额查询 API；填写后，统计页会用“总额度－本项目累计用量”估算剩余。</small>
        </label>
        <p class="card-footnote">专家先准备论点资料，写手与审核官完成初稿和审核；审核官可要求写手补充，总监发现不足时会结合专家解析和当前文章亲自重组、扩写与总结。</p>
      </section>

      <section class="settings-card">
        <div class="settings-card-index">03</div>
        <div class="settings-card-head">
          <Radar :size="20" />
          <div><h2>联网检索</h2></div>
        </div>
        <div class="two-fields">
          <label class="field">
            <span>搜索引擎</span>
            <select v-model="form.search_engine">
              <option value="search_std">search_std</option>
              <option value="search_pro">search_pro</option>
            </select>
          </label>
          <label class="field">
            <span>返回数量</span>
            <input v-model.number="form.search_count" type="number" min="3" max="20" />
          </label>
        </div>
        <p class="card-footnote">系统读取用户选中的公开原文作为事实依据，保留来源链接并独立重写；不得逐句替换或冒充个人经历。</p>
      </section>

      <section class="settings-card settings-card-wechat">
        <div class="settings-card-index">04</div>
        <div class="settings-card-head">
          <MessageSquareText :size="20" />
          <div><h2>微信公众号发布</h2></div>
        </div>
        <label class="field">
          <span>公众号 AppID</span>
          <input v-model="form.wechat_app_id" placeholder="在公众号后台「开发设置」中查看" />
        </label>
        <label class="field">
          <span>公众号 AppSecret</span>
          <div class="password-field password-field-light">
            <input
              v-model="form.wechat_app_secret"
              :type="showWechatSecret ? 'text' : 'password'"
              :placeholder="wechatConfigured ? `已配置：${maskedWechatSecret}（留空表示不修改）` : '输入公众号 AppSecret'"
              autocomplete="off"
            />
            <button type="button" :aria-label="showWechatSecret ? '隐藏密钥' : '显示密钥'" @click="showWechatSecret = !showWechatSecret">
              <EyeOff v-if="showWechatSecret" :size="17" /><Eye v-else :size="17" />
            </button>
          </div>
        </label>
        <label class="field">
          <span>默认作者名</span>
          <input v-model="form.wechat_author" maxlength="16" placeholder="显示在公众号文章作者位置" />
        </label>
        <div class="wechat-config-state" :class="{ ready: wechatConfigured }">
          <ShieldCheck :size="16" />
          <span>{{ wechatConfigured ? '微信发布凭证已保存' : '等待配置公众号凭证' }}</span>
        </div>
        <button
          class="button button-secondary"
          type="button"
          :disabled="wechatTesting || (!wechatConfigured && (!form.wechat_app_id.trim() || !form.wechat_app_secret.trim()))"
          @click="testWechatConnection"
        >
          <LoaderCircle v-if="wechatTesting" class="spin" :size="15" /><Send v-else :size="15" />
          {{ wechatTesting ? '正在连接微信…' : '测试微信公众号连接' }}
        </button>
        <p class="card-footnote">需要在公众号后台开启开发者能力，并把本机公网出口 IP 加入白名单。AppSecret 只保存在后端 .env。</p>
      </section>

      <div class="settings-actions">
        <button class="button button-secondary" type="button" :disabled="testing || (!configured && !form.api_key.trim())" @click="testConnection">
          <LoaderCircle v-if="testing" class="spin" :size="16" /><TestTube2 v-else :size="16" />
          测试当前填写配置
        </button>
        <button class="button button-primary" type="submit" :disabled="saving">
          <LoaderCircle v-if="saving" class="spin" :size="16" /><Save v-else :size="16" />
          保存模型设置
        </button>
      </div>
    </form>

    <NoticeToast :message="notice.message" :type="notice.type" @close="notice.message = ''" />
  </section>
</template>
