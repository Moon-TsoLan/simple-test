<script setup lang="ts">
defineProps<{ title: string; description: string; action?: string }>()
defineEmits<{ action: [] }>()
</script>

<template>
  <div class="empty-state">
    <div class="empty-symbol">⌁</div>
    <h3>{{ title }}</h3>
    <p>{{ description }}</p>
    <button v-if="action" class="button secondary" @click="$emit('action')">{{ action }}</button>
  </div>
</template>
