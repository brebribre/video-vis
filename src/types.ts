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

export type AspectRatio = '1:1' | '16:9' | '4:5' | '9:16'

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
  '16:9': { width: 1280, height: 720 },
  '1:1':  { width: 1080, height: 1080 },
  '4:5':  { width: 1080, height: 1350 },
  '9:16': { width: 1080, height: 1920 },
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
