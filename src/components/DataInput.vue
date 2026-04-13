<script setup lang="ts">
import { ref, computed } from 'vue'
import type { Series, AspectRatio } from '../types'
import { DEFAULT_COLORS } from '../types'

const emit = defineEmits<{
  apply: [config: {
    series: Series[]
    aspectRatio: AspectRatio
    title: string
    subtitle: string
    xLabel: string
    yLabel: string
    animationDuration: number
  }]
}>()

const title = ref('Revenue Comparison')
const subtitle = ref('Annual revenue in millions USD')
const xLabel = ref('Year')
const yLabel = ref('Revenue ($)')
const aspectRatio = ref<AspectRatio>('16:9')
const animationDuration = ref(5)

interface SeriesInput {
  name: string
  color: string
  csv: string // "time,value" per line
  image: string // data URL
}

const seriesInputs = ref<SeriesInput[]>([
  {
    name: 'OpenAI',
    color: DEFAULT_COLORS[0],
    image: '',
    csv: `2020,100
2021,200
2022,500
2023,1600
2024,3700
2025,12500`,
  },
  {
    name: 'Anthropic',
    color: DEFAULT_COLORS[1],
    image: '',
    csv: `2021,10
2022,50
2023,200
2024,850
2025,2400`,
  },
])

function addSeries() {
  const idx = seriesInputs.value.length
  seriesInputs.value.push({
    name: `Series ${idx + 1}`,
    color: DEFAULT_COLORS[idx % DEFAULT_COLORS.length],
    image: '',
    csv: '',
  })
}

function onImageUpload(index: number, event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    seriesInputs.value[index].image = reader.result as string
  }
  reader.readAsDataURL(file)
}

function clearImage(index: number) {
  seriesInputs.value[index].image = ''
}

function removeSeries(i: number) {
  seriesInputs.value.splice(i, 1)
}

function parseSeries(input: SeriesInput): Series {
  const data = input.csv
    .split('\n')
    .map(line => line.trim())
    .filter(line => line.length > 0)
    .map(line => {
      const parts = line.split(/[,\t]+/)
      if (parts.length >= 3) {
        // year, month, value — convert to fractional year
        const year = parseFloat(parts[0])
        const month = parseFloat(parts[1])
        const value = parseFloat(parts[2])
        return { time: year + (month - 1) / 12, value }
      }
      return { time: parseFloat(parts[0]), value: parseFloat(parts[1]) }
    })
    .filter(d => !isNaN(d.time) && !isNaN(d.value))
    .sort((a, b) => a.time - b.time)

  return { name: input.name, color: input.color, data, image: input.image || undefined }
}

const parsedSeries = computed(() => seriesInputs.value.map(parseSeries))

function apply() {
  emit('apply', {
    series: parsedSeries.value,
    aspectRatio: aspectRatio.value,
    title: title.value,
    subtitle: subtitle.value,
    xLabel: xLabel.value,
    yLabel: yLabel.value,
    animationDuration: animationDuration.value,
  })
}

// Auto-apply on mount
apply()
</script>

<template>
  <div class="data-input">
    <h2>Chart Settings</h2>

    <div class="field">
      <label>Title</label>
      <input v-model="title" placeholder="Chart title" />
    </div>

    <div class="field">
      <label>Subtitle</label>
      <input v-model="subtitle" placeholder="Subtitle (optional)" />
    </div>

    <div class="row">
      <div class="field">
        <label>X Axis Label</label>
        <input v-model="xLabel" placeholder="X axis" />
      </div>
      <div class="field">
        <label>Y Axis Label</label>
        <input v-model="yLabel" placeholder="Y axis" />
      </div>
    </div>

    <div class="row">
      <div class="field">
        <label>Format</label>
        <select v-model="aspectRatio">
          <option value="16:9">Desktop (16:9)</option>
          <option value="1:1">Square (1:1)</option>
          <option value="4:5">Portrait (4:5)</option>
          <option value="9:16">Story / Reel (9:16)</option>
        </select>
      </div>
      <div class="field">
        <label>Duration (seconds)</label>
        <input type="number" v-model.number="animationDuration" min="1" max="30" />
      </div>
    </div>

    <h3>Data Series</h3>

    <div v-for="(s, i) in seriesInputs" :key="i" class="series-block">
      <div class="series-header">
        <input v-model="s.name" placeholder="Series name" class="series-name" />
        <input type="color" v-model="s.color" class="color-picker" />
        <button v-if="seriesInputs.length > 1" class="remove-btn" @click="removeSeries(i)">Remove</button>
      </div>
      <div class="image-row">
        <label class="image-upload-btn">
          {{ s.image ? 'Change Icon' : 'Add Icon' }}
          <input type="file" accept="image/*" @change="onImageUpload(i, $event)" hidden />
        </label>
        <img v-if="s.image" :src="s.image" class="image-preview" />
        <button v-if="s.image" class="remove-btn" @click="clearImage(i)">x</button>
      </div>
      <textarea
        v-model="s.csv"
        placeholder="year,value or year,month,value (one per line)&#10;2020,100&#10;2021,1,200"
        rows="6"
      />
    </div>

    <div class="actions">
      <button @click="addSeries">+ Add Series</button>
      <button class="primary" @click="apply">Apply & Preview</button>
    </div>
  </div>
</template>

<style scoped>
.data-input {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 20px;
  background: #141414;
  border-radius: 8px;
  border: 1px solid #2a2a2a;
  width: 380px;
  max-height: calc(100vh - 40px);
  overflow-y: auto;
}

h2 {
  font-size: 18px;
  font-weight: 600;
  margin: 0;
}

h3 {
  font-size: 15px;
  font-weight: 600;
  margin: 8px 0 0 0;
  color: #aaa;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
}

.field label {
  font-size: 12px;
  color: #888;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.row {
  display: flex;
  gap: 12px;
}

.series-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  background: #1a1a1a;
  border-radius: 6px;
  border: 1px solid #2a2a2a;
}

.series-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.series-name {
  flex: 1;
}

.color-picker {
  width: 36px;
  height: 36px;
  padding: 2px;
  cursor: pointer;
  border-radius: 4px;
}

.remove-btn {
  font-size: 12px;
  padding: 4px 10px;
  color: #f74f4f;
  border-color: #f74f4f33;
}

.image-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.image-upload-btn {
  font-size: 12px;
  padding: 4px 10px;
  border: 1px solid #2a2a2a;
  border-radius: 6px;
  background: #1a1a1a;
  color: #e0e0e0;
  cursor: pointer;
  transition: background 0.15s;
}

.image-upload-btn:hover {
  background: #2a2a2a;
}

.image-preview {
  width: 28px;
  height: 28px;
  border-radius: 4px;
  object-fit: contain;
  background: #222;
}

textarea {
  resize: vertical;
  font-family: 'Fira Code', 'Cascadia Code', monospace;
  font-size: 13px;
  line-height: 1.5;
}

.actions {
  display: flex;
  gap: 8px;
}

.actions button {
  flex: 1;
}
</style>
