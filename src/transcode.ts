import { FFmpeg } from '@ffmpeg/ffmpeg'
import { fetchFile, toBlobURL } from '@ffmpeg/util'

let ffmpeg: FFmpeg | null = null
let loading = false
let loadPromise: Promise<unknown> | null = null

const CORE_VERSION = '0.12.6'
const BASE = `https://unpkg.com/@ffmpeg/core@${CORE_VERSION}/dist/esm`

async function ensureLoaded(): Promise<FFmpeg> {
  if (ffmpeg?.loaded) return ffmpeg

  if (loading && loadPromise) {
    await loadPromise
    return ffmpeg!
  }

  loading = true
  ffmpeg = new FFmpeg()

  loadPromise = ffmpeg.load({
    coreURL: await toBlobURL(`${BASE}/ffmpeg-core.js`, 'text/javascript'),
    wasmURL: await toBlobURL(`${BASE}/ffmpeg-core.wasm`, 'application/wasm'),
  })

  await loadPromise
  loading = false
  return ffmpeg
}

export async function webmToMp4(
  webmBlob: Blob,
  onProgress?: (ratio: number) => void,
): Promise<Blob> {
  const ff = await ensureLoaded()

  ff.on('progress', ({ progress }) => {
    onProgress?.(Math.min(progress, 1))
  })

  await ff.writeFile('input.webm', await fetchFile(webmBlob))

  await ff.exec([
    '-i', 'input.webm',
    '-c:v', 'libx264',
    '-preset', 'fast',
    '-crf', '23',
    '-pix_fmt', 'yuv420p', // required for broad compatibility
    '-movflags', '+faststart', // optimise for streaming/web
    'output.mp4',
  ])

  const data = await ff.readFile('output.mp4')
  await ff.deleteFile('input.webm')
  await ff.deleteFile('output.mp4')

  return new Blob([data], { type: 'video/mp4' })
}
