<script setup>
import { FileText } from 'lucide-vue-next'

defineProps({
  title: { type: String, default: '还没有文章' },
  description: { type: String, default: '从一个真实的项目问题开始记录。' },
})
</script>

<template>
  <div class="empty-state">
    <span class="empty-icon"><FileText :size="25" /></span>
    <h3>{{ title }}</h3>
    <p>{{ description }}</p>
    <slot />
  </div>
</template>

