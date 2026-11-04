import assert from 'node:assert/strict'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import test from 'node:test'

const directory = resolve('.build', 'test-dsh-speech')
process.env.DSH_DAFEIYU_VOICE_DIR = directory
const { DshSpeechTranscriber, implausibleDshTranscript } = await import('../src/dsh-speech-transcriber.js')

test('DSH recognizer receives the recorded WAV and returns its transcript', async () => {
  await mkdir(directory, { recursive: true })
  const path = resolve(directory, '1234567890abcdef1234567890abcdef.wav')
  const audio = Buffer.from('RIFFtest WAVE')
  await writeFile(path, audio)
  let phase = 'unprepared'
  const listeners = new Set()
  const provider = {
    info: { id: 'sensevoice-local' },
    preparation: {
      snapshot: () => ({ phase }),
      subscribe: (listener) => { listeners.add(listener); return () => listeners.delete(listener) },
    },
  }
  let received
  const service = {
    resolve(request) {
      assert.equal(request.language, 'zh')
      return { provider, ...request }
    },
    prepare(id) {
      assert.equal(id, 'sensevoice-local')
      phase = 'ready'
      for (const listener of listeners) listener()
    },
    async transcribe(spec, signal) {
      signal.throwIfAborted()
      received = spec.audio
      return { text: '大哥，任务已完成。' }
    },
  }
  const transcriber = new DshSpeechTranscriber(() => service)
  assert.equal(await transcriber.transcribe(path), '大哥，任务已完成。')
  assert.deepEqual(received, audio)
  await assert.rejects(readFile(path), { code: 'ENOENT' })
  assert.equal(transcriber.pending.size, 0)
})

test('DSH recognizer reports a missing official speech component', async () => {
  const transcriber = new DshSpeechTranscriber(() => undefined)
  await assert.rejects(transcriber.warm(), /DSH 语音识别未启用/u)
})

test('DSH recognizer rejects an implausible repeated transcript', () => {
  assert.equal(implausibleDshTranscript('你具有天文。'.repeat(60), 3.1), true)
  assert.equal(implausibleDshTranscript('大哥，任务已完成。', 3.1), false)
})
