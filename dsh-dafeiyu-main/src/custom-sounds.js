import { randomUUID } from 'node:crypto'
import { existsSync } from 'node:fs'
import { mkdir, rename, unlink, writeFile } from 'node:fs/promises'
import { homedir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { isLocalRequest, jsonResponse } from './local-http.js'

export const CUSTOM_SOUND_ENDPOINT = '/plugins/dsh-dafeiyu/custom-sounds'
export const CUSTOM_SOUND_FILES = Object.freeze({
  SUCCESS: 'success.wav', ERROR: 'error.wav', APPROVAL: 'approval.wav',
  SLEEP: 'sleep.wav', ALARM: 'alarm.wav', TODO: 'todo.wav',
})

const userData = process.platform === 'win32'
  ? process.env.LOCALAPPDATA || join(homedir(), 'AppData', 'Local')
  : process.env.XDG_DATA_HOME || join(homedir(), '.local', 'share')
export const customSoundsDirectory = resolve(process.env.DSH_DAFEIYU_CUSTOM_SOUNDS_DIR || join(userData, 'dsh-dafeiyu', 'custom-sounds'))
const MAX_BYTES = 3 * 1024 * 1024

export function customSoundPath(state, directory = customSoundsDirectory) {
  const name = CUSTOM_SOUND_FILES[state]
  return name ? join(directory, name) : null
}

export function validateCustomWav(bytes) {
  if (!Buffer.isBuffer(bytes) || bytes.length < 44 || bytes.length > MAX_BYTES) throw new Error('音频文件大小无效')
  if (bytes.toString('ascii', 0, 4) !== 'RIFF' || bytes.toString('ascii', 8, 12) !== 'WAVE'
    || bytes.readUInt32LE(4) !== bytes.length - 8 || bytes.toString('ascii', 12, 16) !== 'fmt '
    || bytes.readUInt32LE(16) !== 16 || bytes.readUInt16LE(20) !== 1
    || bytes.readUInt16LE(22) !== 1 || bytes.readUInt32LE(24) !== 44100
    || bytes.readUInt32LE(28) !== 88200 || bytes.readUInt16LE(32) !== 2
    || bytes.readUInt16LE(34) !== 16 || bytes.toString('ascii', 36, 40) !== 'data'
    || bytes.readUInt32LE(40) !== bytes.length - 44) {
    throw new Error('请上传由设置页转换的单声道 WAV 音频')
  }
  const seconds = (bytes.length - 44) / 88200
  if (seconds < 0.2 || seconds > 30) throw new Error('音频长度需为 0.2 至 30 秒')
  return seconds
}

export function createCustomSoundsHandler({ directory = customSoundsDirectory, onChange = () => {} } = {}) {
  return async (req, res) => {
    if (!isLocalRequest(req)) return jsonResponse(res, 403, { error: 'local access only' })
    let state
    try { state = new URL(req.url ?? '', 'http://dsh.local').searchParams.get('state') } catch {}
    if (req.method === 'GET') {
      return jsonResponse(res, 200, {
        states: Object.fromEntries(Object.keys(CUSTOM_SOUND_FILES).map((key) => [key, existsSync(customSoundPath(key, directory))])),
      })
    }
    const path = customSoundPath(state, directory)
    if (!path) return jsonResponse(res, 404, { error: 'unknown sound state' })
    if (req.method === 'DELETE') {
      try { await unlink(path) } catch (error) { if (error?.code !== 'ENOENT') return jsonResponse(res, 500, { error: '无法删除自定义音频' }) }
      try { onChange(state) } catch { /* A Helper restart must not undo a successful removal. */ }
      return jsonResponse(res, 200, { state, uploaded: false })
    }
    if (req.method !== 'POST') return jsonResponse(res, 405, { error: 'method not allowed' })
    if (!/^audio\/wav(?:\s*;.*)?$/iu.test(req.headers?.['content-type'] ?? '')) {
      return jsonResponse(res, 415, { error: '请上传 WAV 音频' })
    }
    const chunks = []
    let length = 0
    try {
      for await (const chunk of req) {
        length += chunk.length
        if (length > MAX_BYTES) return jsonResponse(res, 413, { error: '音频不得超过 30 秒' })
        chunks.push(chunk)
      }
      const bytes = Buffer.concat(chunks)
      validateCustomWav(bytes)
      await mkdir(dirname(path), { recursive: true })
      const temporary = `${path}.${randomUUID()}.tmp`
      try {
        await writeFile(temporary, bytes, { flag: 'wx' })
        await rename(temporary, path)
      } finally {
        await unlink(temporary).catch(() => {})
      }
      try { onChange(state) } catch { /* The saved file stays usable after a Helper restart. */ }
      return jsonResponse(res, 200, { state, uploaded: true })
    } catch (error) {
      return jsonResponse(res, 400, { error: error instanceof Error ? error.message : '音频处理失败' })
    }
  }
}
