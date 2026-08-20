<script setup lang="ts">
import { ref, computed, onUnmounted } from 'vue'
import type { ChartConfig, PlatformPreview } from './types'
import { SAFE_ZONES, overlayVariantFor } from './types'
import AnimatedChart from './components/AnimatedChart.vue'
import DataInput from './components/DataInput.vue'
import PlatformOverlay from './components/PlatformOverlay.vue'

const config = ref<ChartConfig>({
  series: [],
  aspectRatio: '9:16',
  xAxisMode: 'text',
  title: '',
  subtitle: '',
  xLabel: '',
  yLabel: '',
  currency: '$',
  currencyPosition: 'prefix',
  allowNegative: false,
  iconSize: 'medium',
  chartFont: 'modern',
  showEndRanking: true,
  animationDuration: 5,
  textSize: 1,
  numberSuffixes: { thousands: 'K', millions: 'M', billions: 'B' },
  captions: [],
})

const progress = ref(0)
const playing = ref(false)
const playbackSpeed = ref(1)
type ExportFormat = 'webm' | 'mp4' | 'hevc'
const exportFormat = ref<ExportFormat>('webm')

// Platform chrome mock — DOM-only, so it never reaches the recorded canvas stream
const platformPreview = ref<PlatformPreview>('none')
const showSafeZones = ref(true)
const mockUsername = ref('@yourhandle')
const mockCaption = ref('The chart nobody expected 📈 #data #ai #charts')

// Picking a platform also composes the chart for it: the drawn frame is inset to
// that platform's safe zone, so the exported video clears the real UI chrome.
const activeVariant = computed(() =>
  overlayVariantFor(platformPreview.value, config.value.aspectRatio),
)
const activeSafeZone = computed(() =>
  activeVariant.value ? SAFE_ZONES[activeVariant.value] : null,
)

// Feed chrome renders above and below the frame, so the stage needs room for it
const feedChrome = computed(() => activeVariant.value === 'ig-feed')

let startTime = 0
let startProgress = 0
let animFrameId: number | null = null
let recordingStopTimeoutId: number | null = null

// Recording state
const recording = ref(false)
const recordedChunks: Blob[] = []
let mediaRecorder: MediaRecorder | null = null
let recordingBlobType = 'video/webm'
let recordingFileExtension = 'webm'

function onApply(c: ChartConfig) {
  config.value = c
  progress.value = 0
  playing.value = false
}

function play() {
  progress.value = 0
  playing.value = true
  startTime = performance.now()
  startProgress = 0
  tick()
}

function tick() {
  const elapsed = (performance.now() - startTime) / 1000
  const duration = config.value.animationDuration
  progress.value = Math.min(startProgress + (elapsed * playbackSpeed.value) / duration, 1)

  if (progress.value >= 1) {
    playing.value = false
    if (recording.value) {
      // Keep recording a little longer so end-state animation is captured.
      if (recordingStopTimeoutId !== null) {
        clearTimeout(recordingStopTimeoutId)
      }
      recordingStopTimeoutId = window.setTimeout(() => {
        stopRecording()
        recordingStopTimeoutId = null
      }, 3000)
    }
    return
  }

  animFrameId = requestAnimationFrame(tick)
}

function onSpeedChange() {
  if (playing.value) {
    startProgress = progress.value
    startTime = performance.now()
  }
}

function stop() {
  playing.value = false
  if (animFrameId !== null) cancelAnimationFrame(animFrameId)
  if (recordingStopTimeoutId !== null) {
    clearTimeout(recordingStopTimeoutId)
    recordingStopTimeoutId = null
  }
  if (recording.value) stopRecording()
}

function reset() {
  stop()
  progress.value = 0
}

function onFrame(canvas: HTMLCanvasElement) {
  // Store ref for recording setup
  canvasEl.value = canvas
}

const canvasEl = ref<HTMLCanvasElement | null>(null)

function pickSupportedMimeType(candidates: string[]): string | null {
  for (const mimeType of candidates) {
    if (typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(mimeType)) {
      return mimeType
    }
  }
  return null
}

function getRecordingConfig() {
  if (exportFormat.value === 'mp4') {
    const mp4Candidates = ['video/mp4;codecs=hvc1', 'video/mp4;codecs=hev1', 'video/mp4']
    const supportedMp4 = pickSupportedMimeType(mp4Candidates)
    if (supportedMp4) {
      return { mimeType: supportedMp4, blobType: 'video/mp4', extension: 'mp4' }
    }
  }

  if (exportFormat.value === 'hevc') {
    const hevcCandidates = ['video/mp4;codecs=hvc1', 'video/mp4;codecs=hev1', 'video/mp4']
    const supportedHevc = pickSupportedMimeType(hevcCandidates)
    if (supportedHevc) {
      return { mimeType: supportedHevc, blobType: 'video/mp4', extension: 'mov' }
    }
  }

  const webmCandidates = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm']
  const supportedWebm = pickSupportedMimeType(webmCandidates)
  if (supportedWebm) {
    return { mimeType: supportedWebm, blobType: 'video/webm', extension: 'webm' }
  }

  return { mimeType: '', blobType: 'video/webm', extension: 'webm' }
}

function startRecording() {
  const canvas = canvasEl.value
  if (!canvas) return

  const stream = canvas.captureStream(60)
  const recordingConfig = getRecordingConfig()
  recordingBlobType = recordingConfig.blobType
  recordingFileExtension = recordingConfig.extension

  try {
    mediaRecorder = recordingConfig.mimeType
      ? new MediaRecorder(stream, { mimeType: recordingConfig.mimeType })
      : new MediaRecorder(stream)
  } catch {
    // Fallback
    mediaRecorder = new MediaRecorder(stream)
    recordingBlobType = 'video/webm'
    recordingFileExtension = 'webm'
  }

  recordedChunks.length = 0

  mediaRecorder.ondataavailable = (e) => {
    if (e.data.size > 0) recordedChunks.push(e.data)
  }

  mediaRecorder.onstop = () => {
    const blob = new Blob(recordedChunks, { type: recordingBlobType })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `chart-${Date.now()}.${recordingFileExtension}`
    a.click()
    URL.revokeObjectURL(url)
    recording.value = false
  }

  mediaRecorder.start()
  recording.value = true

  // Start playing
  play()
}

function stopRecording() {
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop()
  }
  recording.value = false
}

onUnmounted(() => {
  if (animFrameId !== null) cancelAnimationFrame(animFrameId)
  if (recordingStopTimeoutId !== null) clearTimeout(recordingStopTimeoutId)
})
</script>

<template>
  <div class="app-layout">
    <DataInput @apply="onApply" />

    <div class="chart-area">
      <div class="stage" :class="{ 'has-feed-chrome': feedChrome }">
        <AnimatedChart
          :config="config"
          :playing="playing"
          :progress="progress"
          :safe-zone="activeSafeZone"
          @frame="onFrame"
        />
        <PlatformOverlay
          :platform="platformPreview"
          :aspect-ratio="config.aspectRatio"
          :show-safe-zones="showSafeZones"
          :username="mockUsername"
          :caption="mockCaption"
        />
      </div>

      <div class="controls">
        <div class="preview-bar">
          <div class="seg">
            <button
              v-for="p in (['none', 'tiktok', 'instagram'] as PlatformPreview[])"
              :key="p"
              :class="{ active: platformPreview === p }"
              @click="platformPreview = p"
            >
              {{ p === 'none' ? 'No overlay' : p === 'tiktok' ? 'TikTok' : 'Instagram' }}
            </button>
          </div>

          <template v-if="platformPreview !== 'none'">
            <label class="check">
              <input type="checkbox" v-model="showSafeZones" />
              Safe zones
            </label>
            <input v-model="mockUsername" class="mock-input handle-input" placeholder="@handle" />
            <input v-model="mockCaption" class="mock-input" placeholder="Mock caption" />
          </template>

          <span v-if="platformPreview === 'tiktok' && config.aspectRatio === '4:5'" class="warn">
            TikTok plays 9:16 — a 4:5 upload gets padded.
          </span>
          <span v-else class="hint">Overlay is preview only — it is not recorded.</span>
        </div>

        <div class="progress-bar">
          <div class="progress-fill" :style="{ width: (progress * 100) + '%' }" />
        </div>

        <div class="buttons">
          <button @click="play" :disabled="playing">Play</button>
          <button @click="stop" :disabled="!playing">Stop</button>
          <button @click="reset">Reset</button>
          <div class="speed-control">
            <label>Speed</label>
            <input
              type="range"
              min="0.25"
              max="4"
              step="0.25"
              v-model.number="playbackSpeed"
              @input="onSpeedChange"
            />
            <span class="speed-label">{{ playbackSpeed }}x</span>
          </div>
          <div class="export-format-control">
            <label>Export</label>
            <select v-model="exportFormat">
              <option value="webm">WebM</option>
              <option value="mp4">MP4</option>
              <option value="hevc">HEVC (.mov)</option>
            </select>
          </div>
          <button class="primary record-btn" @click="startRecording" :disabled="recording">
            <span v-if="recording" class="rec-dot" />
            {{ recording ? 'Recording…' : 'Export Video' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.app-layout {
  display: flex;
  gap: 24px;
  padding: 20px;
  min-height: 100vh;
  align-items: flex-start;
}

.chart-area {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 16px;
  flex: 1;
}

.stage {
  position: relative;
  display: inline-block;
  line-height: 0;
}

/* Instagram feed chrome sits outside the media — reserve room so it isn't clipped.
   The overlay sizes itself in cqw, so the reserved space has to scale with the
   frame width: 4:5 means width = height x 0.8, capped by the available width. */
.stage.has-feed-chrome {
  --frame-w: min(100%, calc(var(--frame-max-h) * 0.8));
  margin-top: calc(var(--frame-w) * 0.11);
  margin-bottom: calc(var(--frame-w) * 0.22);
}

.preview-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.seg {
  display: flex;
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
}

.seg button {
  border: none;
  border-radius: 0;
  padding: 7px 14px;
  font-size: 13px;
  background: transparent;
}

.seg button + button {
  border-left: 1px solid var(--border);
}

.seg button.active {
  background: var(--accent);
  color: #fff;
  font-weight: 600;
}

.check {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-muted);
  cursor: pointer;
  white-space: nowrap;
}

.check input {
  accent-color: var(--accent);
}

.mock-input {
  padding: 6px 10px;
  font-size: 13px;
  flex: 1;
  min-width: 160px;
}

.handle-input {
  flex: 0 0 130px;
  min-width: 0;
}

.hint,
.warn {
  font-size: 12px;
  color: #555;
}

.warn {
  color: #f7c94f;
}

.controls {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
}

.progress-bar {
  height: 6px;
  background: #1a1a1a;
  border-radius: 3px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: #4f8ff7;
  border-radius: 3px;
  transition: width 0.05s linear;
}

.buttons {
  display: flex;
  gap: 8px;
}

.buttons button {
  padding: 10px 20px;
}

.buttons button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.speed-control {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 8px;
}

.speed-control label {
  font-size: 13px;
  color: #888;
  white-space: nowrap;
}

.speed-control input[type="range"] {
  width: 100px;
  accent-color: #4f8ff7;
}

.speed-label {
  font-size: 13px;
  color: #e0e0e0;
  min-width: 32px;
  font-variant-numeric: tabular-nums;
}

.export-format-control {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 8px;
}

.export-format-control label {
  font-size: 13px;
  color: #888;
  white-space: nowrap;
}

.export-format-control select {
  min-width: 120px;
}

.record-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}

.rec-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #ff4444;
  animation: blink 1s ease-in-out infinite;
  flex-shrink: 0;
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.2; }
}
</style>
