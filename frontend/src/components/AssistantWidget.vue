<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import type { ChartConfig } from '../types'
import {
  canvasCsvUrl,
  generateChart,
  type CanvasState,
  type SourceRef,
} from '../lib/agentClient'

const props = defineProps<{
  aspectRatio: '9:16' | '4:5'
  animationDuration: number
}>()

const emit = defineEmits<{ apply: [config: ChartConfig] }>()

const open = ref(false)
const topic = ref('')
const language = ref('English')

const running = ref(false)
const stage = ref('')
const transcript = ref('')
const canvas = ref<CanvasState | null>(null)
const sources = ref<SourceRef[]>([])
const notices = ref<string[]>([])
const errorMessage = ref('')
const result = ref<ChartConfig | null>(null)
const runId = ref('')
const showSources = ref(false)

let controller: AbortController | null = null

const canRun = computed(() => topic.value.trim().length > 1 && !running.value)

// The gap report is the honest progress signal: rows alone can look complete
// while a whole series is still missing.
const outstanding = computed(() =>
  (canvas.value?.missing ?? []).reduce((n, m) => n + m.missing_periods.length, 0),
)

function reset() {
  stage.value = ''
  transcript.value = ''
  canvas.value = null
  sources.value = []
  notices.value = []
  errorMessage.value = ''
  result.value = null
  runId.value = ''
}

async function run() {
  if (!canRun.value) return
  reset()
  running.value = true
  controller = new AbortController()

  try {
    for await (const event of generateChart(
      {
        topic: topic.value.trim(),
        language: language.value.trim() || 'English',
        aspectRatio: props.aspectRatio,
        animationDuration: props.animationDuration,
      },
      controller.signal,
    )) {
      switch (event.type) {
        case 'run':
          runId.value = event.runId
          break
        case 'stage':
          stage.value = event.status === 'done' ? `${event.name} done` : `${event.name}…`
          break
        case 'token':
          transcript.value += (transcript.value ? '\n\n' : '') + event.text
          break
        case 'canvas':
          canvas.value = event.canvas
          break
        case 'sources':
          // Same URL can be returned by several searches; show each once.
          for (const source of event.sources) {
            if (!sources.value.some((s) => s.url === source.url)) sources.value.push(source)
          }
          break
        case 'notice':
          notices.value.push(
            Object.values(event.notice).flat().map(String).join('; '),
          )
          break
        case 'config':
          result.value = event.config
          break
        case 'error':
          errorMessage.value = event.message
          break
      }
    }
  } catch (err) {
    if ((err as Error)?.name !== 'AbortError') {
      errorMessage.value = (err as Error)?.message ?? 'the run failed'
    }
  } finally {
    running.value = false
    controller = null
  }
}

function stop() {
  controller?.abort()
  running.value = false
}

function apply() {
  if (result.value) emit('apply', result.value)
}

onUnmounted(() => controller?.abort())
</script>

<template>
  <div class="assistant">
    <button v-if="!open" class="fab" title="Generate a chart with AI" @click="open = true">
      ✨
    </button>

    <section v-else class="panel">
      <header class="panel-head">
        <strong>Generate a chart</strong>
        <button class="icon" title="Close" @click="open = false">×</button>
      </header>

      <div class="field">
        <label>Topic</label>
        <input
          v-model="topic"
          placeholder="Tesla vs BYD annual deliveries, 2022 to 2024"
          :disabled="running"
          @keyup.enter="run"
        />
      </div>

      <div class="field">
        <label>Language</label>
        <input v-model="language" placeholder="English" :disabled="running" />
      </div>

      <div class="actions">
        <button v-if="!running" class="primary" :disabled="!canRun" @click="run">
          Research &amp; build
        </button>
        <button v-else @click="stop">Stop</button>
        <span class="stage">{{ stage }}</span>
      </div>

      <p v-if="running" class="hint">
        Researching takes a few minutes — sources are checked as they are found.
      </p>

      <div v-if="errorMessage" class="error">{{ errorMessage }}</div>

      <div v-if="canvas" class="canvas-summary">
        <div class="row">
          <span>{{ canvas.rows }} datapoints</span>
          <span>{{ canvas.series.length }} series</span>
          <span v-if="canvas.range">{{ canvas.range.start }}–{{ canvas.range.end }}</span>
        </div>
        <div class="row muted">
          <span v-if="outstanding">{{ outstanding }} still missing</span>
          <span v-else-if="canvas.rows">complete</span>
          <span v-if="canvas.conflicts">{{ canvas.conflicts }} conflicting</span>
        </div>
      </div>

      <pre v-if="transcript" class="transcript">{{ transcript }}</pre>

      <div v-if="notices.length" class="notices">
        <div v-for="(note, i) in notices" :key="i">{{ note }}</div>
      </div>

      <div v-if="sources.length" class="sources">
        <button class="disclosure" @click="showSources = !showSources">
          {{ showSources ? '▾' : '▸' }} {{ sources.length }} sources
        </button>
        <ul v-if="showSources">
          <li v-for="source in sources" :key="source.url">
            <a :href="source.url" target="_blank" rel="noopener noreferrer">
              {{ source.title || source.url }}
            </a>
          </li>
        </ul>
      </div>

      <div v-if="result" class="result">
        <div class="result-title">{{ result.title }}</div>
        <div class="result-sub">{{ result.subtitle }}</div>
        <button class="primary wide" @click="apply">Apply to chart</button>
        <a v-if="runId" class="csv" :href="canvasCsvUrl(runId)" download>
          Download the data with its sources
        </a>
      </div>
    </section>
  </div>
</template>

<style scoped>
.assistant {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 50;
}

.fab {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  font-size: 22px;
  background: var(--accent);
  border-color: var(--accent);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.45);
}

.panel {
  width: 380px;
  max-height: min(620px, calc(100vh - 48px));
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.5);
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.icon {
  padding: 2px 10px;
  font-size: 18px;
  line-height: 1;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.field label {
  font-size: 12px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.stage {
  font-size: 12px;
  color: var(--text-muted);
}

.hint,
.notices {
  font-size: 12px;
  color: #777;
}

.error {
  font-size: 13px;
  color: #f74f4f;
  border: 1px solid #f74f4f55;
  border-radius: 6px;
  padding: 8px 10px;
}

.canvas-summary {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 13px;
}

.canvas-summary .row {
  display: flex;
  gap: 12px;
}

.canvas-summary .muted {
  color: var(--text-muted);
  font-size: 12px;
}

.transcript {
  max-height: 150px;
  overflow-y: auto;
  margin: 0;
  padding: 8px 10px;
  font-family: inherit;
  font-size: 12px;
  line-height: 1.45;
  white-space: pre-wrap;
  color: #bbb;
  background: #111;
  border-radius: 6px;
}

.disclosure {
  border: none;
  background: none;
  padding: 0;
  font-size: 12px;
  color: var(--text-muted);
}

.sources ul {
  margin: 6px 0 0;
  padding-left: 16px;
  max-height: 160px;
  overflow-y: auto;
}

.sources li {
  font-size: 12px;
  margin-bottom: 4px;
}

.sources a {
  color: var(--accent);
}

.result {
  display: flex;
  flex-direction: column;
  gap: 6px;
  border-top: 1px solid var(--border);
  padding-top: 12px;
}

.result-title {
  font-weight: 600;
}

.result-sub {
  font-size: 12px;
  color: var(--text-muted);
}

.wide {
  width: 100%;
  margin-top: 4px;
}

.csv {
  font-size: 12px;
  color: var(--text-muted);
  text-align: center;
}
</style>
