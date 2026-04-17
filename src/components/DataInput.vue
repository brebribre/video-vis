<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import type { Series, AspectRatio, NumberSuffixes, XAxisMode, IconSize, ChartFont, CurrencyPosition, Caption } from '../types'
import { DEFAULT_COLORS, NUMBER_SUFFIX_PRESETS } from '../types'

const emit = defineEmits<{
  apply: [config: {
    series: Series[]
    aspectRatio: AspectRatio
    xAxisMode: XAxisMode
    title: string
    subtitle: string
    xLabel: string
    yLabel: string
    currency: string
    currencyPosition: CurrencyPosition
    allowNegative: boolean
    iconSize: IconSize
    chartFont: ChartFont
    showEndRanking: boolean
    animationDuration: number
    textSize: number
    numberSuffixes: NumberSuffixes
    captions: Caption[]
  }]
}>()

const title = ref('Revenue Comparison')
const subtitle = ref('Annual revenue in millions USD')
const xLabel = ref('Year')
const yLabel = ref('Revenue ($)')
const xAxisMode = ref<XAxisMode>('text')
const currency = ref('$')
const currencyPosition = ref<CurrencyPosition>('prefix')
const allowNegative = ref(false)
const iconSize = ref<IconSize>('medium')
const chartFont = ref<ChartFont>('modern')
const showEndRanking = ref(true)
const aspectRatio = ref<AspectRatio>('16:9')
const animationDuration = ref(5)
const textSize = ref(1)

const suffixPreset = ref('English')
const suffixes = ref<NumberSuffixes>({ ...NUMBER_SUFFIX_PRESETS['English'] })

const captions = ref<Caption[]>([])

function addCaption() {
  captions.value.push({ text: '', appearAt: 0, duration: 2 })
}

function removeCaption(index: number) {
  captions.value.splice(index, 1)
}

watch(suffixPreset, (preset) => {
  if (preset !== 'Custom') {
    suffixes.value = { ...NUMBER_SUFFIX_PRESETS[preset] }
  }
})

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

function parseDDMMYYToMs(input: string): number | null {
  const m = input.trim().match(/^(\d{1,2})\/(\d{1,2})\/(\d{2}|\d{4})$/)
  if (!m) return null
  const day = Number.parseInt(m[1], 10)
  const month = Number.parseInt(m[2], 10)
  const rawYear = Number.parseInt(m[3], 10)
  const year = m[3].length === 2 ? 2000 + rawYear : rawYear
  if (month < 1 || month > 12 || day < 1 || day > 31) return null
  const date = new Date(Date.UTC(year, month - 1, day))
  // Reject invalid rolled dates like 31/02/25
  if (
    date.getUTCFullYear() !== year ||
    date.getUTCMonth() !== month - 1 ||
    date.getUTCDate() !== day
  ) {
    return null
  }
  return date.getTime()
}

function parseMMYYToMs(input: string): number | null {
  const m = input.trim().match(/^(\d{1,2})\/(\d{2}|\d{4})$/)
  if (!m) return null
  const month = Number.parseInt(m[1], 10)
  const rawYear = Number.parseInt(m[2], 10)
  const year = m[2].length === 2 ? 2000 + rawYear : rawYear
  if (month < 1 || month > 12) return null
  return Date.UTC(year, month - 1, 1)
}

function parseDatetimeHHMMDDMMYYToMs(input: string): number | null {
  // Accepts: "09:30 14/04/26" → HH:MM DD/MM/YY
  const m = input.trim().match(/^(\d{1,2}):(\d{2})\s+(\d{1,2})\/(\d{1,2})\/(\d{2}|\d{4})$/)
  if (!m) return null
  const hours = Number.parseInt(m[1], 10)
  const minutes = Number.parseInt(m[2], 10)
  const day = Number.parseInt(m[3], 10)
  const month = Number.parseInt(m[4], 10)
  const rawYear = Number.parseInt(m[5], 10)
  const year = m[5].length === 2 ? 2000 + rawYear : rawYear
  if (hours > 23 || minutes > 59 || day < 1 || day > 31 || month < 1 || month > 12) return null
  return Date.UTC(year, month - 1, day, hours, minutes)
}

function parseYear(input: string): number | null {
  const trimmed = input.trim()
  if (!/^\d{4}$/.test(trimmed)) return null
  const year = Number.parseInt(trimmed, 10)
  if (year < 0 || year > 9999) return null
  return year
}

function parseSeries(input: SeriesInput): Series {
  const data = input.csv
    .split('\n')
    .map(line => line.trim())
    .filter(line => line.length > 0)
    .map((line, index) => {
      const parts = line.split(/[,\t]+/)
      if (parts.length < 2) return null

      const label = parts.slice(0, -1).join(',').trim()
      const value = parseFloat(parts[parts.length - 1])
      if (!label || Number.isNaN(value)) return null

      if (xAxisMode.value === 'datetime-hhmm-ddmmyy') {
        const parsedMs = parseDatetimeHHMMDDMMYYToMs(label)
        if (parsedMs === null) return null
        return { time: parsedMs, label, value }
      }

      if (xAxisMode.value === 'date-ddmmyy') {
        const parsedMs = parseDDMMYYToMs(label)
        if (parsedMs === null) return null
        return { time: parsedMs, label, value }
      }

      if (xAxisMode.value === 'date-mmyy') {
        const parsedMs = parseMMYYToMs(label)
        if (parsedMs === null) return null
        return { time: parsedMs, label, value }
      }

      if (xAxisMode.value === 'year') {
        const parsedYear = parseYear(label)
        if (parsedYear === null) return null
        return { time: parsedYear, label, value }
      }

      return { time: index, label, value }
    })
    .filter((d): d is { time: number; label: string; value: number } => d !== null)
    .sort((a, b) => a.time - b.time)

  return { name: input.name, color: input.color, data, image: input.image || undefined }
}

function formatLabelFromTime(time: number): string {
  if (xAxisMode.value === 'datetime-hhmm-ddmmyy') {
    const d = new Date(time)
    const hh = String(d.getUTCHours()).padStart(2, '0')
    const min = String(d.getUTCMinutes()).padStart(2, '0')
    const dd = String(d.getUTCDate()).padStart(2, '0')
    const mm = String(d.getUTCMonth() + 1).padStart(2, '0')
    const yy = String(d.getUTCFullYear() % 100).padStart(2, '0')
    return `${hh}:${min} ${dd}/${mm}/${yy}`
  }
  if (xAxisMode.value === 'date-ddmmyy') {
    const d = new Date(time)
    const dd = String(d.getUTCDate()).padStart(2, '0')
    const mm = String(d.getUTCMonth() + 1).padStart(2, '0')
    const yy = String(d.getUTCFullYear() % 100).padStart(2, '0')
    return `${dd}/${mm}/${yy}`
  }
  if (xAxisMode.value === 'date-mmyy') {
    const d = new Date(time)
    const mm = String(d.getUTCMonth() + 1).padStart(2, '0')
    const yy = String(d.getUTCFullYear() % 100).padStart(2, '0')
    return `${mm}/${yy}`
  }
  if (xAxisMode.value === 'year') {
    return Math.floor(time).toString()
  }
  return String(time)
}

function fillLeadingGapsWithZero(seriesList: Series[]): Series[] {
  const allTimes = Array.from(new Set(seriesList.flatMap(s => s.data.map(d => d.time)))).sort((a, b) => a - b)
  if (allTimes.length === 0) return seriesList

  const labelByTime = new Map<number, string>()
  for (const s of seriesList) {
    for (const d of s.data) {
      if (!labelByTime.has(d.time)) labelByTime.set(d.time, d.label)
    }
  }

  return seriesList.map(series => {
    if (series.data.length === 0) return series
    const firstTime = series.data[0].time
    const leadingTimes = allTimes.filter(t => t < firstTime)
    if (leadingTimes.length === 0) return series

    const leadingZeros = leadingTimes.map(t => ({
      time: t,
      label: labelByTime.get(t) ?? formatLabelFromTime(t),
      value: 0,
    }))

    return {
      ...series,
      data: [...leadingZeros, ...series.data],
    }
  })
}

const parsedSeries = computed(() => fillLeadingGapsWithZero(seriesInputs.value.map(parseSeries)))
const csvPlaceholder = computed(() =>
  xAxisMode.value === 'date-ddmmyy'
    ? 'date,value (DD/MM/YY)\n01/02/25,100\n06/02/25,200'
    : xAxisMode.value === 'date-mmyy'
      ? 'month,value (MM/YY)\n02/25,100\n07/25,200'
    : xAxisMode.value === 'year'
      ? 'year,value\n2020,100\n2021,200'
      : xAxisMode.value === 'datetime-hhmm-ddmmyy'
        ? 'datetime,value (HH:MM DD/MM/YY)\n09:30 14/04/26,100\n10:00 14/04/26,200'
        : 'x,value (one per line)\n2020,100\nQ1 2025,200',
)

function apply() {
  emit('apply', {
    series: parsedSeries.value,
    aspectRatio: aspectRatio.value,
    xAxisMode: xAxisMode.value,
    title: title.value,
    subtitle: subtitle.value,
    xLabel: xLabel.value,
    yLabel: yLabel.value,
    currency: currency.value,
    currencyPosition: currencyPosition.value,
    allowNegative: allowNegative.value,
    iconSize: iconSize.value,
    chartFont: chartFont.value,
    showEndRanking: showEndRanking.value,
    animationDuration: animationDuration.value,
    textSize: textSize.value,
    numberSuffixes: { ...suffixes.value },
    captions: captions.value.filter(c => c.text.trim()),
  })
}

watch(
  [
    title,
    subtitle,
    xLabel,
    yLabel,
    xAxisMode,
    currency,
    currencyPosition,
    allowNegative,
    iconSize,
    chartFont,
    showEndRanking,
    aspectRatio,
    animationDuration,
    textSize,
    suffixPreset,
    suffixes,
    captions,
  ],
  () => {
    apply()
  },
  { deep: true },
)

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
        <label>X Axis Type</label>
        <select v-model="xAxisMode">
          <option value="text">Text (any string)</option>
          <option value="year">Year only</option>
          <option value="date-ddmmyy">Date (DD/MM/YY)</option>
          <option value="date-mmyy">Date (MM/YY)</option>
          <option value="datetime-hhmm-ddmmyy">Datetime (HH:MM DD/MM/YY)</option>
        </select>
      </div>
    </div>
    <div class="row">
      <div class="field">
        <label>Y Axis Label</label>
        <input v-model="yLabel" placeholder="Y axis" />
      </div>
      <div class="field">
        <label>Currency Symbol</label>
        <input v-model="currency" placeholder="$" />
      </div>
      <div class="field">
        <label>Symbol Position</label>
        <select v-model="currencyPosition">
          <option value="prefix">Prefix ($100)</option>
          <option value="suffix">Suffix (100$)</option>
        </select>
      </div>
      <div class="field">
        <label>Icon Size</label>
        <select v-model="iconSize">
          <option value="small">Small</option>
          <option value="medium">Medium</option>
          <option value="large">Large</option>
        </select>
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
      <div class="field">
        <label>Chart Font</label>
        <select v-model="chartFont">
          <option value="modern">Modern (current)</option>
          <option value="royal">Royal Premium (Times style)</option>
        </select>
      </div>
    </div>

    <div class="field">
      <label>Text Size &mdash; {{ textSize.toFixed(1) }}×</label>
      <input
        type="range"
        v-model.number="textSize"
        min="0.5"
        max="2"
        step="0.1"
        class="text-size-slider"
      />
    </div>

    <div class="field">
      <label>Number Format</label>
      <select v-model="suffixPreset">
        <option v-for="(_, name) in NUMBER_SUFFIX_PRESETS" :key="name" :value="name">{{ name }}</option>
      </select>
    </div>

    <div class="field checkbox-field">
      <label>
        <input type="checkbox" v-model="showEndRanking" />
        Show end ranking animation
      </label>
    </div>

    <div class="field checkbox-field">
      <label>
        <input type="checkbox" v-model="allowNegative" />
        Allow negative values
      </label>
    </div>

    <div v-if="suffixPreset === 'Custom'" class="row">
      <div class="field">
        <label>Thousands</label>
        <input v-model="suffixes.thousands" placeholder="K" />
      </div>
      <div class="field">
        <label>Millions</label>
        <input v-model="suffixes.millions" placeholder="M" />
      </div>
      <div class="field">
        <label>Billions</label>
        <input v-model="suffixes.billions" placeholder="B" />
      </div>
    </div>
    <div v-else class="suffix-preview">
      1,000 = 1{{ suffixes.thousands }} &nbsp;·&nbsp;
      1,000,000 = 1{{ suffixes.millions }} &nbsp;·&nbsp;
      1,000,000,000 = 1{{ suffixes.billions }}
    </div>

    <h3>Captions</h3>
    <div v-for="(cap, ci) in captions" :key="ci" class="caption-block">
      <div class="caption-header">
        <input v-model="cap.text" placeholder="Caption text" class="caption-text" />
        <button class="remove-btn" @click="removeCaption(ci)">Remove</button>
      </div>
      <div class="row">
        <div class="field">
          <label>Appear at (s)</label>
          <input type="number" v-model.number="cap.appearAt" min="0" step="0.5" />
        </div>
        <div class="field">
          <label>Duration (s)</label>
          <input type="number" v-model.number="cap.duration" min="0.5" step="0.5" />
        </div>
      </div>
    </div>
    <button class="add-btn" @click="addCaption">+ Add Caption</button>

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
        :placeholder="csvPlaceholder"
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

.checkbox-field label {
  display: flex;
  align-items: center;
  gap: 8px;
  text-transform: none;
  letter-spacing: 0;
  color: #cfcfcf;
}

.row {
  display: flex;
  flex-direction: column;
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

.text-size-slider {
  width: 100%;
  accent-color: #4f8ff7;
}

.suffix-preview {
  font-size: 11px;
  color: #555;
  background: #111;
  border-radius: 4px;
  padding: 6px 10px;
  font-family: 'Fira Code', monospace;
}

.caption-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  background: #1a1a1a;
  border-radius: 6px;
  border: 1px solid #2a2a2a;
  margin-bottom: 8px;
}

.caption-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.caption-text {
  flex: 1;
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
