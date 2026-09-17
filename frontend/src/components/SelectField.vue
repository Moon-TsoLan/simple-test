<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

export interface SelectOption { value: string; label: string; hint?: string }

const props = withDefaults(defineProps<{
  modelValue: string | string[]
  options: SelectOption[]
  placeholder?: string
  multiple?: boolean
  searchable?: boolean
  disabled?: boolean
  clearable?: boolean
  ariaLabel?: string
}>(), {
  placeholder: '请选择',
  multiple: false,
  searchable: true,
  disabled: false,
  clearable: true,
})

const emit = defineEmits<{ 'update:modelValue': [string | string[]]; change: [string | string[]] }>()

const root = ref<HTMLElement | null>(null)
const searchBox = ref<HTMLInputElement | null>(null)
const listBox = ref<HTMLElement | null>(null)
const open = ref(false)
const dropUp = ref(false)
const keyword = ref('')
const activeIndex = ref(-1)
const listId = `sf-list-${Math.random().toString(36).slice(2, 9)}`

const selected = computed(() => (Array.isArray(props.modelValue) ? props.modelValue : props.modelValue ? [props.modelValue] : []))
const selectedSet = computed(() => new Set(selected.value))
const labelOf = computed(() => new Map(props.options.map(option => [option.value, option.label])))
const visible = computed(() => {
  const needle = keyword.value.trim().toLowerCase()
  if (!needle) return props.options
  return props.options.filter(option => `${option.label} ${option.hint || ''} ${option.value}`.toLowerCase().includes(needle))
})
const hasSelection = computed(() => selected.value.length > 0)
const triggerText = computed(() => {
  if (!hasSelection.value) return props.placeholder
  const first = labelOf.value.get(selected.value[0]) || selected.value[0]
  if (!props.multiple || selected.value.length === 1) return first
  return `${first} 等 ${selected.value.length} 项`
})

function emitValue(next: string | string[]) {
  emit('update:modelValue', next)
  emit('change', next)
}

function place() {
  const el = root.value
  if (!el) return
  const box = el.getBoundingClientRect()
  const gap = 6
  const chrome = (props.searchable ? 52 : 0) + (props.multiple ? 36 : 10)
  const spaceBelow = window.innerHeight - box.bottom - gap - 8
  const spaceAbove = box.top - gap - 8
  dropUp.value = spaceBelow < 240 && spaceAbove > spaceBelow
  const available = Math.max(0, dropUp.value ? spaceAbove : spaceBelow)
  const maxList = Math.max(132, Math.min(420, available - chrome))
  const minWidth = Math.min(Math.max(el.offsetWidth, 420), window.innerWidth - 24)
  const alignEnd = box.left + minWidth > window.innerWidth - 12
  el.style.setProperty('--sf-list-max', `${maxList}px`)
  el.style.setProperty('--sf-panel-min', `${Math.round(minWidth)}px`)
  el.classList.toggle('is-end', alignEnd)
}

async function openPanel() {
  if (props.disabled || open.value) return
  open.value = true
  keyword.value = ''
  place()
  activeIndex.value = Math.max(0, visible.value.findIndex(option => selectedSet.value.has(option.value)))
  await nextTick()
  place()
  if (props.searchable) searchBox.value?.focus()
  scrollActiveIntoView()
}

function closePanel() {
  if (!open.value) return
  open.value = false
  activeIndex.value = -1
}

function togglePanel() {
  if (open.value) closePanel()
  else void openPanel()
}

function choose(option: SelectOption) {
  if (props.multiple) {
    const next = selectedSet.value.has(option.value)
      ? selected.value.filter(value => value !== option.value)
      : [...selected.value, option.value]
    emitValue(next)
    return
  }
  emitValue(option.value)
  closePanel()
  root.value?.querySelector<HTMLButtonElement>('.sf-trigger')?.focus()
}

function clear(event: Event) {
  event.stopPropagation()
  emitValue(props.multiple ? [] : '')
}

function scrollActiveIntoView() {
  const node = listBox.value?.querySelector<HTMLElement>('.sf-option.is-active')
  node?.scrollIntoView({ block: 'nearest' })
}

function move(step: number) {
  if (!visible.value.length) return
  const total = visible.value.length
  activeIndex.value = (activeIndex.value + step + total) % total
  void nextTick(scrollActiveIntoView)
}

function onKeydown(event: KeyboardEvent) {
  if (!open.value) {
    if (['Enter', ' ', 'ArrowDown', 'ArrowUp'].includes(event.key)) {
      event.preventDefault()
      void openPanel()
    }
    return
  }
  if (event.key === 'Escape') { event.preventDefault(); closePanel(); return }
  if (event.key === 'ArrowDown') { event.preventDefault(); move(1); return }
  if (event.key === 'ArrowUp') { event.preventDefault(); move(-1); return }
  if (event.key === 'Home') { event.preventDefault(); activeIndex.value = 0; void nextTick(scrollActiveIntoView); return }
  if (event.key === 'End') { event.preventDefault(); activeIndex.value = visible.value.length - 1; void nextTick(scrollActiveIntoView); return }
  if (event.key === 'Enter') {
    event.preventDefault()
    const option = visible.value[activeIndex.value]
    if (option) choose(option)
    return
  }
  if (event.key === 'Tab') closePanel()
}

function onPointerDown(event: PointerEvent) {
  if (!open.value) return
  if (!root.value?.contains(event.target as Node)) closePanel()
}

watch(keyword, () => { activeIndex.value = visible.value.length ? 0 : -1 })
onMounted(() => {
  document.addEventListener('pointerdown', onPointerDown, true)
  window.addEventListener('resize', place)
  window.addEventListener('scroll', place, true)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onPointerDown, true)
  window.removeEventListener('resize', place)
  window.removeEventListener('scroll', place, true)
})
</script>

<template>
  <div ref="root" class="select-field" :class="{ 'is-open': open, 'is-disabled': disabled }" @keydown="onKeydown">
    <button
      type="button"
      class="sf-trigger"
      role="combobox"
      :aria-expanded="open"
      :aria-controls="listId"
      :aria-label="ariaLabel"
      :disabled="disabled"
      @click="togglePanel"
    >
      <span class="sf-value" :class="{ 'is-placeholder': !hasSelection }" :title="hasSelection ? triggerText : ''">{{ triggerText }}</span>
      <span v-if="multiple && selected.length > 1" class="sf-count">{{ selected.length }}</span>
      <i
        v-if="clearable && hasSelection && !disabled"
        class="sf-clear"
        role="button"
        tabindex="-1"
        aria-label="清除选择"
        @click="clear"
      >×</i>
      <i class="sf-caret" aria-hidden="true"></i>
    </button>

    <div v-if="open" class="sf-panel" :class="{ 'is-up': dropUp }">
      <div v-if="searchable" class="sf-search">
        <input ref="searchBox" v-model="keyword" type="text" placeholder="输入关键字筛选" aria-label="筛选选项" />
      </div>
      <ul :id="listId" ref="listBox" class="sf-list" role="listbox" :aria-multiselectable="multiple">
        <li
          v-for="(option, index) in visible"
          :key="option.value"
          class="sf-option"
          :class="{ 'is-active': index === activeIndex, 'is-selected': selectedSet.has(option.value) }"
          role="option"
          :aria-selected="selectedSet.has(option.value)"
          @mouseenter="activeIndex = index"
          @click="choose(option)"
        >
          <i v-if="multiple" class="sf-check" aria-hidden="true"></i>
          <span class="sf-option-main">
            <span class="sf-option-text" :title="option.label">{{ option.label }}</span>
            <small v-if="option.hint" class="sf-option-hint">{{ option.hint }}</small>
          </span>
        </li>
        <li v-if="!visible.length" class="sf-empty">没有匹配的选项</li>
      </ul>
      <div v-if="multiple" class="sf-footer">
        <span>已选 {{ selected.length }} / {{ options.length }}</span>
        <button type="button" @click="emitValue([])">清空</button>
      </div>
    </div>
  </div>
</template>
