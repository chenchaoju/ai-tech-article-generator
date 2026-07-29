<script setup>
import { computed } from 'vue'
import DOMPurify from 'dompurify'
import { marked } from 'marked'

const props = defineProps({
  content: { type: String, default: '' },
  emptyText: { type: String, default: '还没有正文内容' },
})

marked.setOptions({ breaks: true, gfm: true })
const html = computed(() => DOMPurify.sanitize(marked.parse(props.content || '')))
</script>

<template>
  <article v-if="content" class="markdown-body" v-html="html" />
  <div v-else class="markdown-empty">{{ emptyText }}</div>
</template>
