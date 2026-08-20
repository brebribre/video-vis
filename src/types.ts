export interface DataPoint {
  time: number
  value: number
}

export interface Series {
  name: string
  color: string
  data: DataPoint[]
  image?: string // data URL or object URL for endpoint icon
}

export type AspectRatio = '9:16' | '4:5'

export interface NumberSuffixes {
  thousands: string  // e.g. "K" or "Rb"
  millions: string   // e.g. "M" or "Jt"
  billions: string   // e.g. "B" or "M" (miliar)
}

export const NUMBER_SUFFIX_PRESETS: Record<string, NumberSuffixes> = {
  'English':    { thousands: 'K',  millions: 'M',  billions: 'B'  },
  'Indonesian': { thousands: 'Rb', millions: 'Jt', billions: 'M'  },
  'Japanese':   { thousands: 'K',  millions: '百万', billions: '十億' },
  'Custom':     { thousands: 'K',  millions: 'M',  billions: 'B'  },
}

export interface ChartConfig {
  series: Series[]
  aspectRatio: AspectRatio
  title: string
  subtitle: string
  xLabel: string
  yLabel: string
  animationDuration: number // seconds
  textSize: number // multiplier, 1 = default
  numberSuffixes: NumberSuffixes
}

export const ASPECT_DIMENSIONS: Record<AspectRatio, { width: number; height: number }> = {
  '9:16': { width: 1080, height: 1920 },
  '4:5':  { width: 1080, height: 1350 },
}

// Which platform's UI chrome to mock on top of the preview. Preview-only —
// the overlay lives in the DOM, so canvas.captureStream() never sees it.
export type PlatformPreview = 'none' | 'tiktok' | 'instagram'

// Instagram shows different chrome for Reels (9:16) vs a feed post (4:5),
// so the concrete overlay is derived from platform + aspect ratio.
export type OverlayVariant = 'tiktok' | 'ig-reels' | 'ig-feed'

export interface SafeZone {
  top: number
  right: number
  bottom: number
  left: number
}

// Fractions of the frame covered by platform UI.
// TikTok: Creative Center safe zones for 1080x1920 — 130 top, 483 bottom, 44 left, 140 right.
// Reels: Meta's text-safe guidance — ~250 top, ~420 bottom, plus the action rail on the right.
// Feed: chrome sits outside the 4:5 media, so nothing is covered.
export const SAFE_ZONES: Record<OverlayVariant, SafeZone> = {
  'tiktok':   { top: 0.068, right: 0.130, bottom: 0.252, left: 0.041 },
  'ig-reels': { top: 0.130, right: 0.167, bottom: 0.219, left: 0.037 },
  'ig-feed':  { top: 0,     right: 0,     bottom: 0,     left: 0     },
}

// Single source of truth for both the mock chrome and the chart's own layout,
// so the drawn frame can never disagree with the overlay about the safe area.
export function overlayVariantFor(
  platform: PlatformPreview,
  aspectRatio: AspectRatio,
): OverlayVariant | null {
  if (platform === 'tiktok') return 'tiktok'
  if (platform === 'instagram') return aspectRatio === '4:5' ? 'ig-feed' : 'ig-reels'
  return null
}

export const DEFAULT_COLORS = [
  '#4f8ff7',
  '#f74f4f',
  '#4ff78f',
  '#f7c94f',
  '#c74ff7',
  '#4ff7f7',
  '#f77b4f',
  '#7b4ff7',
]
