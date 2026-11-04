import { readFile, unlink } from 'node:fs/promises'
import { isValidRecordingPath } from './voice-transcriber.js'

const PREPARATION_TIMEOUT_MS = 10 * 60_000

export function implausibleDshTranscript(text, seconds) {
  const compact = text.replace(/[^\p{L}\p{N}_]+/gu, '')
  if (compact.length > Math.max(48, Math.ceil(seconds * 20))) return true
  return /(.{4,40}?)\1{2,}/u.test(compact)
}

function waitUntilReady(preparation, signal) {
  return new Promise((resolve, reject) => {
    let off = () => {}
    const finish = (error) => {
      clearTimeout(timer)
      off()
      signal.removeEventListener('abort', cancelled)
      if (error) reject(error)
      else resolve()
    }
    const cancelled = () => finish(signal.reason || new Error('语音识别已停止'))
    const check = () => {
      const state = preparation.snapshot()
      if (state.phase === 'ready' || state.phase === 'standby') finish()
      else if (state.phase === 'failed' || state.phase === 'cancelled') {
        finish(new Error(state.message || 'DSH 语音模型准备失败'))
      }
    }
    const timer = setTimeout(() => finish(new Error('DSH 语音模型准备超时')), PREPARATION_TIMEOUT_MS)
    off = preparation.subscribe(check)
    signal.addEventListener('abort', cancelled, { once: true })
    if (signal.aborted) cancelled()
    else check()
  })
}

export class DshSpeechTranscriber {
  constructor(getService) {
    this.getService = getService
    this.pending = new Set()
    this.loading = undefined
    this.warmAbort = undefined
  }

  #selected() {
    const service = this.getService()
    if (typeof service?.resolve !== 'function' || typeof service?.transcribe !== 'function') {
      throw new Error('DSH 语音识别未启用，请启用官方语音输入组件')
    }
    const provider = service.resolve({ audio: new Uint8Array(0), language: 'zh' }).provider
    return { service, provider }
  }

  warm() {
    if (this.loading) return this.loading
    const controller = new AbortController()
    this.warmAbort = controller
    const loading = (async () => {
      const { service, provider } = this.#selected()
      const preparation = provider.preparation
      if (!preparation) return
      const phase = preparation.snapshot().phase
      if (phase === 'ready' || phase === 'standby') return
      if (phase === 'unprepared' || phase === 'failed' || phase === 'cancelled') {
        service.prepare(provider.info.id)
      }
      await waitUntilReady(preparation, controller.signal)
    })()
    this.loading = loading
    void loading.finally(() => {
      if (this.loading === loading) this.loading = undefined
      if (this.warmAbort === controller) this.warmAbort = undefined
    }).catch(() => {})
    return loading
  }

  async transcribe(path) {
    if (!isValidRecordingPath(path)) throw new Error('录音文件路径无效')
    const controller = new AbortController()
    this.pending.add(controller)
    try {
      const audio = await readFile(path)
      await this.warm()
      controller.signal.throwIfAborted()
      const { service } = this.#selected()
      const spec = service.resolve({ audio, language: 'zh' })
      const transcript = await service.transcribe(spec, controller.signal)
      const text = String(transcript?.text ?? '').trim()
      const seconds = Number.isFinite(transcript?.audioSeconds)
        ? transcript.audioSeconds : Math.max(0, (audio.length - 44) / 32000)
      return implausibleDshTranscript(text, seconds) ? '' : text
    } finally {
      this.pending.delete(controller)
      await unlink(path).catch(() => {})
    }
  }

  dispose() {
    this.warmAbort?.abort(new Error('语音识别已停止'))
    this.warmAbort = undefined
    this.loading = undefined
    for (const controller of this.pending) controller.abort(new Error('语音识别已停止'))
  }
}
