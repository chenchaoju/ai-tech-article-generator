<script setup>
import { AlertCircle, CheckCircle2, X } from 'lucide-vue-next'

defineProps({
  message: { type: String, default: '' },
  type: { type: String, default: 'success' },
})
defineEmits(['close'])
</script>

<template>
  <Transition name="toast">
    <div v-if="message" class="toast" :class="`toast-${type}`" role="status">
      <CheckCircle2 v-if="type === 'success'" :size="19" />
      <AlertCircle v-else :size="19" />
      <span>{{ message }}</span>
      <button class="icon-button" type="button" aria-label="关闭提示" @click="$emit('close')">
        <X :size="16" />
      </button>
    </div>
  </Transition>
</template>

