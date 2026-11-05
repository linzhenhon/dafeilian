import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { Readable } from 'node:stream'
import test from 'node:test'
import { createConfigHandler } from '../src/index.js'

function settingsFixture() {
  let value = {
    enabled: true, scale: 1, bubbleScale: 1, activityLevel: 'normal', reducedMotion: false, soundEnabled: true,
    includeSubagents: false, marketWatchEnabled: false,
    marketWatchSymbols: 'BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,DOGEUSDT', marketWatchSymbol: 'BTCUSDT', marketWatchInterval: '15m',
  }
  return {
    get: () => ({ ...value }),
    update: async (patch) => { value = { ...value, ...patch } },
  }
}

async function request(handler, { method = 'GET', body = '', address = '127.0.0.1', origin } = {}) {
  const req = Readable.from(body ? [Buffer.from(body)] : [])
  req.method = method
  req.socket = { remoteAddress: address }
  req.headers = { host: '127.0.0.1:2026', ...(origin ? { origin } : {}) }
  let status
  let payload = ''
  const res = {
    writeHead(code) { status = code },
    end(chunk = '') { payload += chunk },
  }
  await handler(req, res)
  return { status, body: JSON.parse(payload) }
}

test('local config endpoint reads and persists an allowed patch', async () => {
  const settings = settingsFixture()
  const handler = createConfigHandler(settings)
  const initial = await request(handler)
  assert.equal(initial.status, 200)
  assert.equal(initial.body.enabled, true)

  const changed = await request(handler, {
    method: 'PATCH',
    body: JSON.stringify({ enabled: false, scale: 0.8, bubbleScale: 0.8, soundEnabled: false }),
    origin: 'http://127.0.0.1:2026',
  })
  assert.equal(changed.status, 200)
  assert.equal(changed.body.enabled, false)
  assert.equal(changed.body.scale, 0.8)
  assert.equal(changed.body.bubbleScale, 0.8)
  assert.equal(changed.body.soundEnabled, false)
})

test('config endpoint persists market watch selection and interval', async () => {
  const handler = createConfigHandler(settingsFixture())
  const changed = await request(handler, {
    method: 'PATCH',
    body: JSON.stringify({
      marketWatchEnabled: true,
      marketWatchSymbols: 'BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,DOGEUSDT',
      marketWatchSymbol: 'SOLUSDT',
      marketWatchInterval: '1h',
    }),
    origin: 'http://127.0.0.1:2026',
  })
  assert.equal(changed.status, 200)
  assert.equal(changed.body.marketWatchEnabled, true)
  assert.equal(changed.body.marketWatchSymbol, 'SOLUSDT')
  assert.equal(changed.body.marketWatchInterval, '1h')
})

test('config endpoint persists per-event sound choices and drops unknown states', async () => {
  const handler = createConfigHandler(settingsFixture())
  const changed = await request(handler, {
    method: 'PATCH',
    body: JSON.stringify({ soundStates: ['ERROR', 'WAITING'] }),
    origin: 'http://127.0.0.1:2026',
  })
  assert.equal(changed.status, 200)
  assert.deepEqual(changed.body.soundStates, ['ERROR'])
  const invalid = await request(handler, { method: 'PATCH', body: '{"soundStates":"ERROR"}', origin: 'http://127.0.0.1:2026' })
  assert.equal(invalid.status, 400)
})

test('config endpoint switches between bundled and custom voice packs', async () => {
  const handler = createConfigHandler(settingsFixture())
  const selected = await request(handler, {
    method: 'PATCH', body: '{"soundPack":"clean"}', origin: 'http://127.0.0.1:2026',
  })
  assert.equal(selected.status, 200)
  assert.equal(selected.body.soundPack, 'clean')
  const video = await request(handler, {
    method: 'PATCH', body: '{"soundPack":"video"}', origin: 'http://127.0.0.1:2026',
  })
  assert.equal(video.status, 200)
  assert.equal(video.body.soundPack, 'video')
  const custom = await request(handler, {
    method: 'PATCH', body: '{"soundPack":"custom"}', origin: 'http://127.0.0.1:2026',
  })
  assert.equal(custom.status, 200)
  assert.equal(custom.body.soundPack, 'custom')
  assert.equal((await request(handler, { method: 'PATCH', body: '{"soundPack":"../secret"}' })).status, 400)
})

test('config endpoint saves a custom idle title and rejects invalid titles', async () => {
  const handler = createConfigHandler(settingsFixture())
  const changed = await request(handler, {
    method: 'PATCH', body: JSON.stringify({ idleTitle: '  小弟随时待命  ' }), origin: 'http://127.0.0.1:2026',
  })
  assert.equal(changed.status, 200)
  assert.equal(changed.body.idleTitle, '小弟随时待命')
  for (const idleTitle of ['', '  ', '第一行\n第二行', 'a'.repeat(41), 123]) {
    assert.equal((await request(handler, { method: 'PATCH', body: JSON.stringify({ idleTitle }) })).status, 400)
  }
})

test('config endpoint accepts local voice paths and rejects multiline values', async () => {
  const handler = createConfigHandler(settingsFixture())
  const result = await request(handler, {
    method: 'PATCH', body: JSON.stringify({ voicePython: 'C:\\Python\\python.exe', voiceCache: 'D:\\models', voiceModel: 'openai/whisper-base' }),
  })
  assert.equal(result.status, 200)
  assert.equal(result.body.voiceCache, 'D:\\models')
  assert.equal((await request(handler, { method: 'PATCH', body: JSON.stringify({ voicePython: 'bad\npath' }) })).status, 400)
})

test('config endpoint selects DSH or local speech recognition', async () => {
  const handler = createConfigHandler(settingsFixture())
  const selected = await request(handler, { method: 'PATCH', body: '{"voiceEngine":"dsh"}' })
  assert.equal(selected.status, 200)
  assert.equal(selected.body.voiceEngine, 'dsh')
  assert.equal((await request(handler, { method: 'PATCH', body: '{"voiceEngine":"unknown"}' })).status, 400)
})

test('sound states default to every event and drop unknown entries', async () => {
  const { normalizeSoundStates } = await import('../src/plugin.js')
  assert.deepEqual(normalizeSoundStates(undefined), ['SUCCESS', 'ERROR'])
  assert.deepEqual(normalizeSoundStates(['APPROVAL']), ['APPROVAL'])
  assert.deepEqual(normalizeSoundStates([]), [])
  assert.deepEqual(normalizeSoundStates(['ERROR', 'ERROR', 'IDLE']), ['ERROR'])
})

test('local config endpoint rejects remote, cross-origin, and unknown writes', async () => {
  const handler = createConfigHandler(settingsFixture())
  assert.equal((await request(handler, { address: '192.168.1.8' })).status, 403)
  assert.equal((await request(handler, { origin: 'https://example.com' })).status, 403)
  assert.equal((await request(handler, { method: 'PATCH', body: '{"surprise":true}' })).status, 400)
})

test('settings client debounces each slider independently', async () => {
  const source = await readFile(new URL('../lib/client.js', import.meta.url), 'utf8')
  assert.match(source, /sliderTimers = useRef\(new Map\(\)\)/u)
  assert.match(source, /sliderTimers\.current\.get\(field\)/u)
  assert.match(source, /sliderTimers\.current\.set\(field, timer\)/u)
  assert.match(source, /key: 'dsh-dafeilian'/u)
})
