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
  const r = props.config.aspectRatio
  // For 9:16 reels, keep a 4:5 composition centered vertically, then pad top/bottom.
  // This preserves portrait positioning while fitting reel output dimensions.
  if (r === '9:16') {
    const { width, height } = dims.value
    const targetPortraitHeight = width * (5 / 4) // 4:5 frame height for this width
    const extraVerticalPad = Math.max(0, Math.round((height - targetPortraitHeight) / 2))
    return {
      top: Math.round(280 * s) + extraVerticalPad,
      right: Math.round(220 * s),
      bottom: Math.round(220 * s) + extraVerticalPad,
      left: Math.round(180 * s),
    }
  }
  return isPortrait.value
    ? { top: Math.round(280 * s), right: Math.round(220 * s), bottom: Math.round(220 * s), left: Math.round(180 * s) }
    : { top: Math.round(200 * s), right: Math.round(230 * s), bottom: Math.round(180 * s), left: Math.round(180 * s) }
})
const AXIS_LERP_SPEED = 0.03 // per frame, controls smoothness
const LEGEND_LERP_SPEED = 0.2
const CONFETTI_DURATION_MS = 1800
const CONFETTI_COUNT = 90
const ICON_SIZE_SCALE = {
  small: 0.75,
  medium: 1,
  large: 1.35,
} as const

// Smoothly animated axis state
let displayYMin = 0
let displayYMax = 1
let displayXMin = 0
let displayXMax = 1
let axisInitialized = false

// Image cache: maps data URL -> HTMLImageElement
const imageCache = new Map<string, HTMLImageElement>()
const legendDisplayY = new Map<string, number>()
const WATERMARK_SRC = '/bg-transparent.png'
const DESIGNER_LOGO_SRC = '/logo.png'
type ConfettiPiece = {
  x: number
  y: number
  vx: number
  vy: number
  size: number
  rot: number
  rotSpeed: number
  color: string
}
let confettiPieces: ConfettiPiece[] = []
let confettiActive = false
let confettiStartMs = 0
let confettiRafId: number | null = null

function titleFontFamily(): string {
  return props.config.chartFont === 'royal'
    ? '"Canela", "Noe Display", Didot, "Bodoni 72", "Bodoni MT", "Times New Roman", serif'
    : 'Inter, sans-serif'
}

function titleNormalFont(px: number): string {
  return `${px}px ${titleFontFamily()}`
}

function titleBoldFont(px: number): string {
  // Royal style uses a lighter high-contrast serif look.
  if (props.config.chartFont === 'royal') {
    return `900 ${px}px ${titleFontFamily()}`
  }
  return `900 ${px}px ${titleFontFamily()}`
}

function titleFontScale(): number {
  return props.config.chartFont === 'royal' ? 1.36 : 1
}

function subtitleFontScale(): number {
  return props.config.chartFont === 'royal' ? 1.05 : 1
}

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

function formatValue(v: number, sf = props.config.numberSuffixes): string {
  const symbol = props.config.currency ?? ''
  const isPrefix = (props.config.currencyPosition ?? 'prefix') === 'prefix'
  const abs = Math.abs(v)
  let raw: string
  if (abs >= 1e9) raw = (v / 1e9).toFixed(1) + sf.billions
  else if (abs >= 1e6) raw = (v / 1e6).toFixed(1) + sf.millions
  else if (abs >= 1e3) raw = (v / 1e3).toFixed(1) + sf.thousands
  else if (abs < 0.01 && abs > 0) raw = v.toExponential(1)
  else if (Number.isInteger(v)) raw = v.toString()
  else raw = v.toFixed(1)
  return isPrefix ? symbol + raw : raw + symbol
}

function formatDDMMYY(ms: number): string {
  const d = new Date(ms)
  const dd = String(d.getUTCDate()).padStart(2, '0')
  const mm = String(d.getUTCMonth() + 1).padStart(2, '0')
  const yy = String(d.getUTCFullYear() % 100).padStart(2, '0')
  return `${dd}/${mm}/${yy}`
}

function formatMMYY(ms: number): string {
  const d = new Date(ms)
  const mm = String(d.getUTCMonth() + 1).padStart(2, '0')
  const yy = String(d.getUTCFullYear() % 100).padStart(2, '0')
  return `${mm}/${yy}`
}

function getVisibleData(series: Series[], progress: number): { points: { time: number; label: string; value: number }[]; maxTimeVisible: number }[] {
  if (series.length === 0) return []

  const allTimes = series.flatMap(s => s.data.map(d => d.time))
  const minTime = Math.min(...allTimes)
  const maxTime = Math.max(...allTimes)
  const currentTime = lerp(minTime, maxTime, progress)

  return series.map(s => {
    const sorted = [...s.data].sort((a, b) => a.time - b.time)
    const visible: { time: number; label: string; value: number }[] = []

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
        visible.push({ time: currentTime, label: prev.label, value: lerp(prev.value, next.value, t) })
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

function getCurrentXLabel(series: Series[], currentTime: number): string {
  if (props.config.xAxisMode === 'date-ddmmyy') {
    return formatDDMMYY(currentTime)
  }
  if (props.config.xAxisMode === 'date-mmyy') {
    return formatMMYY(currentTime)
  }
  if (props.config.xAxisMode === 'year') {
    return Math.floor(currentTime).toString()
  }
  if (series.length === 0) return ''
  const base = series[0]?.data ?? []
  if (base.length === 0) return ''
  const idx = Math.max(0, Math.min(base.length - 1, Math.floor(currentTime + 1e-6)))
  return base[idx]?.label ?? ''
}

function getSeriesKey(ser: Series, idx: number): string {
  return `${idx}:${ser.name}`
}

function startConfetti(width: number, height: number) {
  const colors = ['#ffd84d', '#4f8ff7', '#f74f4f', '#4ff78f', '#c74ff7', '#ffffff']
  confettiPieces = Array.from({ length: CONFETTI_COUNT }, (_, i) => {
    const seed = i + 1
    const randA = (Math.sin(seed * 12.9898) * 43758.5453) % 1
    const randB = (Math.sin(seed * 78.233) * 12345.6789) % 1
    const randC = (Math.sin(seed * 45.164) * 99999.9999) % 1
    const r1 = randA < 0 ? randA + 1 : randA
    const r2 = randB < 0 ? randB + 1 : randB
    const r3 = randC < 0 ? randC + 1 : randC
    return {
      x: r1 * width,
      y: -r2 * height * 0.7 - 20,
      vx: (r2 - 0.5) * 2.2,
      vy: 1.6 + r1 * 2.4,
      size: 4 + r3 * 8,
      rot: r1 * Math.PI,
      rotSpeed: (r3 - 0.5) * 0.3,
      color: colors[i % colors.length],
    }
  })
  confettiActive = true
  confettiStartMs = performance.now()
}

function runConfettiLoop() {
  if (confettiRafId !== null) cancelAnimationFrame(confettiRafId)
  const step = () => {
    draw()
    if (confettiActive) {
      confettiRafId = requestAnimationFrame(step)
    } else {
      confettiRafId = null
      draw() // ensure final still frame
    }
  }
  confettiRafId = requestAnimationFrame(step)
}

function getRankedLegendItems(series: Series[], visibleData: { points: { time: number; label: string; value: number }[] }[]) {
  return series.map((ser, idx) => {
    const vd = visibleData[idx]
    const currentValue = vd.points.length > 0
      ? vd.points[vd.points.length - 1].value
      : Number.NEGATIVE_INFINITY
    return { ser, idx, currentValue }
  }).sort((a, b) => b.currentValue - a.currentValue)
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
  getImage(WATERMARK_SRC)
  getImage(DESIGNER_LOGO_SRC)

  const visibleData = getVisibleData(series, props.progress)
  const sc = textScale.value
  const iconScale = ICON_SIZE_SCALE[props.config.iconSize ?? 'medium']
  const PAD = PADDING.value
  const chartLeft = PAD.left
  const chartRight = width - PAD.right
  const chartTop = PAD.top
  const chartBottom = height - PAD.bottom
  const chartW = chartRight - chartLeft
  const chartH = chartBottom - chartTop

  // Background watermark at chart center.
  const watermark = getImage(WATERMARK_SRC)
  if (watermark && watermark.complete && watermark.naturalWidth > 0) {
    const maxW = chartW * 0.52
    const maxH = chartH * 0.52
    const scale = Math.min(maxW / watermark.naturalWidth, maxH / watermark.naturalHeight)
    const wmW = watermark.naturalWidth * scale
    const wmH = watermark.naturalHeight * scale
    const wmX = chartLeft + (chartW - wmW) / 2
    const wmY = chartTop + (chartH - wmH) / 2
    ctx.save()
    ctx.globalAlpha = 0.09
    ctx.drawImage(watermark, wmX, wmY, wmW, wmH)
    ctx.restore()
  }

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
  const yMinRaw = props.config.allowNegative
    ? Math.min(...allVisibleValues)
    : Math.min(...allVisibleValues, 0)
  const yMaxRaw = Math.max(...allVisibleValues)

  // Add extra headroom above the max so the chart has generous breathing room
  const yRange = yMaxRaw - yMinRaw || Math.abs(yMaxRaw) * 0.1 || 1
  const headroom = yRange * 0.5 // 50% of visible range as top padding
  const targetYScale = niceScale(yMinRaw, yMaxRaw + headroom, 8)

  // X axis: use raw current time as max so the line head is always pinned to the right edge
  // The min is fixed to the global start. No rounding/nice-scaling on xMax.
  displayXMin = globalMinTime
  displayXMax = currentTime

  // Y axis: smooth lerp for nice transitions when scale jumps.
  // The mapY clamp below prevents lines from escaping the chart area
  // while the axis catches up.
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
    const raw = chartBottom - ((value - displayYMin) / (displayYMax - displayYMin)) * chartH
    // Clamp to chart area so lines/endpoints never exceed the container
    // when data grows faster than the animated Y-axis can follow
    return Math.max(chartTop, Math.min(chartBottom, raw))
  }

  // Compute how many ticks actually fit given font size and chart dimensions
  const tickFontPx = Math.round(28 * sc)
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

  // Zero line when chart spans negative values
  if (props.config.allowNegative && displayYMin < 0 && displayYMax > 0) {
    const zeroY = mapY(0)
    if (zeroY >= chartTop && zeroY <= chartBottom) {
      ctx.strokeStyle = '#444'
      ctx.lineWidth = 1.5
      ctx.setLineDash([6, 4])
      ctx.beginPath()
      ctx.moveTo(chartLeft, zeroY)
      ctx.lineTo(chartRight, zeroY)
      ctx.stroke()
      ctx.setLineDash([])
    }
  }

  // X axis — single label at the right edge, aligned with line heads
  ctx.fillStyle = '#aaa'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'top'
  const currentLabel = getCurrentXLabel(series, currentTime)
  ctx.fillText(currentLabel, chartRight, chartBottom + Math.round(16 * sc))

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
    const iconSize = Math.round(44 * sc * iconScale)
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
  const titleScale = titleFontScale()
  const subtitleScale = subtitleFontScale()
  const titleSize = Math.round(42 * sc * titleScale)
  const subtitleSize = Math.round(24 * sc * subtitleScale)
  const axisLabelSize = Math.round(28 * sc)
  const subtitleTopGap = Math.round(44 * sc)
  const subtitleY = chartTop - subtitleSize - subtitleTopGap
  const titleY = subtitleY - titleSize - Math.round(8 * sc)

  ctx.fillStyle = '#e0e0e0'
  ctx.font = titleBoldFont(titleSize)
  ctx.textAlign = 'center'
  ctx.textBaseline = 'top'
  ctx.fillText(title, width / 2, titleY)

  if (props.config.subtitle) {
    ctx.fillStyle = '#888'
    ctx.font = titleNormalFont(subtitleSize)
    ctx.textAlign = 'center'
    ctx.textBaseline = 'top'
    ctx.fillText(props.config.subtitle, width / 2, subtitleY)
  }

  // X label
  ctx.fillStyle = '#e0e0e0'
  ctx.font = `${axisLabelSize}px Inter, sans-serif`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'top'
  ctx.fillText(props.config.xLabel, width / 2, chartBottom + Math.round(34 * sc))

  // Y label
  ctx.save()
  ctx.translate(Math.round(56 * sc), height / 2)
  ctx.rotate(-Math.PI / 2)
  ctx.fillStyle = '#e0e0e0'
  ctx.font = `${axisLabelSize}px Inter, sans-serif`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'top'
  ctx.fillText(props.config.yLabel, 0, 0)
  ctx.restore()

  // Legend (dynamic ranking by current visible value with smooth swapping animation)
  const legendFont = Math.round(28 * sc)
  const legendSwatch = Math.round(22 * sc * iconScale)
  const legendGap = Math.round(38 * sc)
  const legendX = chartLeft + Math.round(16 * sc)
  const legendTop = chartTop + Math.round(20 * sc)
  ctx.font = `${legendFont}px Inter, sans-serif`
  ctx.textAlign = 'left'
  ctx.textBaseline = 'middle'

  const rankedLegendItems = getRankedLegendItems(series, visibleData)

  const showEndRanking = props.config.showEndRanking && props.progress >= 1
  const activeLegendKeys = new Set(rankedLegendItems.map(item => getSeriesKey(item.ser, item.idx)))
  for (const key of legendDisplayY.keys()) {
    if (!activeLegendKeys.has(key)) legendDisplayY.delete(key)
  }

  for (let rank = 0; rank < rankedLegendItems.length; rank++) {
    const { ser, idx } = rankedLegendItems[rank]
    const key = getSeriesKey(ser, idx)

    if (showEndRanking) {
      const y = legendTop + rank * legendGap
      legendDisplayY.set(key, y)
      continue
    }

    const targetY = legendTop + rank * legendGap
    const currentY = legendDisplayY.get(key) ?? targetY
    const nextY = lerp(currentY, targetY, LEGEND_LERP_SPEED)
    legendDisplayY.set(key, nextY)

    const img = ser.image ? getImage(ser.image) : null
    if (img && img.complete && img.naturalWidth > 0) {
      ctx.drawImage(img, legendX, nextY - legendSwatch / 2, legendSwatch, legendSwatch)
    } else {
      ctx.fillStyle = ser.color
      ctx.fillRect(legendX, nextY - legendSwatch / 2, legendSwatch, legendSwatch)
    }
    ctx.fillStyle = '#ccc'
    ctx.fillText(ser.name, legendX + legendSwatch + Math.round(8 * sc), nextY)
  }

  if (showEndRanking) {
    const nowMs = performance.now()
    if (confettiActive) {
      const elapsed = nowMs - confettiStartMs
      const t = Math.min(elapsed / CONFETTI_DURATION_MS, 1)
      const gravity = 0.09
      for (const p of confettiPieces) {
        p.vy += gravity
        p.x += p.vx
        p.y += p.vy
        p.rot += p.rotSpeed
        if (p.y > height + 24) {
          p.y = -20
          p.vy = 1.2
        }
      }

      for (const p of confettiPieces) {
        ctx.save()
        ctx.translate(p.x, p.y)
        ctx.rotate(p.rot)
        ctx.fillStyle = p.color
        ctx.globalAlpha = 1 - t * 0.4
        ctx.fillRect(-p.size / 2, -p.size / 2, p.size, p.size * 0.7)
        ctx.restore()
      }
      ctx.globalAlpha = 1

      if (t >= 1) confettiActive = false
    }

    // Dim the full recorded frame and show centered final ranking list.
    ctx.fillStyle = 'rgba(0, 0, 0, 0.65)'
    ctx.fillRect(0, 0, width, height)

    const overlayTitleSize = Math.round(34 * sc)
    const overlayItemSize = Math.round(30 * sc)
    const cardHeight = Math.round(62 * sc)
    const cardGap = Math.round(10 * sc)
    const cardRadius = Math.round(14 * sc)
    const cardWidth = Math.min(Math.round(chartW * 0.82), Math.round(820 * sc))
    const totalCardsHeight = rankedLegendItems.length * cardHeight + (rankedLegendItems.length - 1) * cardGap
    const listTop = chartTop + chartH / 2 - totalCardsHeight / 2 + Math.round(6 * sc)
    const cardLeft = chartLeft + (chartW - cardWidth) / 2

    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillStyle = '#f5f5f5'
    ctx.font = `bold ${overlayTitleSize}px Inter, sans-serif`
    ctx.fillText('Final Ranking', chartLeft + chartW / 2, listTop - Math.round(52 * sc))

    ctx.font = `bold ${overlayItemSize}px Inter, sans-serif`
    for (let rank = 0; rank < rankedLegendItems.length; rank++) {
      const { ser } = rankedLegendItems[rank]
      const cardTop = listTop + rank * (cardHeight + cardGap)
      const y = cardTop + cardHeight / 2
      const rowText = `#${rank + 1} ${ser.name}`
      const iconSize = Math.round(34 * sc * iconScale)
      const iconGap = Math.round(14 * sc)
      const iconX = cardLeft + Math.round(18 * sc)
      const textX = iconX + iconSize + iconGap

      // Kahoot-like colored ranking card (uniform size).
      ctx.save()
      ctx.fillStyle = ser.color
      ctx.globalAlpha = 0.88
      ctx.beginPath()
      ctx.moveTo(cardLeft + cardRadius, cardTop)
      ctx.lineTo(cardLeft + cardWidth - cardRadius, cardTop)
      ctx.quadraticCurveTo(cardLeft + cardWidth, cardTop, cardLeft + cardWidth, cardTop + cardRadius)
      ctx.lineTo(cardLeft + cardWidth, cardTop + cardHeight - cardRadius)
      ctx.quadraticCurveTo(cardLeft + cardWidth, cardTop + cardHeight, cardLeft + cardWidth - cardRadius, cardTop + cardHeight)
      ctx.lineTo(cardLeft + cardRadius, cardTop + cardHeight)
      ctx.quadraticCurveTo(cardLeft, cardTop + cardHeight, cardLeft, cardTop + cardHeight - cardRadius)
      ctx.lineTo(cardLeft, cardTop + cardRadius)
      ctx.quadraticCurveTo(cardLeft, cardTop, cardLeft + cardRadius, cardTop)
      ctx.closePath()
      ctx.fill()
      ctx.restore()

      const img = ser.image ? getImage(ser.image) : null
      if (img && img.complete && img.naturalWidth > 0) {
        ctx.drawImage(img, iconX, y - iconSize / 2, iconSize, iconSize)
      } else {
        ctx.fillStyle = ser.color
        ctx.fillRect(iconX, y - iconSize / 2, iconSize, iconSize)
      }

      ctx.fillStyle = '#f5f5f5'
      ctx.textAlign = 'left'
      ctx.fillText(rowText, textX, y)
    }

    const footerY = chartBottom + Math.round(76 * sc)
    const logo = getImage(DESIGNER_LOGO_SRC)
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillStyle = '#d8d8d8'
    ctx.font = `${Math.round(20 * sc)}px Inter, sans-serif`
    ctx.fillText('Designed By', width / 2, footerY)
    if (logo && logo.complete && logo.naturalWidth > 0) {
      const logoMaxW = Math.round(140 * sc)
      const logoScale = logoMaxW / logo.naturalWidth
      const logoW = logoMaxW
      const logoH = logo.naturalHeight * logoScale
      const logoX = width / 2 - logoW / 2
      const logoY = footerY + Math.round(18 * sc)
      ctx.drawImage(logo, logoX, logoY, logoW, logoH)
    }
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
  if (props.progress >= 1 && props.config.showEndRanking && !confettiActive) {
    const { width, height } = dims.value
    startConfetti(width, height)
    runConfettiLoop()
  }
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
  legendDisplayY.clear()
  confettiActive = false
  confettiPieces = []
  if (confettiRafId !== null) {
    cancelAnimationFrame(confettiRafId)
    confettiRafId = null
  }
  draw()
}, { deep: true })

onMounted(() => {
  draw()
})

onUnmounted(() => {
  if (rafId !== null) cancelAnimationFrame(rafId)
  if (confettiRafId !== null) cancelAnimationFrame(confettiRafId)
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
