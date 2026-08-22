import type { ChartConfig } from '../types'

/**
 * Client for POST /api/chart/generate (§5).
 *
 * EventSource is GET-only and the endpoint is a POST, so the SSE stream is read
 * from the fetch body and framed by hand. Events are yielded as they arrive —
 * a research run takes minutes, so buffering would show the user nothing until
 * the very end.
 */

export interface AgentRequest {
  topic: string
  language: string
  aspectRatio: '9:16' | '4:5'
  animationDuration: number
}

export interface SourceRef {
  url: string
  title: string
}

export interface CanvasState {
  rows: number
  series: string[]
  range: { start: string; end: string; granularity: string } | null
  missing: { series: string; missing_periods: string[]; has_no_data?: boolean }[]
  conflicts: number
  needs_attention: number
}

export type AgentEvent =
  | { type: 'run'; runId: string }
  | { type: 'stage'; name: string; status: string; stopReason?: string }
  | { type: 'token'; text: string }
  | { type: 'canvas'; canvas: CanvasState }
  | { type: 'sources'; sources: SourceRef[] }
  | { type: 'notice'; notice: Record<string, unknown> }
  | { type: 'config'; config: ChartConfig }
  | { type: 'error'; message: string; retryable: boolean }
  | { type: 'done' }

function toEvent(name: string, raw: string): AgentEvent | null {
  let data: any
  try {
    data = JSON.parse(raw)
  } catch {
    return null
  }
  switch (name) {
    case 'run':
      return { type: 'run', runId: data.run_id }
    case 'stage':
      return { type: 'stage', name: data.name, status: data.status, stopReason: data.stop_reason }
    case 'token':
      return { type: 'token', text: data.text ?? '' }
    case 'canvas':
      return { type: 'canvas', canvas: data as CanvasState }
    case 'sources':
      return { type: 'sources', sources: data.sources ?? [] }
    case 'notice':
      return { type: 'notice', notice: data }
    case 'config':
      return { type: 'config', config: data.config as ChartConfig }
    case 'error':
      return { type: 'error', message: data.message ?? 'unknown error', retryable: !!data.retryable }
    case 'done':
      return { type: 'done' }
    default:
      return null
  }
}

export async function* generateChart(
  request: AgentRequest,
  signal?: AbortSignal,
): AsyncGenerator<AgentEvent> {
  const response = await fetch('/api/chart/generate', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      topic: request.topic,
      language: request.language,
      aspect_ratio: request.aspectRatio,
      animation_duration: request.animationDuration,
    }),
    signal,
  })

  if (!response.ok || !response.body) {
    // A non-2xx never reaches the SSE framing, so surface it as an event rather
    // than throwing — the caller renders one error path, not two.
    let detail = `HTTP ${response.status}`
    try {
      const body = await response.json()
      if (body?.detail) detail = JSON.stringify(body.detail)
    } catch {
      /* body was not json */
    }
    yield { type: 'error', message: detail, retryable: response.status >= 500 }
    return
  }

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += value

      // SSE frames are separated by a blank line. A frame can arrive split
      // across chunks, so only complete ones are consumed.
      let split: number
      while ((split = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, split)
        buffer = buffer.slice(split + 2)

        let name = 'message'
        const dataLines: string[] = []
        for (const line of frame.split('\n')) {
          if (line.startsWith('event: ')) name = line.slice(7).trim()
          else if (line.startsWith('data: ')) dataLines.push(line.slice(6))
        }
        if (!dataLines.length) continue

        const event = toEvent(name, dataLines.join('\n'))
        if (event) yield event
      }
    }
  } finally {
    reader.cancel().catch(() => {})
  }
}

export function canvasCsvUrl(runId: string): string {
  return `/api/runs/${runId}/canvas.csv`
}
