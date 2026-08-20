<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'
import type { ChartConfig, Series, SafeZone } from '../types'
import { ASPECT_DIMENSIONS } from '../types'

const props = defineProps<{
  config: ChartConfig
  playing: boolean
  progress: number // 0..1
  // When set, every drawn element is kept inside this inset so it can't end up
  // under the platform's UI chrome. Null lays out against the full frame.
  safeZone?: SafeZone | null
}>()

const emit = defineEmits<{
  frame: [canvas: HTMLCanvasElement]
}>()

const canvasRef = ref<HTMLCanvasElement | null>(null)

const dims = computed(() => ASPECT_DIMENSIONS[props.config.aspectRatio])

// Scale factor relative to a 1280×720 baseline, multiplied by user-controlled size
const textScale = computed(() => {
  const { width, height } = dims.value
  return (Math.sqrt(width * height) / 960) * (props.config.textSize ?? 1)
})

// The safe zone as pixels of the current frame. Everything the chart draws is
// laid out inside this box, so nothing lands under the platform's UI chrome.
const safeInset = computed(() => {
  const { width, height } = dims.value
  const z = props.safeZone
  if (!z) return { top: 0, right: 0, bottom: 0, left: 0 }
  return {
    top: Math.round(z.top * height),
    right: Math.round(z.right * width),
    bottom: Math.round(z.bottom * height),
    left: Math.round(z.left * width),
  }
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

function clamp(v: number, lo: number, hi: number): number {
  return v < lo ? lo : v > hi ? hi : v
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

function formatValue(v: number, sf = props.config.numberSuffixes): string {
  const abs = Math.abs(v)
  if (abs >= 1e9) return (v / 1e9).toFixed(1) + sf.billions
  if (abs >= 1e6) return (v / 1e6).toFixed(1) + sf.millions
  if (abs >= 1e3) return (v / 1e3).toFixed(1) + sf.thousands
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

  // ---- Layout ----------------------------------------------------------
  // Everything is anchored to the content box (the frame minus the platform's
  // safe-zone inset) rather than to the frame itself.
  const safe = safeInset.value
  const contentTop = safe.top
  const contentBottom = height - safe.bottom
  const contentLeft = safe.left
  const contentRight = width - safe.right

  const titleSize = Math.round(40 * sc)
  const subtitleSize = Math.round(27 * sc)
  const axisLabelSize = Math.round(28 * sc)
  const tickFontPx = Math.round(28 * sc)
  const headFontPx = Math.round(30 * sc)

  // Title block sits at the top of the content box
  const titleY = contentTop + Math.round(30 * sc)
  const subtitleY = titleY + titleSize + Math.round(8 * sc)
  const titleBlockBottom = props.config.subtitle ? subtitleY + subtitleSize : titleY + titleSize

  // Measure the chart furniture so the plot box is sized to what's actually
  // drawn. Measurements use the global extremes, not the currently visible
  // ones, so the plot box stays put instead of jittering during playback.
  const allValues = series.flatMap(s => s.data.map(d => d.value))
  const widestValue = Math.max(...allValues.map(Math.abs), 0)

  ctx.font = `${tickFontPx}px Inter, sans-serif`
  const yTickW = ctx.measureText(formatValue(widestValue)).width

  ctx.font = `bold ${headFontPx}px Inter, sans-serif`
  const headLabelW = ctx.measureText(formatValue(widestValue)).width

  const chartTop = titleBlockBottom + Math.round(46 * sc)
  const chartBottom = contentBottom - (axisLabelSize + tickFontPx + Math.round(56 * sc))
  const chartLeft = contentLeft + Math.round(yTickW) + axisLabelSize + Math.round(40 * sc)
  const chartRight = contentRight - Math.round(20 * sc)
  const chartW = chartRight - chartLeft
  const chartH = chartBottom - chartTop
  if (chartW <= 0 || chartH <= 0) return

  // ---- Data region -----------------------------------------------------
  // The series is mapped into a region inset from the plot box, so the endpoint
  // marker and its value label — which hang off the head of each line — stay
  // inside the plot box instead of spilling past its right edge.
  const dotR = Math.round(7 * sc)
  const iconSize = Math.round(44 * sc)
  const markerR = Math.round(iconSize / 2)
  // Enough for the widest label the animation can reach, so the region is fixed
  const headRoom = markerR + Math.round(12 * sc) + Math.ceil(headLabelW)
  // Half a line of label text, so a head at the extreme doesn't clip vertically
  const vPad = Math.max(markerR, Math.round(headFontPx * 0.62))

  const dataLeft = chartLeft + markerR
  const dataRight = chartRight - headRoom
  const dataTop = chartTop + vPad
  const dataBottom = chartBottom - vPad
  if (dataRight <= dataLeft || dataBottom <= dataTop) return

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

  // Y axis: smooth lerp for nice transitions when scale jumps.
  // The eased range must still enclose the data every frame — otherwise a fast
  // rise outruns the axis and points map outside the plot box entirely.
  if (!axisInitialized) {
    displayYMin = targetYScale.min
    displayYMax = targetYScale.max
    axisInitialized = true
  } else {
    displayYMax = Math.max(lerp(displayYMax, targetYScale.max, AXIS_LERP_SPEED), yMaxRaw)
    displayYMin = Math.min(lerp(displayYMin, targetYScale.min, AXIS_LERP_SPEED), yMinRaw)
  }

  const dataW = dataRight - dataLeft
  const dataH = dataBottom - dataTop

  function mapX(time: number): number {
    if (displayXMax === displayXMin) return dataLeft + dataW / 2
    return dataLeft + ((time - displayXMin) / (displayXMax - displayXMin)) * dataW
  }

  function mapY(value: number): number {
    if (displayYMax === displayYMin) return dataTop + dataH / 2
    return dataBottom - ((value - displayYMin) / (displayYMax - displayYMin)) * dataH
  }

  // Compute how many ticks actually fit given font size and chart dimensions
  const maxYTicks = Math.max(2, Math.floor(chartH / (tickFontPx * 2.5)))

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

  // X axis — single label tracking the line heads, clamped to the plot box
  ctx.fillStyle = '#aaa'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'top'
  const xTickText = formatTime(currentTime, yearMode)
  const xTickHalf = ctx.measureText(xTickText).width / 2
  const xTickCx = Math.min(
    Math.max(dataRight, chartLeft + xTickHalf),
    chartRight - xTickHalf,
  )
  ctx.fillText(xTickText, xTickCx, chartBottom + Math.round(16 * sc))

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

  // Draw lines with Catmull-Rom spline + glow effect
  function buildLinePath(c: CanvasRenderingContext2D, pts: {x: number, y: number}[]) {
    c.beginPath()
    c.moveTo(pts[0].x, pts[0].y)
    if (pts.length === 2) {
      c.lineTo(pts[1].x, pts[1].y)
    } else if (pts.length > 2) {
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
        c.bezierCurveTo(cp1x, cp1y, cp2x, cp2y, p2.x, p2.y)
      }
    }
  }

  for (let si = 0; si < series.length; si++) {
    const ser = series[si]
    const vd = visibleData[si]
    if (vd.points.length < 1) continue

    const pts = vd.points.map(p => ({ x: mapX(p.time), y: mapY(p.value) }))

    ctx.lineJoin = 'round'
    ctx.lineCap = 'round'

    // Glow pass — wide, blurred, semi-transparent
    ctx.strokeStyle = ser.color
    ctx.lineWidth = Math.round(14 * sc)
    ctx.shadowColor = ser.color
    ctx.shadowBlur = Math.round(24 * sc)
    ctx.globalAlpha = 0.35
    buildLinePath(ctx, pts)
    ctx.stroke()

    // Core pass — sharp, fully opaque
    ctx.globalAlpha = 1
    ctx.shadowBlur = 0
    ctx.lineWidth = Math.round(3.5 * sc)
    buildLinePath(ctx, pts)
    ctx.stroke()
  }

  ctx.shadowBlur = 0
  ctx.globalAlpha = 1

  // Endpoints stay inside the plot box, so they are drawn within the same clip
  for (let si = 0; si < series.length; si++) {
    const ser = series[si]
    const vd = visibleData[si]
    if (vd.points.length < 1) continue

    // Pinned to the data region: the marker and its label must stay in the box
    // even if the eased axis is momentarily behind the data.
    const last = vd.points[vd.points.length - 1]
    const px = clamp(mapX(last.time), dataLeft, dataRight)
    const py = clamp(mapY(last.value), dataTop, dataBottom)

    // Draw image or dot at endpoint
    const img = ser.image ? getImage(ser.image) : null
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

    // Value label at end — headRoom above reserves exactly this much space
    const labelOffset = (img && img.complete && img.naturalWidth > 0) ? markerR + Math.round(8 * sc) : dotR + Math.round(8 * sc)
    ctx.fillStyle = ser.color
    ctx.font = `bold ${headFontPx}px Inter, sans-serif`
    ctx.textAlign = 'left'
    ctx.textBaseline = 'middle'
    ctx.fillText(formatValue(last.value), px + labelOffset, py)
  }

  ctx.restore() // un-clip the plot box

  // Title + subtitle (anchored to the top of the content box)
  const contentCenterX = (contentLeft + contentRight) / 2

  ctx.fillStyle = '#e0e0e0'
  ctx.font = `bold ${titleSize}px Inter, sans-serif`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'top'
  ctx.fillText(title, contentCenterX, titleY)

  if (props.config.subtitle) {
    ctx.fillStyle = '#888'
    ctx.font = `${subtitleSize}px Inter, sans-serif`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'top'
    ctx.fillText(props.config.subtitle, contentCenterX, subtitleY)
  }

  // X label — pinned to the bottom of the content box
  ctx.fillStyle = '#888'
  ctx.font = `${axisLabelSize}px Inter, sans-serif`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'bottom'
  ctx.fillText(props.config.xLabel, contentCenterX, contentBottom - Math.round(20 * sc))

  // Y label — centred on the plot, just inside the left edge of the content box
  ctx.save()
  ctx.translate(contentLeft + Math.round(16 * sc), (chartTop + chartBottom) / 2)
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

// Switching platform re-insets the layout, so the frame has to be repainted
watch(() => props.safeZone, () => draw())

onMounted(() => {
  draw()
})

onUnmounted(() => {
  if (rafId !== null) cancelAnimationFrame(rafId)
})
</script>

<template>
  <!-- The bitmap size is set imperatively in draw(). Binding :width/:height here
       too would re-patch the attributes after the watcher has already painted,
       resetting the bitmap and leaving the canvas blank on an aspect change. -->
  <canvas
    ref="canvasRef"
    :style="{
      maxWidth: '100%',
      maxHeight: 'var(--frame-max-h)',
      width: 'auto',
      height: 'auto',
      aspectRatio: dims.width + '/' + dims.height,
      borderRadius: '8px',
      border: '1px solid #2a2a2a'
          }"
  />
</template>
