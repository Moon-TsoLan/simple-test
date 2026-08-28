<script setup lang="ts">
defineProps<{ label: string; value: string | number; detail: string; tone?: 'ink' | 'coral' | 'jade' }>()
</script>

<template>
  <article class="metric-card" :class="`tone-${tone || 'ink'}`">
    <span>{{ label }}</span><strong>{{ value }}</strong><small>{{ detail }}</small>
  </article>
</template>
