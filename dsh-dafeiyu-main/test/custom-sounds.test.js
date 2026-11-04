import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'
import { createAssetRoutes } from '../src/index.js'
import { createCustomSoundsHandler, customSoundPath } from '../src/custom-sounds.js'

function wav(seconds = 0.5) {
  const size = Math.round(seconds * 44100) * 2
  const bytes = Buffer.alloc(44 + size)
  bytes.write('RIFF', 0); bytes.writeUInt32LE(bytes.length - 8, 4); bytes.write('WAVEfmt ', 8)
  bytes.writeUInt32LE(16, 16); bytes.writeUInt16LE(1, 20); bytes.writeUInt16LE(1, 22)
  bytes.writeUInt32LE(44100, 24); bytes.writeUInt32LE(88200, 28)
  bytes.writeUInt16LE(2, 32); bytes.writeUInt16LE(16, 34)
  bytes.write('data', 36); bytes.writeUInt32LE(size, 40)
  return bytes
}

function request(method, state, bytes = Buffer.alloc(0), address = '127.0.0.1') {
  const req = new EventEmitter()
  req.method = method
  req.url = `/plugins/dsh-dafeiyu/custom-sounds${state ? `?state=${state}` : ''}`
  req.socket = { remoteAddress: address }
  req.headers = { host: '127.0.0.1:3080', origin: 'http://127.0.0.1:3080', 'content-type': 'audio/wav' }
  req[Symbol.asyncIterator] = async function * () { yield bytes }
  return req
}

function response() {
  return { status: 0, headers: {}, body: Buffer.alloc(0),
    writeHead(status, headers) { this.status = status; this.headers = headers },
    end(body) { this.body = Buffer.isBuffer(body) ? body : Buffer.from(body ?? '') },
  }
}

test('custom sounds persist per state, preview, fall back, and can be removed', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'dsh-custom-sounds-'))
  const changed = []
  const handler = createCustomSoundsHandler({ directory, onChange: (state) => changed.push(state) })
  const routes = createAssetRoutes({ customDirectory: directory })
  try {
    const initial = response()
    await handler(request('GET'), initial)
    assert.equal(JSON.parse(initial.body).states.SLEEP, false)

    const upload = response()
    const audio = wav()
    await handler(request('POST', 'SLEEP', audio), upload)
    assert.equal(upload.status, 200)
    assert.deepEqual(await readFile(customSoundPath('SLEEP', directory)), audio)
    assert.deepEqual(changed, ['SLEEP'])

    const preview = response()
    const previewRequest = request('GET', 'SLEEP')
    previewRequest.url = '/plugins/dsh-dafeiyu/sound?pack=custom&state=SLEEP'
    routes.soundHandler(previewRequest, preview)
    assert.equal(preview.status, 200)
    assert.deepEqual(preview.body, audio)

    const fallback = response()
    const req = request('GET', 'TODO')
    req.url = '/plugins/dsh-dafeiyu/sound?pack=custom&state=TODO'
    routes.soundHandler(req, fallback)
    assert.equal(fallback.status, 200)
    assert.ok(fallback.body.length > audio.length)

    const remove = response()
    await handler(request('DELETE', 'SLEEP'), remove)
    assert.equal(remove.status, 200)
    assert.deepEqual(changed, ['SLEEP', 'SLEEP'])
    const after = response()
    await handler(request('GET'), after)
    assert.equal(JSON.parse(after.body).states.SLEEP, false)
  } finally { await rm(directory, { recursive: true, force: true }) }
})

test('custom sound upload rejects malformed audio, unknown states, and remote requests', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'dsh-custom-sounds-'))
  const handler = createCustomSoundsHandler({ directory })
  try {
    const bad = response()
    await handler(request('POST', 'ALARM', Buffer.from('not a wav')), bad)
    assert.equal(bad.status, 400)

    const traversal = response()
    await handler(request('POST', '../../outside', wav()), traversal)
    assert.equal(traversal.status, 404)

    const remote = response()
    await handler(request('POST', 'ALARM', wav(), '203.0.113.7'), remote)
    assert.equal(remote.status, 403)
  } finally { await rm(directory, { recursive: true, force: true }) }
})
