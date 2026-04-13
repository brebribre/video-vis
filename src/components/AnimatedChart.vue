<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'
import type { ChartConfig, Series } from '../types'
import { ASPECT_DIMENSIONS } from '../types'

const props = defineProps<{
  config: ChartConfig
  playing: boolean
  progress: number // 0..1
}>()

const emit = defineEmits<{
  frame: [canvas: HTMLCanvasElement]
}>()

const canvasRef = ref<HTMLCanvasElement | null>(null)

const dims = computed(() => ASPECT_DIMENSIONS[props.config.aspectRatio])

const isPortrait = computed(() => {
  const r = props.config.aspectRatio
  return r === '4:5' || r === '9:16'
})

// Scale factor relative to a 1280×720 baseline, multiplied by user-controlled size
const textScale = computed(() => {
  const { width, height } = dims.value
  return (Math.sqrt(width * height) / 960) * (props.config.textSize ?? 1)
})

// Portrait formats get extra vertical padding for title/subtitle
const PADDING = computed(() => {
  const s = textScale.value
  return isPortrait.value
    ? { top: Math.round(280 * s), right: Math.round(260 * s), bottom: Math.round(220 * s), left: Math.round(230 * s) }
    : { top: Math.round(200 * s), right: Math.round(280 * s), bottom: Math.round(180 * s), left: Math.round(220 * s) }
})
const AXIS_LERP_SPEED = 0.03 // per frame, controls smoothness

// Smoothly animated axis state
let displayYMin = 0
let displayYMax = 1
let displayXMin = 0
let displayXMax = 1
let axisInitialized = false

// Image cache: maps data URL -> HTMLImageElement
const imageCache = new Map<string, HTMLImageElement>()

function getImage(src: string): HTMLImageElement | null {
  if (!src) return null
  const cached = imageCache.get(src)
  if (cached) return cached
  const img = new Image()
  img.src = src
  imageCache.set(src, img)
  return null // not loaded yet, will appear next frame
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t
}

function niceNum(range: number, round: boolean): number {
  const exp = Math.floor(Math.log10(range))
  const frac = range / Math.pow(10, exp)
  let nice: number
  if (round) {
    if (frac < 1.5) nice = 1
    else if (frac < 3) nice = 2
    else if (frac < 7) nice = 5
    else nice = 10
  } else {
    if (frac <= 1) nice = 1
    else if (frac <= 2) nice = 2
    else if (frac <= 5) nice = 5
    else nice = 10
  }
  return nice * Math.pow(10, exp)
}

function niceScale(min: number, max: number, maxTicks: number = 8): { min: number; max: number; step: number } {
  if (min === max) {
    if (min === 0) return { min: 0, max: 1, step: 0.2 }
    const offset = Math.abs(min) * 0.1
    min -= offset
    max += offset
  }
  const range = niceNum(max - min, false)
  const step = niceNum(range / (maxTicks - 1), true)
  const niceMin = Math.floor(min / step) * step
  const niceMax = Math.ceil(max / step) * step
  return { min: niceMin, max: niceMax, step }
}

function formatValue(v: number): string {
  const abs = Math.abs(v)
  if (abs >= 1e9) return (v / 1e9).toFixed(1) + 'B'
  if (abs >= 1e6) return (v / 1e6).toFixed(1) + 'M'
  if (abs >= 1e3) return (v / 1e3).toFixed(1) + 'K'
  if (abs < 0.01 && abs > 0) return v.toExponential(1)
  if (Number.isInteger(v)) return v.toString()
  return v.toFixed(1)
}

function isYearLike(series: Series[]): boolean {
  // Matches whole years (2020) and fractional years from year+month encoding (2020.083...)
  const allTimes = series.flatMap(s => s.data.map(d => d.time))
  return allTimes.every(t => t >= 1900 && t < 2200)
}

function formatTime(v: number, yearMode: boolean): string {
  if (yearMode) return Math.floor(v).toString()
  return formatValue(v)
}

function getVisibleData(series: Series[], progress: number): { points: { time: number; value: number }[]; maxTimeVisible: number }[] {
  if (series.length === 0) return []

  const allTimes = series.flatMap(s => s.data.map(d => d.time))
  const minTime = Math.min(...allTimes)
  const maxTime = Math.max(...allTimes)
  const currentTime = lerp(minTime, maxTime, progress)

  return series.map(s => {
    const sorted = [...s.data].sort((a, b) => a.time - b.time)
    const visible: { time: number; value: number }[] = []

    if (sorted.length === 0 || sorted[0].time > currentTime) {
      return { points: visible, maxTimeVisible: currentTime }
    }

    for (let i = 0; i < sorted.length; i++) {
      if (sorted[i].time <= currentTime) {
        visible.push(sorted[i])
      } else {
        const prev = sorted[i - 1]
        const next = sorted[i]
        const t = (currentTime - prev.time) / (next.time - prev.time)
        visible.push({ time: currentTime, value: lerp(prev.value, next.value, t) })
        break
      }
    }

    return { points: visible, maxTimeVisible: currentTime }
  })
}

// Compute nice tick positions for the smoothly animated display range
function getDisplayTicks(displayMin: number, displayMax: number, maxTicks: number): { step: number; ticks: number[] } {
  const range = displayMax - displayMin
  if (range <= 0) return { step: 1, ticks: [displayMin] }
  const step = niceNum(range / (maxTicks - 1), true)
  const ticks: number[] = []
  const start = Math.floor(displayMin / step) * step
  for (let v = start; v <= displayMax + step * 0.01; v += step) {
    ticks.push(v)
  }
  return { step, ticks }
}

function draw() {
  const canvas = canvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const { width, height } = dims.value
  canvas.width = width
  canvas.height = height

  ctx.fillStyle = '#0f0f0f'
  ctx.fillRect(0, 0, width, height)

  const { series, title } = props.config
  if (series.length === 0) return

  // Pre-load images
  for (const s of series) {
    if (s.image) getImage(s.image)
  }

  const visibleData = getVisibleData(series, props.progress)
  const sc = textScale.value
  const PAD = PADDING.value
  const chartLeft = PAD.left
  const chartRight = width - PAD.right
  const chartTop = PAD.top
  const chartBottom = height - PAD.bottom
  const chartW = chartRight - chartLeft
  const chartH = chartBottom - chartTop

  // Compute target axes ranges from visible data
  const allVisibleValues: number[] = []
  const allVisibleTimes: number[] = []
  for (const vd of visibleData) {
    for (const p of vd.points) {
      allVisibleValues.push(p.value)
      allVisibleTimes.push(p.time)
    }
  }

  if (allVisibleValues.length === 0) return

  const allTimes = series.flatMap(s => s.data.map(d => d.time))
  const globalMinTime = Math.min(...allTimes)

  const currentTime = Math.max(...allVisibleTimes)
  const yMinRaw = Math.min(...allVisibleValues, 0)
  const yMaxRaw = Math.max(...allVisibleValues)

  const yearMode = isYearLike(series)
  const targetYScale = niceScale(yMinRaw, yMaxRaw, 8)

  // X axis: use raw current time as max so the line head is always pinned to the right edge
  // The min is fixed to the global start. No rounding/nice-scaling on xMax.
  displayXMin = yearMode ? Math.floor(globalMinTime) : globalMinTime
  displayXMax = currentTime

  // Y axis: smooth lerp for nice transitions when scale jumps
  if (!axisInitialized) {
    displayYMin = targetYScale.min
    displayYMax = targetYScale.max
    axisInitialized = true
  } else {
    displayYMin = lerp(displayYMin, targetYScale.min, AXIS_LERP_SPEED)
    displayYMax = lerp(displayYMax, targetYScale.max, AXIS_LERP_SPEED)
  }

  function mapX(time: number): number {
    if (displayXMax === displayXMin) return chartLeft + chartW / 2
    return chartLeft + ((time - displayXMin) / (displayXMax - displayXMin)) * chartW
  }

  function mapY(value: number): number {
    if (displayYMax === displayYMin) return chartTop + chartH / 2
    return chartBottom - ((value - displayYMin) / (displayYMax - displayYMin)) * chartH
  }

  // Compute how many ticks actually fit given font size and chart dimensions
  const tickFontPx = Math.round(28 * sc)
  const maxYTicks = Math.max(2, Math.floor(chartH / (tickFontPx * 2.5)))
  // X labels are 4-char years; need ~5× the font width of clearance each
  const maxXTicks = Math.max(2, Math.floor(chartW / (tickFontPx * 5)))

  // Grid lines using display range
  ctx.strokeStyle = '#1e1e1e'
  ctx.lineWidth = 1

  // Y grid
  const yTicks = getDisplayTicks(displayYMin, displayYMax, maxYTicks)
  ctx.font = `${tickFontPx}px Inter, sans-serif`
  ctx.fillStyle = '#666'
  ctx.textAlign = 'right'
  ctx.textBaseline = 'middle'
  for (const v of yTicks.ticks) {
    const y = mapY(v)
    if (y < chartTop - 1 || y > chartBottom + 1) continue
    ctx.beginPath()
    ctx.moveTo(chartLeft, y)
    ctx.lineTo(chartRight, y)
    ctx.stroke()
    ctx.fillText(formatValue(v), chartLeft - Math.round(18 * sc), y)
  }

  // X axis — single label at the right edge, aligned with line heads
  ctx.fillStyle = '#aaa'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'top'
  ctx.fillText(formatTime(currentTime, yearMode), chartRight, chartBottom + Math.round(16 * sc))

  // Axes border
  ctx.strokeStyle = '#333'
  ctx.lineWidth = 1.5
  ctx.beginPath()
  ctx.moveTo(chartLeft, chartTop)
  ctx.lineTo(chartLeft, chartBottom)
  ctx.lineTo(chartRight, chartBottom)
  ctx.stroke()

  // Clip chart area for lines
  ctx.save()
  ctx.beginPath()
  ctx.rect(chartLeft, chartTop, chartW, chartH)
  ctx.clip()

  // Draw lines with Catmull-Rom spline for smooth curves
  for (let si = 0; si < series.length; si++) {
    const ser = series[si]
    const vd = visibleData[si]
    if (vd.points.length < 1) continue

    const pts = vd.points.map(p => ({ x: mapX(p.time), y: mapY(p.value) }))

    ctx.strokeStyle = ser.color
    ctx.lineWidth = Math.round(3.5 * sc)
    ctx.lineJoin = 'round'
    ctx.lineCap = 'round'
    ctx.beginPath()
    ctx.moveTo(pts[0].x, pts[0].y)

    if (pts.length === 1) {
      // single point — nothing more to draw
    } else if (pts.length === 2) {
      ctx.lineTo(pts[1].x, pts[1].y)
    } else {
      // Catmull-Rom → cubic bezier, tension 0.5
      const tension = 0.5
      for (let i = 0; i < pts.length - 1; i++) {
        const p0 = pts[Math.max(i - 1, 0)]
        const p1 = pts[i]
        const p2 = pts[i + 1]
        const p3 = pts[Math.min(i + 2, pts.length - 1)]
        const cp1x = p1.x + (p2.x - p0.x) * tension / 2
        const cp1y = p1.y + (p2.y - p0.y) * tension / 2
        const cp2x = p2.x - (p3.x - p1.x) * tension / 2
        const cp2y = p2.y - (p3.y - p1.y) * tension / 2
        ctx.bezierCurveTo(cp1x, cp1y, cp2x, cp2y, p2.x, p2.y)
      }
    }

    ctx.stroke()
  }

  ctx.restore() // un-clip

  // Draw endpoints (dots/images + labels) on top, outside clip
  for (let si = 0; si < series.length; si++) {
    const ser = series[si]
    const vd = visibleData[si]
    if (vd.points.length < 1) continue

    const last = vd.points[vd.points.length - 1]
    const px = mapX(last.time)
    const py = mapY(last.value)

    // Draw image or dot at endpoint
    const img = ser.image ? getImage(ser.image) : null
    const dotR = Math.round(7 * sc)
    const iconSize = Math.round(44 * sc)
    if (img && img.complete && img.naturalWidth > 0) {
      ctx.save()
      ctx.beginPath()
      ctx.arc(px, py, iconSize / 2, 0, Math.PI * 2)
      ctx.closePath()
      ctx.clip()
      ctx.drawImage(img, px - iconSize / 2, py - iconSize / 2, iconSize, iconSize)
      ctx.restore()
      ctx.strokeStyle = ser.color
      ctx.lineWidth = Math.round(2.5 * sc)
      ctx.beginPath()
      ctx.arc(px, py, iconSize / 2, 0, Math.PI * 2)
      ctx.stroke()
    } else {
      ctx.fillStyle = ser.color
      ctx.beginPath()
      ctx.arc(px, py, dotR, 0, Math.PI * 2)
      ctx.fill()
    }

    // Value label at end
    const labelOffset = (img && img.complete && img.naturalWidth > 0) ? iconSize / 2 + Math.round(8 * sc) : dotR + Math.round(8 * sc)
    ctx.fillStyle = ser.color
    ctx.font = `bold ${Math.round(30 * sc)}px Inter, sans-serif`
    ctx.textAlign = 'left'
    ctx.textBaseline = 'middle'
    ctx.fillText(formatValue(last.value), px + labelOffset, py)
  }

  // Title + subtitle
  const titleSize = Math.round(40 * sc)
  const subtitleSize = Math.round(27 * sc)
  const axisLabelSize = Math.round(28 * sc)
  const titleY = Math.round(36 * sc)
  const subtitleY = titleY + titleSize + Math.round(8 * sc)

  ctx.fillStyle = '#e0e0e0'
  ctx.font = `bold ${titleSize}px Inter, sans-serif`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'top'
  ctx.fillText(title, width / 2, titleY)

  if (props.config.subtitle) {
    ctx.fillStyle = '#888'
    ctx.font = `${subtitleSize}px Inter, sans-serif`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'top'
    ctx.fillText(props.config.subtitle, width / 2, subtitleY)
  }

  // X label
  ctx.fillStyle = '#888'
  ctx.font = `${axisLabelSize}px Inter, sans-serif`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'bottom'
  ctx.fillText(props.config.xLabel, width / 2, height - Math.round(52 * sc))

  // Y label
  ctx.save()
  ctx.translate(Math.round(56 * sc), height / 2)
  ctx.rotate(-Math.PI / 2)
  ctx.fillStyle = '#888'
  ctx.font = `${axisLabelSize}px Inter, sans-serif`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'top'
  ctx.fillText(props.config.yLabel, 0, 0)
  ctx.restore()

  // Legend
  const legendFont = Math.round(28 * sc)
  const legendSwatch = Math.round(22 * sc)
  const legendGap = Math.round(38 * sc)
  const legendX = chartLeft + Math.round(16 * sc)
  let legendY = chartTop + Math.round(20 * sc)
  ctx.font = `${legendFont}px Inter, sans-serif`
  ctx.textAlign = 'left'
  ctx.textBaseline = 'middle'
  for (const ser of series) {
    const img = ser.image ? getImage(ser.image) : null
    if (img && img.complete && img.naturalWidth > 0) {
      ctx.drawImage(img, legendX, legendY - legendSwatch / 2, legendSwatch, legendSwatch)
    } else {
      ctx.fillStyle = ser.color
      ctx.fillRect(legendX, legendY - legendSwatch / 2, legendSwatch, legendSwatch)
    }
    ctx.fillStyle = '#ccc'
    ctx.fillText(ser.name, legendX + legendSwatch + Math.round(8 * sc), legendY)
    legendY += legendGap
  }

  emit('frame', canvas)
}

let rafId: number | null = null

function animationLoop() {
  draw()
  if (props.playing) {
    rafId = requestAnimationFrame(animationLoop)
  }
}

watch(() => props.progress, () => {
  if (!props.playing) draw()
})

watch(() => props.playing, (val) => {
  if (val) {
    animationLoop()
  }
})

watch(() => props.config, () => {
  axisInitialized = false
  imageCache.clear()
  draw()
}, { deep: true })

onMounted(() => {
  draw()
})

onUnmounted(() => {
  if (rafId !== null) cancelAnimationFrame(rafId)
})
</script>

<template>
  <canvas
    ref="canvasRef"
    :width="dims.width"
    :height="dims.height"
    :style="{
      maxWidth: '100%',
      maxHeight: 'calc(100vh - 160px)',
      width: 'auto',
      height: 'auto',
      aspectRatio: dims.width + '/' + dims.height,
      borderRadius: '8px',
      border: '1px solid #2a2a2a'
          }"
  />
</template>
