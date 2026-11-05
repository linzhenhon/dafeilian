import assert from 'node:assert/strict'
import { existsSync } from 'node:fs'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import test, { after } from 'node:test'
import { apply, inject, TASK_TARGET_ENDPOINT } from '../src/index.js'

// Native-menu fallback files must never land in the developer's real profile
// while the integration suite exercises the plugin.
const testFallbackFile = join(tmpdir(), `dsh-dafeiyu-user-settings-${process.pid}.json`)
process.env.DSH_DAFEIYU_USER_SETTINGS = testFallbackFile
after(() => rm(testFallbackFile, { force: true }).catch(() => {}))

test('plugin declares the service dependencies it actually consumes', () => {
  assert.ok(inject.includes('settings'), 'settings is a real hard dependency for live config')
  assert.ok(inject.includes('sessions'), 'sessions events drive the whole companion feature')
  assert.ok(inject.includes('sessionController'), 'task submission needs the host session controller')
})

test('package metadata exposes the DSH web client bundle', () => {
  const require = createRequire(import.meta.url)
  const metadata = require('dsh-dafeilian/package.json')
  assert.equal(metadata.exports['./client'], './lib/client.js')
  assert.equal(metadata.dsh.client.platform, 'web')
  assert.deepEqual(metadata.bundleDependencies, [
    '@deepseek-ai/cosmokit',
    '@deepseek-ai/schemastery',
    '@standard-schema/spec',
  ])
})

test('activation failure degrades to a disabled pet instead of failing the host', () => {
  const errors = []
  const ctx = {
    logger: { debug() {}, info() {}, warn() {}, error(message) { errors.push(message) } },
    settings: { register: () => { throw new Error('host settings API changed') } },
  }
  assert.doesNotThrow(() => apply(ctx, {}))
  assert.ok(errors.some((message) => message.includes('failed to activate')))
})

async function waitFor(predicate, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (await predicate()) return
    await new Promise((resolve) => setTimeout(resolve, 25))
  }
  throw new Error('timed out waiting for plugin integration condition')
}

// Checks protocol semantics (message kind) rather than JSON whitespace, so
// both the Swift and Python helpers pass regardless of serializer formatting.
async function eventLogHasKind(eventLog, kind) {
  try {
    const lines = (await readFile(eventLog, 'utf8')).trim().split(/\r?\n/).filter(Boolean)
    return lines.some((line) => {
      try {
        return JSON.parse(line).kind === kind
      } catch {
        return false
      }
    })
  } catch {
    return false
  }
}

test('plugin forwards DSH-shaped session events and owns helper shutdown', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'dsh-dafeiyu-plugin-'))
  const eventLog = join(directory, 'events.jsonl')
  const listeners = new Map()
  let dispose
  const ctx = {
    logger: { debug() {}, info() {}, warn() {}, error() {} },
    on(name, callback) {
      listeners.set(name, callback)
    },
    effect(setup) {
      dispose = setup()
    },
  }

  apply(ctx, { balanceEnabled: false, helper: { headless: true, eventLog, logFile: null, tempDirectory: null } })
  const session = { header: { id: 'phase0-real-shape' } }
  listeners.get('session/event')(session, { type: 'turn/start', seq: 1, data: { turn: 1 } })
  listeners.get('session/event')(session, {
    type: 'tool/call',
    seq: 2,
    data: { callId: 'call-1', name: 'web_search' },
  })
  listeners.get('session/event')(session, {
    type: 'turn/end',
    seq: 3,
    data: { turn: 1, reason: { kind: 'completed' } },
  })
  dispose()

  await waitFor(async () => {
    return eventLogHasKind(eventLog, 'shutdown')
  })

  const messages = (await readFile(eventLog, 'utf8')).trim().split(/\r?\n/).map(JSON.parse)
  assert.deepEqual(messages.map((message) => message.kind), [
    'hello',
    'state',
    'novel',
    'state',
    'state',
    'pulse',
    'shutdown',
  ])
  assert.deepEqual(messages.map((message) => message.state).filter(Boolean), [
    'IDLE',
    'IDLE',
    'THINKING',
    'WORKING',
    'SUCCESS',
  ])
  await rm(directory, { recursive: true, force: true })
})

test('native task input reaches the currently selected DSH conversation', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'dsh-dafeiyu-task-input-'))
  const resultPath = join(directory, 'task-result.json')
  const fixture = join(dirname(fileURLToPath(import.meta.url)), 'fixtures', 'task-helper.js')
  const routes = new Map()
  let dispose
  let submitted
  const ctx = {
    logger: { debug() {}, info() {}, warn() {}, error() {} },
    on() { return () => {} },
    effect(setup) { dispose = setup() },
    get(name) {
      if (name !== 'sessionController') return undefined
      return { async prompt(request, signal) { submitted = { request, signal }; return { accepted: true } } }
    },
    inject(_services, callback) {
      callback({
        effect(setup) { setup() },
        webServer: { register({ path, handler }) { routes.set(path, handler); return () => routes.delete(path) } },
      })
    },
  }

  try {
    apply(ctx, { balanceEnabled: false, helper: {
      command: process.execPath, args: [fixture, resultPath], heartbeatMs: 0,
      logFile: null, tempDirectory: null,
    } })
    const handler = routes.get(TASK_TARGET_ENDPOINT)
    assert.equal(typeof handler, 'function')
    const req = {
      method: 'POST', socket: { remoteAddress: '127.0.0.1' },
      headers: { host: '127.0.0.1:3080', origin: 'http://127.0.0.1:3080' },
      async *[Symbol.asyncIterator]() { yield Buffer.from('{"sessionId":"current-session"}') },
    }
    let status
    await handler(req, { writeHead(next) { status = next }, end() {} })
    assert.equal(status, 200)

    await waitFor(() => existsSync(resultPath))
    const result = JSON.parse(await readFile(resultPath, 'utf8'))
    assert.equal(result.kind, 'task_result')
    assert.equal(result.accepted, true)
    assert.deepEqual(submitted.request, {
      requestId: 'fixture-task-1', sessionId: 'current-session', mode: 'queue',
      content: [{ type: 'text', text: '从桌宠输入的任务' }],
    })
    assert.equal(submitted.signal.aborted, false)
  } finally {
    dispose?.()
    await rm(directory, { recursive: true, force: true })
  }
})

test('call mode reads the final answer from the selected conversation once', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'dsh-dafeiyu-voice-reply-'))
  const eventLog = join(directory, 'events.jsonl')
  const marker = join(directory, 'voice-ready')
  const fixture = join(dirname(fileURLToPath(import.meta.url)), 'fixtures', 'voice-helper.js')
  const routes = new Map()
  const listeners = new Map()
  let dispose
  const ctx = {
    logger: { debug() {}, info() {}, warn() {}, error() {} },
    on(name, callback) { listeners.set(name, callback); return () => listeners.delete(name) },
    effect(setup) { dispose = setup() },
    inject(_services, callback) {
      callback({ effect(setup) { setup() }, webServer: {
        register({ path, handler }) { routes.set(path, handler); return () => routes.delete(path) },
      } })
    },
  }
  try {
    apply(ctx, { balanceEnabled: false, helper: {
      command: process.execPath, args: [fixture, eventLog, marker], heartbeatMs: 0,
      logFile: null, tempDirectory: null,
    } })
    const handler = routes.get(TASK_TARGET_ENDPOINT)
    const req = {
      method: 'POST', socket: { remoteAddress: '127.0.0.1' },
      headers: { host: '127.0.0.1:3080', origin: 'http://127.0.0.1:3080' },
      async *[Symbol.asyncIterator]() { yield Buffer.from('{"sessionId":"voice-chat"}') },
    }
    await handler(req, { writeHead() {}, end() {} })
    await waitFor(() => existsSync(marker))
    await new Promise((resolve) => setTimeout(resolve, 100))
    const session = { header: { id: 'voice-chat' } }
    listeners.get('session/event')(session, { type: 'turn/start', seq: 1, data: {} })
    listeners.get('session/event')(session, { type: 'assistant/message', seq: 2, data: {
      message: { role: 'assistant', channel: 'final', content: '语音任务完成。' },
    } })
    listeners.get('session/event')(session, { type: 'turn/end', seq: 3, data: { reason: { kind: 'completed' } } })
    await waitFor(async () => {
      const lines = (await readFile(eventLog, 'utf8')).trim().split(/\r?\n/).filter(Boolean).map(JSON.parse)
      return lines.some((message) => message.kind === 'speak')
    })
    const messages = (await readFile(eventLog, 'utf8')).trim().split(/\r?\n/).map(JSON.parse)
    assert.deepEqual(messages.filter((message) => message.kind === 'speak').map((message) => message.text), ['语音任务完成。'])
    assert.deepEqual(messages.filter((message) => message.kind === 'call_message').map((message) => message.text), ['语音任务完成。'])
  } finally {
    dispose?.()
    await rm(directory, { recursive: true, force: true })
  }
})

test('live settings keep the active project state without restarting the helper', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'dsh-dafeiyu-live-settings-'))
  const eventLog = join(directory, 'events.jsonl')
  const listeners = new Map()
  let dispose
  let settingsListener
  let settingsValue = {
    enabled: true,
    scale: 1,
    bubbleScale: 1,
    activityLevel: 'normal',
    reducedMotion: false,
    soundEnabled: true,
    includeSubagents: false,
  }
  const settings = {
    get: () => ({ ...settingsValue }),
    watch(callback) {
      settingsListener = callback
      return () => { settingsListener = undefined }
    },
  }
  const ctx = {
    settings: { register: () => settings },
    logger: { debug() {}, info() {}, warn() {}, error() {} },
    on(name, callback) {
      listeners.set(name, callback)
    },
    effect(setup) {
      dispose = setup()
    },
  }

  apply(ctx, { helper: { headless: true, eventLog, logFile: null, tempDirectory: null } })
  const activeSession = { header: { id: 'live-settings', cwd: 'D:\\work\\active-project' } }
  listeners.get('session/event')(activeSession, { type: 'turn/start', seq: 1, data: { turn: 1 } })
  listeners.get('session/event')(activeSession, {
    type: 'todo/write',
    seq: 2,
    data: { todos: [{ content: '继续保留这个任务', status: 'in_progress' }] },
  })
  settingsValue = { ...settingsValue, scale: 0.9, bubbleScale: 0.8, idleTitle: '小弟继续等大哥', soundEnabled: false, soundPack: 'clean', soundStates: ['SUCCESS', 'BOGUS'] }
  settingsListener(settingsValue)
  listeners.get('session/event')(activeSession, {
    type: 'tool/call',
    seq: 3,
    data: { callId: 'edit-after-settings', name: 'apply_patch' },
  })
  dispose()

  await waitFor(async () => {
    return eventLogHasKind(eventLog, 'shutdown')
  })

  const messages = (await readFile(eventLog, 'utf8')).trim().split(/\r?\n/).map(JSON.parse)
  assert.equal(messages.filter((message) => message.kind === 'hello').length, 1)
  assert.equal(messages.filter((message) => message.kind === 'config').length, 1)
  assert.equal(messages.find((message) => message.kind === 'config').soundEnabled, false)
  assert.equal(messages.find((message) => message.kind === 'config').soundPack, 'clean')
  assert.equal(messages.find((message) => message.kind === 'config').idleTitle, '小弟继续等大哥')
  assert.deepEqual(messages.find((message) => message.kind === 'config').soundStates, ['SUCCESS'])
  const working = messages.findLast((message) => message.state === 'WORKING')
  assert.equal(working.project, 'active-project')
  assert.equal(working.task, '继续保留这个任务')
  await rm(directory, { recursive: true, force: true })
})

test('helper context-menu changes persist through the DSH settings service', async () => {
  const fixture = join(dirname(fileURLToPath(import.meta.url)), 'fixtures', 'settings-helper.js')
  const listeners = new Map()
  let dispose
  let settingsListener
  let persisted
  let settingsValue = {
    enabled: true,
    scale: 1,
    bubbleScale: 1,
    activityLevel: 'normal',
    reducedMotion: false,
    soundEnabled: true,
    bubbleMode: 'always',
    bubbleStates: ['SUCCESS', 'ERROR', 'WAITING'],
    includeSubagents: false,
  }
  const settings = {
    get: () => ({ ...settingsValue }),
    watch(callback) {
      settingsListener = callback
      return () => { settingsListener = undefined }
    },
    async update(patch) {
      persisted = patch
      settingsValue = { ...settingsValue, ...patch }
      settingsListener?.({ ...settingsValue })
    },
  }
  const ctx = {
    settings: { register: () => settings },
    logger: { debug() {}, info() {}, warn() {}, error() {} },
    on(name, callback) {
      listeners.set(name, callback)
    },
    effect(setup) {
      dispose = setup()
    },
  }

  apply(ctx, {
    helper: {
      command: process.execPath,
      args: [fixture],
      headless: false,
      heartbeatMs: 0,
      logFile: null,
      tempDirectory: null,
    },
  })
  await waitFor(() => persisted !== undefined)
  assert.deepEqual(persisted, {
    scale: 0.6,
    bubbleScale: 0.9,
    reducedMotion: true,
    soundEnabled: false,
    soundPack: 'video',
  })
  assert.equal(settingsValue.scale, 0.6)
  assert.equal(settingsValue.bubbleScale, 0.9)
  assert.equal(settingsValue.reducedMotion, true)
  assert.equal(settingsValue.soundEnabled, false)
  assert.equal(settingsValue.soundPack, 'video')
  dispose()
})

test('a failed settings write keeps the native menu choice in the fallback and replay snapshot', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'dsh-dafeiyu-settings-fallback-'))
  const eventLog = join(directory, 'events.jsonl')
  const fallbackFile = join(directory, 'user-settings.json')
  const fixture = join(dirname(fileURLToPath(import.meta.url)), 'fixtures', 'settings-log-helper.js')
  const previousFallback = process.env.DSH_DAFEIYU_USER_SETTINGS
  process.env.DSH_DAFEIYU_USER_SETTINGS = fallbackFile

  const listeners = new Map()
  let dispose
  let settingsListener
  const warnings = []
  let settingsValue = {
    enabled: true,
    scale: 1,
    bubbleScale: 1,
    activityLevel: 'normal',
    reducedMotion: false,
    soundEnabled: true,
    bubbleMode: 'always',
    bubbleStates: ['SUCCESS', 'ERROR', 'WAITING'],
    includeSubagents: false,
  }
  const settings = {
    get: () => ({ ...settingsValue }),
    watch(callback) {
      settingsListener = callback
      return () => { settingsListener = undefined }
    },
    async update() {
      throw new Error('No configurable plugin entry "dsh-dafeiyu"')
    },
  }
  const ctx = {
    settings: { register: () => settings },
    logger: { debug() {}, info() {}, warn(message) { warnings.push(message) }, error() {} },
    on(name, callback) {
      listeners.set(name, callback)
    },
    effect(setup) {
      dispose = setup()
    },
  }

  try {
    apply(ctx, {
      helper: {
        command: process.execPath,
        args: [fixture, eventLog],
        headless: false,
        heartbeatMs: 0,
        logFile: null,
        tempDirectory: null,
      },
    })

    await waitFor(() => existsSync(fallbackFile))
    await waitFor(async () => eventLogHasKind(eventLog, 'config'))

    const messages = (await readFile(eventLog, 'utf8')).trim().split(/\r?\n/).map(JSON.parse)
    const config = messages.find((message) => message.kind === 'config')
    assert.equal(config.scale, 0.6)
    assert.equal(config.bubbleScale, 0.9)
    assert.equal(config.reducedMotion, true)
    assert.ok(warnings.some((message) => String(message).includes('failed to persist helper settings')))

    const fallback = JSON.parse(await readFile(fallbackFile, 'utf8'))
    assert.deepEqual(fallback.overrides.scale, { value: 0.6, host: 1 })
    assert.deepEqual(fallback.overrides.bubbleScale, { value: 0.9, host: 1 })
    assert.deepEqual(fallback.overrides.reducedMotion, { value: true, host: false })
  } finally {
    dispose?.()
    if (previousFallback === undefined) delete process.env.DSH_DAFEIYU_USER_SETTINGS
    else process.env.DSH_DAFEIYU_USER_SETTINGS = previousFallback
    await rm(directory, { recursive: true, force: true })
  }
})
