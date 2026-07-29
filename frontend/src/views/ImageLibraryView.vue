<script setup>
import {
  ArrowLeft,
  ArrowDown,
  ArrowUp,
  Check,
  ExternalLink,
  Folder,
  FolderCog,
  GripVertical,
  ImagePlus,
  Images,
  Link2,
  LoaderCircle,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  X,
} from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { articleApi, getApiError } from '../api/articles'
import NoticeToast from '../components/NoticeToast.vue'

const query = ref('')
const searchEngine = ref('bing')
const preferClean = ref(true)
const searching = ref(false)
const loadingAssets = ref(true)
const workingUrl = ref('')
const addingManual = ref(false)
const manualImageUrl = ref('')
const manualImageTitle = ref('')
const manualCategory = ref('未分类')
const results = ref([])
const assets = ref([])
const assetCategories = ref([])
const activeCategory = ref('全部')
const draggedAssetId = ref(null)
const showCategoryManager = ref(false)
const newCategoryName = ref('')
const categoryWorkingId = ref(null)
let dragOrderChanged = false
const currentPage = ref(1)
const hasMore = ref(true)
const lastSearchKey = ref('')
const seenResultUrls = ref([])
const notice = ref('')
const noticeType = ref('success')

const savedUrls = computed(() => new Set(assets.value.map((item) => item.image_url)))
const categoryNames = computed(() => assetCategories.value.map((item) => item.name))
const visibleAssets = computed(() => (
  activeCategory.value === '全部'
    ? assets.value
    : assets.value.filter((item) => (item.category || '未分类') === activeCategory.value)
))
const IMAGE_ENGINES = [
  { value: 'bing', label: 'Bing 全网' },
  { value: '360', label: '360 图片' },
  { value: 'baidu', label: '百度来源' },
  { value: 'sohu', label: '搜狐来源' },
]
const selectedEngineLabel = computed(
  () => IMAGE_ENGINES.find((item) => item.value === searchEngine.value)?.label || '图片搜索',
)

function showNotice(message, type = 'success') {
  notice.value = message
  noticeType.value = type
}

async function loadAssets() {
  try {
    const [assetData, categoryData] = await Promise.all([
      articleApi.listImageAssets(),
      articleApi.listImageAssetCategories(),
    ])
    assets.value = assetData
    assetCategories.value = categoryData
  } catch (error) {
    showNotice(getApiError(error, '图片素材库加载失败'), 'error')
  } finally {
    loadingAssets.value = false
  }
}

async function createCategory() {
  const name = newCategoryName.value.trim()
  if (!name) return showNotice('请输入分类名称', 'error')
  categoryWorkingId.value = 'new'
  try {
    const created = await articleApi.createImageAssetCategory(name)
    assetCategories.value.push(created)
    newCategoryName.value = ''
    activeCategory.value = created.name
    showNotice(`分类“${created.name}”已创建`)
  } catch (error) {
    showNotice(getApiError(error, '分类创建失败'), 'error')
  } finally {
    categoryWorkingId.value = null
  }
}

async function renameCategory(category) {
  const name = String(category.name || '').trim()
  if (!name) return loadAssets()
  categoryWorkingId.value = category.id
  try {
    const previousName = category._previousName || name
    const updated = await articleApi.updateImageAssetCategory(category.id, name)
    if (activeCategory.value === previousName) activeCategory.value = updated.name
    category._previousName = updated.name
    Object.assign(category, updated)
    assets.value.forEach((asset) => {
      if (asset.category === previousName) asset.category = updated.name
    })
    showNotice(`分类已重命名为“${updated.name}”`)
  } catch (error) {
    showNotice(getApiError(error, '分类重命名失败'), 'error')
    await loadAssets()
  } finally {
    categoryWorkingId.value = null
  }
}

async function deleteCategory(category) {
  if (category.name === '未分类') return
  const assetCount = assets.value.filter((asset) => asset.category === category.name).length
  const confirmed = window.confirm(
    `是否删除分类“${category.name}”及其中全部 ${assetCount} 张图片？\n\n点击“确定”会同时删除分类和图片；点击“取消”则不做任何改动。`,
  )
  if (!confirmed) return
  categoryWorkingId.value = category.id
  try {
    await articleApi.deleteImageAssetCategory(category.id)
    if (activeCategory.value === category.name) activeCategory.value = '全部'
    await loadAssets()
    showNotice(`分类“${category.name}”及其中 ${assetCount} 张素材已删除`)
  } catch (error) {
    showNotice(getApiError(error, '分类删除失败'), 'error')
  } finally {
    categoryWorkingId.value = null
  }
}

async function moveCategory(category, direction) {
  const index = assetCategories.value.findIndex((item) => item.id === category.id)
  const targetIndex = index + direction
  if (targetIndex < 0 || targetIndex >= assetCategories.value.length) return
  const next = [...assetCategories.value]
  ;[next[index], next[targetIndex]] = [next[targetIndex], next[index]]
  assetCategories.value = next
  try {
    assetCategories.value = await articleApi.reorderImageAssetCategories(
      next.map((item) => item.id),
    )
  } catch (error) {
    showNotice(getApiError(error, '分类排序保存失败'), 'error')
    await loadAssets()
  }
}

async function runImageSearch(nextPage = false) {
  const value = query.value.trim()
  if (!value) return showNotice('请输入想搜索的图片关键词', 'error')
  const searchKey = `${value}|${searchEngine.value}|${preferClean.value}`
  const isNewSearch = !nextPage || lastSearchKey.value !== searchKey
  const targetPage = isNewSearch ? 1 : currentPage.value + 1
  searching.value = true
  results.value = []
  try {
    const data = await articleApi.searchImages(
      value,
      10,
      targetPage,
      isNewSearch ? [] : seenResultUrls.value,
      searchEngine.value,
      preferClean.value,
    )
    results.value = data.items
    currentPage.value = data.page
    hasMore.value = data.has_more
    lastSearchKey.value = searchKey
    if (isNewSearch) seenResultUrls.value = []
    seenResultUrls.value = [
      ...new Set([...seenResultUrls.value, ...data.items.map((item) => item.image_url)]),
    ]
    if (!data.items.length) showNotice('没有找到可用图片，换一个关键词试试', 'error')
  } catch (error) {
    showNotice(getApiError(error, 'Bing 图片搜索失败'), 'error')
  } finally {
    searching.value = false
  }
}

async function addManualAsset() {
  const imageUrl = manualImageUrl.value.trim()
  if (!imageUrl) return showNotice('请粘贴图片地址', 'error')
  try {
    const parsed = new URL(imageUrl)
    if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('invalid')
  } catch {
    return showNotice('图片地址必须是 http 或 https 链接', 'error')
  }
  addingManual.value = true
  try {
    const saved = await articleApi.saveImageAsset({
      title: manualImageTitle.value.trim() || '手动添加图片',
      image_url: imageUrl,
      source_page_url: '',
      source_name: '手动添加',
      category: manualCategory.value.trim() || '未分类',
    })
    if (!assets.value.some((asset) => asset.id === saved.id)) assets.value.unshift(saved)
    manualImageUrl.value = ''
    manualImageTitle.value = ''
    manualCategory.value = '未分类'
    showNotice('图片已手动加入素材库')
  } catch (error) {
    showNotice(getApiError(error, '手动添加图片失败'), 'error')
  } finally {
    addingManual.value = false
  }
}

function dismissResult(item) {
  seenResultUrls.value = [...new Set([...seenResultUrls.value, item.image_url])]
  results.value = results.value.filter((result) => result.image_url !== item.image_url)
}

function searchImages() {
  return runImageSearch(false)
}

function nextImagePage() {
  return runImageSearch(true)
}

async function saveAsset(item) {
  if (savedUrls.value.has(item.image_url)) return
  workingUrl.value = item.image_url
  try {
    let targetCategory = activeCategory.value
    if (targetCategory === '全部') {
      const searchCategoryName = query.value.trim().slice(0, 100) || '未分类'
      let category = assetCategories.value.find(
        (candidate) => candidate.name === searchCategoryName,
      )
      if (!category) {
        category = await articleApi.createImageAssetCategory(searchCategoryName)
        assetCategories.value.push(category)
      }
      targetCategory = category.name
      activeCategory.value = targetCategory
    }
    const saved = await articleApi.saveImageAsset({
      ...item,
      category: targetCategory,
    })
    if (!assets.value.some((asset) => asset.id === saved.id)) assets.value.unshift(saved)
    showNotice(`图片已加入“${targetCategory}”分类，可在文章编辑页使用`)
  } catch (error) {
    showNotice(getApiError(error, '图片入库失败'), 'error')
  } finally {
    workingUrl.value = ''
  }
}

async function updateAssetCategory(asset) {
  const category = String(asset.category || '').trim() || '未分类'
  asset.category = category
  try {
    const updated = await articleApi.updateImageAsset(asset.id, { category })
    Object.assign(asset, updated)
    showNotice(`已移动到“${updated.category}”`)
  } catch (error) {
    showNotice(getApiError(error, '分类保存失败'), 'error')
    await loadAssets()
  }
}

function reorderAssetBefore(asset, target) {
  if (!asset || !target || asset.id === target.id || asset.category !== target.category) return false
  const sourceGlobalIndex = assets.value.findIndex((item) => item.id === asset.id)
  const targetGlobalIndex = assets.value.findIndex((item) => item.id === target.id)
  const nextAssets = [...assets.value]
  const [moved] = nextAssets.splice(sourceGlobalIndex, 1)
  const adjustedTargetIndex = sourceGlobalIndex < targetGlobalIndex
    ? targetGlobalIndex - 1
    : targetGlobalIndex
  if (sourceGlobalIndex === adjustedTargetIndex) return false
  nextAssets.splice(adjustedTargetIndex, 0, moved)
  assets.value = nextAssets
  return true
}

async function persistAssetOrder() {
  try {
    assets.value = await articleApi.reorderImageAssets(assets.value.map((item) => item.id))
  } catch (error) {
    showNotice(getApiError(error, '素材排序保存失败'), 'error')
    await loadAssets()
  }
}

function beginPointerSort(event, asset) {
  if (event.pointerType === 'mouse' && event.button !== 0) return
  draggedAssetId.value = asset.id
  dragOrderChanged = false
  document.addEventListener('pointermove', handlePointerSort)
  document.addEventListener('pointerup', endPointerSort, { once: true })
  document.addEventListener('pointercancel', endPointerSort, { once: true })
}

function handlePointerSort(event) {
  const source = assets.value.find((item) => item.id === draggedAssetId.value)
  const targetElement = document.elementFromPoint(event.clientX, event.clientY)
    ?.closest('[data-asset-id]')
  const targetId = Number(targetElement?.dataset.assetId)
  const target = assets.value.find((item) => item.id === targetId)
  if (reorderAssetBefore(source, target)) dragOrderChanged = true
}

async function endPointerSort() {
  document.removeEventListener('pointermove', handlePointerSort)
  document.removeEventListener('pointerup', endPointerSort)
  document.removeEventListener('pointercancel', endPointerSort)
  draggedAssetId.value = null
  if (dragOrderChanged) await persistAssetOrder()
  dragOrderChanged = false
}

async function deleteAsset(asset) {
  workingUrl.value = asset.image_url
  try {
    await articleApi.deleteImageAsset(asset.id)
    assets.value = assets.value.filter((item) => item.id !== asset.id)
    showNotice('图片素材已删除')
  } catch (error) {
    showNotice(getApiError(error, '图片删除失败'), 'error')
  } finally {
    workingUrl.value = ''
  }
}

onMounted(loadAssets)
onBeforeUnmount(() => {
  document.removeEventListener('pointermove', handlePointerSort)
  document.removeEventListener('pointerup', endPointerSort)
  document.removeEventListener('pointercancel', endPointerSort)
})
</script>

<template>
  <section class="page media-library-page">
    <header class="media-library-hero">
      <div>
        <RouterLink to="/articles"><ArrowLeft :size="15" />返回文章库</RouterLink>
        <h1>图片素材库</h1>
      </div>
      <div class="media-library-count"><Images :size="22" /><strong>{{ assets.length }}</strong><span>已收藏素材</span></div>
    </header>

    <section class="media-search-panel">
      <div class="media-engine-tabs" role="group" aria-label="图片搜索渠道">
        <button
          v-for="engine in IMAGE_ENGINES"
          :key="engine.value"
          type="button"
          :class="{ active: searchEngine === engine.value }"
          @click="searchEngine = engine.value"
        >
          {{ engine.label }}
        </button>
        <label class="clean-image-toggle">
          <input v-model="preferClean" type="checkbox" />
          <span>优先无水印 / Logo</span>
        </label>
      </div>
      <label class="media-search-box">
        <Search :size="20" />
        <input v-model="query" placeholder="例如：FastAPI 架构、夏日美食、城市夜景" @keyup.enter="searchImages" />
        <button type="button" :disabled="searching" @click="searchImages">
          <LoaderCircle v-if="searching" class="spin" :size="16" /><Search v-else :size="16" />
          {{ searching ? '搜索中…' : '搜索图片' }}
        </button>
      </label>
      <p>每页显示 10 张大尺寸图片。“百度来源”和“搜狐来源”按图片原始页面筛选；结果不会自动进入文章。</p>
      <div class="manual-image-entry">
        <div><Link2 :size="16" /><span><strong>手动添加图片</strong><small>粘贴可直接访问的图片地址</small></span></div>
        <input v-model="manualImageTitle" maxlength="255" placeholder="图片名称（可选）" />
        <select v-model="manualCategory" aria-label="选择素材分类">
          <option v-for="category in categoryNames" :key="category" :value="category">{{ category }}</option>
        </select>
        <input v-model="manualImageUrl" type="url" placeholder="https://example.com/image.jpg" @keyup.enter="addManualAsset" />
        <button type="button" :disabled="addingManual" @click="addManualAsset">
          <LoaderCircle v-if="addingManual" class="spin" :size="14" /><ImagePlus v-else :size="14" />
          加入素材库
        </button>
      </div>
    </section>

    <section v-if="results.length || searching" class="media-section">
      <header>
        <div><span>01 / IMAGE RESULTS</span><h2>{{ selectedEngineLabel }}</h2></div>
        <div class="media-result-pagination">
          <strong>第 {{ currentPage }} 页 · {{ results.length }} 张</strong>
          <button type="button" :disabled="searching || !hasMore" @click="nextImagePage">
            <LoaderCircle v-if="searching" class="spin" :size="14" /><RefreshCw v-else :size="14" />
            {{ hasMore ? '下一页，换一批' : '没有更多了' }}
          </button>
        </div>
      </header>
      <div v-if="searching" class="loading-state"><LoaderCircle class="spin" :size="24" />正在查找可用图片…</div>
      <div v-else class="media-image-grid">
        <article v-for="item in results" :key="item.image_url">
          <button class="media-dismiss-result" type="button" title="隐藏这张图片" aria-label="隐藏这张图片" @click="dismissResult(item)"><X :size="13" /></button>
          <img :src="item.image_url" :alt="item.title" loading="lazy" referrerpolicy="no-referrer" />
          <div><strong>{{ item.title }}</strong><small>{{ item.source_name || '网页图片' }}</small></div>
          <div class="media-card-actions">
            <button type="button" :disabled="savedUrls.has(item.image_url) || Boolean(workingUrl)" @click="saveAsset(item)">
              <Check v-if="savedUrls.has(item.image_url)" :size="14" />
              <LoaderCircle v-else-if="workingUrl === item.image_url" class="spin" :size="14" />
              <ImagePlus v-else :size="14" />
              {{ savedUrls.has(item.image_url) ? '已在素材库' : '加入素材库' }}
            </button>
            <a v-if="item.source_page_url" :href="item.source_page_url" target="_blank" rel="noreferrer"><ExternalLink :size="13" />来源页面</a>
          </div>
        </article>
      </div>
    </section>

    <section class="media-section media-saved-section">
      <header>
        <div><span>02 / SAVED ASSETS</span><h2>我的图片素材库</h2></div>
        <div class="asset-library-header-actions">
          <strong>{{ visibleAssets.length }} / {{ assets.length }} 张</strong>
          <button type="button" :class="{ active: showCategoryManager }" @click="showCategoryManager = !showCategoryManager">
            <FolderCog :size="14" />分类管理
          </button>
        </div>
      </header>
      <div class="asset-category-bar">
        <button type="button" :class="{ active: activeCategory === '全部' }" @click="activeCategory = '全部'">
          全部 <span>{{ assets.length }}</span>
        </button>
        <button
          v-for="category in assetCategories"
          :key="category.id"
          type="button"
          :class="{ active: activeCategory === category.name }"
          @click="activeCategory = category.name"
        >
          {{ category.name }} <span>{{ assets.filter((item) => (item.category || '未分类') === category.name).length }}</span>
        </button>
      </div>
      <section v-if="showCategoryManager" class="asset-category-manager">
        <header>
          <div><FolderCog :size="17" /><span><strong>分类管理</strong><small>新建、重命名、删除或调整分类顺序</small></span></div>
          <button type="button" aria-label="关闭分类管理" @click="showCategoryManager = false"><X :size="14" /></button>
        </header>
        <div class="category-create-row">
          <input v-model="newCategoryName" maxlength="100" placeholder="输入新分类名称" @keyup.enter="createCategory" />
          <button type="button" :disabled="categoryWorkingId === 'new'" @click="createCategory">
            <LoaderCircle v-if="categoryWorkingId === 'new'" class="spin" :size="13" /><Plus v-else :size="13" />新建分类
          </button>
        </div>
        <div class="category-manager-list">
          <article v-for="(category, index) in assetCategories" :key="category.id">
            <GripVertical :size="14" />
            <input
              v-model="category.name"
              maxlength="100"
              :disabled="category.name === '未分类' || categoryWorkingId === category.id"
              @focus="category._previousName = category.name"
              @change="renameCategory(category)"
            />
            <span>{{ assets.filter((item) => (item.category || '未分类') === category.name).length }} 张</span>
            <button type="button" :disabled="index === 0" title="分类前移" @click="moveCategory(category, -1)"><ArrowUp :size="13" /></button>
            <button type="button" :disabled="index === assetCategories.length - 1" title="分类后移" @click="moveCategory(category, 1)"><ArrowDown :size="13" /></button>
            <button class="danger" type="button" :disabled="category.name === '未分类' || categoryWorkingId === category.id" title="删除分类" @click="deleteCategory(category)"><Trash2 :size="13" /></button>
          </article>
        </div>
      </section>
      <div v-if="loadingAssets" class="loading-state"><LoaderCircle class="spin" :size="24" />正在读取素材库…</div>
      <div v-else-if="visibleAssets.length" class="media-image-grid">
        <article
          v-for="asset in visibleAssets"
          :key="asset.id"
          :data-asset-id="asset.id"
          :class="{ dragging: draggedAssetId === asset.id }"
        >
          <button class="asset-drag-handle" type="button" title="按住拖动排序" aria-label="按住拖动排序" @pointerdown.prevent="beginPointerSort($event, asset)"><GripVertical :size="14" /></button>
          <img :src="asset.image_url" :alt="asset.title" loading="lazy" referrerpolicy="no-referrer" />
          <div>
            <strong>{{ asset.title }}</strong>
            <small>{{ asset.source_name || '已收藏图片' }}</small>
            <label class="asset-category-field">
              <Folder :size="12" />
              <select v-model="asset.category" aria-label="素材分类" @change="updateAssetCategory(asset)">
                <option v-for="category in categoryNames" :key="category" :value="category">{{ category }}</option>
              </select>
            </label>
          </div>
          <div class="media-card-actions">
            <RouterLink :to="`/articles/new?asset=${asset.id}`"><ImagePlus :size="13" />去创作台使用</RouterLink>
            <button class="danger" type="button" :disabled="workingUrl === asset.image_url" @click="deleteAsset(asset)">
              <LoaderCircle v-if="workingUrl === asset.image_url" class="spin" :size="13" /><Trash2 v-else :size="13" />删除
            </button>
          </div>
        </article>
      </div>
      <div v-else class="media-empty"><Images :size="30" /><strong>{{ assets.length ? '这个分类还没有图片' : '素材库还是空的' }}</strong><span>可以切换分类，或在上方搜索图片并加入素材库。</span></div>
    </section>

    <NoticeToast :message="notice" :type="noticeType" @close="notice = ''" />
  </section>
</template>
