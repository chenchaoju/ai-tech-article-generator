import { createRouter, createWebHistory } from 'vue-router'
import ArticleDetailView from '../views/ArticleDetailView.vue'
import ArticlePublishView from '../views/ArticlePublishView.vue'
import ArticleEditorView from '../views/ArticleEditorView.vue'
import ArticleListView from '../views/ArticleListView.vue'
import SettingsView from '../views/SettingsView.vue'
import TokenUsageView from '../views/TokenUsageView.vue'
import ImageLibraryView from '../views/ImageLibraryView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', redirect: '/articles' },
    { path: '/articles', name: 'articles', component: ArticleListView },
    { path: '/articles/new', name: 'article-new', component: ArticleEditorView },
    { path: '/articles/:id/edit', name: 'article-edit', component: ArticleEditorView },
    { path: '/articles/:id/publish', name: 'article-publish', component: ArticlePublishView },
    { path: '/articles/:id', name: 'article-detail', component: ArticleDetailView },
    { path: '/settings', name: 'settings', component: SettingsView },
    { path: '/usage', name: 'usage', component: TokenUsageView },
    { path: '/media', name: 'media-library', component: ImageLibraryView },
  ],
  scrollBehavior: (to, from, savedPosition) => {
    if (savedPosition) return savedPosition
    const editorRoutes = new Set(['article-new', 'article-edit'])
    if (editorRoutes.has(to.name) && editorRoutes.has(from.name)) return false
    return { top: 0 }
  },
})

export default router
