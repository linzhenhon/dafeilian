import { spawn } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { existsSync } from 'node:fs'
import { unlink } from 'node:fs/promises'
import { homedir } from 'node:os'
import { basename, dirname, join, resolve } from 'node:path'
import { createInterface } from 'node:readline'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const root = resolve(here, '..')
const worker = join(root, 'runtime', 'voice_worker.py')
const bundledPython = join(root, '.build', 'voice-venv', 'Scripts', 'python.exe')
const DEFAULT_MODEL = 'openai/whisper-base'
const userData = process.platform === 'win32'
  ? process.env.LOCALAPPDATA || join(homedir(), 'AppData', 'Local')
  : process.env.XDG_CACHE_HOME || join(homedir(), '.cache')
export const voiceDirectory = resolve(process.env.DSH_DAFEIYU_VOICE_DIR || join(userData, 'dsh-dafeiyu', 'voice-temp'))

export function isValidRecordingPath(path, directory = voiceDirectory) {
  if (typeof path !== 'string') return false
  const filename = resolve(path)
  const sameDirectory = process.platform === 'win32'
    ? dirname(filename).toLowerCase() === resolve(directory).toLowerCase()
    : dirname(filename) === resolve(directory)
  return sameDirectory && /^[a-f0-9]{32}\.wav$/u.test(basename(filename))
}

export class VoiceTranscriber {
  constructor(config = {}) {
    this.configure(config)
    this.pending = new Map()
    this.child = undefined
  }

  configure(config = {}) {
    const python = config.voicePython || (existsSync(bundledPython) ? bundledPython : '')
    const model = config.voiceModel || DEFAULT_MODEL
    const cache = config.voiceCache || ''
    if (this.python === python && this.model === model && this.cache === cache) return
    this.dispose?.()
    this.python = python
    this.model = model
    this.cache = cache
  }

  async transcribe(path) {
    if (!isValidRecordingPath(path)) throw new Error('录音文件路径无效')
    const filename = resolve(path)
    try {
      return await this.#request({ path: filename })
    } finally {
      await unlink(filename).catch(() => {})
    }
  }

  warm() {
    return this.#request({ warm: true })
  }

  #request(payload) {
    if (!this.python || !existsSync(this.python)) return Promise.reject(new Error('未配置本地语音识别 Python'))
    if (!existsSync(worker)) return Promise.reject(new Error('语音识别程序缺失'))
    if (!this.child) this.#start()
    const id = randomUUID()
    return new Promise((resolveResult, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id)
        this.dispose()
        reject(new Error('语音识别超时'))
      }, 120_000)
      this.pending.set(id, { resolve: resolveResult, reject, timer })
      this.child.stdin.write(`${JSON.stringify({ id, ...payload })}\n`, (error) => {
        if (!error) return
        const pending = this.pending.get(id)
        if (!pending) return
        clearTimeout(pending.timer)
        this.pending.delete(id)
        reject(error)
      })
    })
  }

  #start() {
    const env = {
      ...process.env,
      PYTHONIOENCODING: 'utf-8',
      HF_HUB_DISABLE_PROGRESS_BARS: '1',
      HF_HUB_OFFLINE: '1',
      TRANSFORMERS_OFFLINE: '1',
    }
    if (this.cache) env.HF_HOME = this.cache
    const child = spawn(this.python, ['-u', worker, '--model', this.model], {
      cwd: root, env, stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true,
    })
    this.child = child
    let stderrTail = ''
    child.stderr.on('data', (chunk) => { stderrTail = (stderrTail + String(chunk)).slice(-1200) })
    createInterface({ input: child.stdout }).on('line', (line) => {
      let result
      try { result = JSON.parse(line) } catch { return }
      const pending = this.pending.get(result.id)
      if (!pending) return
      clearTimeout(pending.timer)
      this.pending.delete(result.id)
      if (result.error) pending.reject(new Error(result.error))
      else pending.resolve(String(result.text ?? '').trim())
    })
    const end = (error) => {
      if (this.child !== child) return
      this.child = undefined
      for (const pending of this.pending.values()) {
        clearTimeout(pending.timer)
        pending.reject(error)
      }
      this.pending.clear()
    }
    child.once('error', (error) => end(error))
    child.once('exit', () => end(new Error(`语音识别进程已退出${stderrTail ? `：${stderrTail.trim().slice(-300)}` : ''}`)))
  }

  dispose() {
    const child = this.child
    this.child = undefined
    child?.kill()
    for (const pending of this.pending?.values() ?? []) {
      clearTimeout(pending.timer)
      pending.reject(new Error('语音识别已停止'))
    }
    this.pending?.clear()
  }
}
