import { createRequire } from 'node:module'
import { existsSync, readFileSync, statSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import Schema from '@deepseek-ai/schemastery'
import { CompanionReducer } from './companion-reducer.js'
import { HelperProcess } from './helper-process.js'
import { VoiceTranscriber, voiceDirectory } from './voice-transcriber.js'
import { DshSpeechTranscriber } from './dsh-speech-transcriber.js'
import { CUSTOM_SOUND_ENDPOINT, createCustomSoundsHandler, customSoundPath, customSoundsDirectory } from './custom-sounds.js'
import { displayReply, spokenReply } from './voice-replies.js'
import { createSettingsScope } from './settings-scope.js'
import { createHelperLog, defaultHelperLogPath } from './helper-log.js'
import { createUserSettingsStore, defaultUserSettingsPath } from './user-settings.js'
import { resolveClientTarget } from './client-target.js'
import { isLocalRequest, jsonResponse } from './local-http.js'
import { TASK_TARGET_ENDPOINT, createTaskTargetHandler, submitDesktopTask } from './task-input.js'
import { BALANCE_ENDPOINT, createBalanceQuery, createBalanceMonitor, createBalanceHandler, balanceProviderNamespace } from './balance.js'
import { createMarketWatchMonitor, normalizeMarketInterval, normalizeMarketSymbol, normalizeMarketSymbols } from './market-watch.js'
import {
  CompanionMessageKind,
  CompanionState,
  createMessage,
} from './protocol.js'

const require = createRequire(import.meta.url)
const pkg = require('../package.json')

export const name = 'dsh-dafeilian'
// The plugin's feature is built on session events, and mounting requires the
// settings service (used to read live config). Keep the declared inject in
// sync with those real hard dependencies instead of listing a service that
// is never consumed directly.
export const inject = ['sessions', 'settings', 'sessionController']
export const CONFIG_ENDPOINT = '/plugins/dsh-dafeiyu/config'
export const EVENTS_ENDPOINT = '/plugins/dsh-dafeiyu/events'
export const MANIFEST_ENDPOINT = '/plugins/dsh-dafeiyu/manifest'
export const FRAME_ENDPOINT = '/plugins/dsh-dafeiyu/frame'
export const SOUND_ENDPOINT = '/plugins/dsh-dafeiyu/sound'
export { CUSTOM_SOUND_ENDPOINT }
export { TASK_TARGET_ENDPOINT }
export { BALANCE_ENDPOINT }

const here = dirname(fileURLToPath(import.meta.url))
const assetsRoot = resolve(here, '..', 'assets')
export const Config = Schema.object({
  enabled: Schema.boolean().default(true).description('启用桌面大肥鱼'),
  scale: Schema.number().min(0.55).max(1.4).step(0.05).default(1).role('slider').description('角色大小'),
  bubbleScale: Schema.number().min(0.8).max(1.2).step(0.05).default(1).role('slider').description('气泡大小'),
  idleTitle: Schema.string().min(1).max(40).default('小弟陪大哥待命').description('桌宠待机时气泡显示的标题'),
  voiceEngine: Schema.union([
    Schema.const('whisper').description('插件本地 Whisper'),
    Schema.const('dsh').description('DSH 内置 SenseVoice'),
  ]).default('whisper').description('录音与通话使用的语音识别服务'),
  voicePython: Schema.string().default('').description('本地语音识别 Python 路径（需安装 transformers、torch、soundfile、scipy）'),
  voiceModel: Schema.string().default('openai/whisper-base').description('本地语音识别模型路径或 Hugging Face 模型名'),
  voiceCache: Schema.string().default('').description('本地语音模型缓存目录（HF_HOME）'),
  voicePreload: Schema.boolean().default(false).description('启动桌宠时在后台预载语音识别模型，减少首次录音和通话等待（会持续占用内存）'),
  activityLevel: Schema.union([
    Schema.const('quiet').description('安静'),
    Schema.const('normal').description('标准'),
    Schema.const('lively').description('活泼'),
  ]).default('normal').description('空闲微动作频率'),
  reducedMotion: Schema.boolean().default(false).description('减少走动、循环帧和程序化晃动'),
  soundEnabled: Schema.boolean().default(true).description('按选定场景播放提示音'),
  soundPack: Schema.union([
    Schema.const('video').description('提示音 C'),
    Schema.const('clean').description('提示音 B'),
    Schema.const('original').description('提示音 A'),
    Schema.const('custom').description('自定义'),
  ]).default('original').description('提示音版本'),
  soundStates: Schema.array(Schema.union([
    Schema.const('SUCCESS').description('对话完成'),
    Schema.const('ERROR').description('工具出错'),
    Schema.const('APPROVAL').description('等待审批'),
  ])).role('checkbox').default(['SUCCESS', 'ERROR']).description('播放提示音与系统通知的场景'),
  bubbleMode: Schema.union([
    Schema.const('always').description('常驻显示'),
    Schema.const('hidden').description('完全隐藏'),
    Schema.const('custom').description('自定义显示状态'),
  ]).default('always').description('气泡显示模式'),
  bubbleStates: Schema.array(Schema.string()).default(['SUCCESS', 'ERROR', 'WAITING']).description('自定义模式下显示气泡的状态'),
  includeSubagents: Schema.boolean().default(false).description('允许子 Agent 抢占宠物状态'),
  webOverlay: Schema.boolean().default(false).description('在 DSH 页面右下角显示轻量桌宠（可与桌面窗口同时开启）'),
  clientTarget: Schema.union(['auto', 'web', 'desktop']).default('auto').description('打开 DSH 的目标客户端（自动识别 WebUI／桌面端）'),
  balanceEnabled: Schema.boolean().default(true).description('在状态气泡和设置页显示 DeepSeek 余额'),
  balanceSource: Schema.union(['auto', 'api-key', 'account']).default('auto').description('余额来源：自动优先 API Key，也可选择已登录账户'),
  marketWatchEnabled: Schema.boolean().default(false).description('启用炒币盯盘动作与实时行情卡片'),
  marketWatchSymbols: Schema.string().default('BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,DOGEUSDT').description('盯盘币种，最多五个 USDT 现货交易对，逗号分隔'),
  marketWatchSymbol: Schema.string().default('BTCUSDT').description('桌宠行情卡片当前展示的币种'),
  marketWatchInterval: Schema.union([
    Schema.const('1m').description('1 分钟'),
    Schema.const('15m').description('15 分钟'),
    Schema.const('1h').description('1 小时'),
    Schema.const('4h').description('4 小时'),
  ]).default('15m').description('盯盘 K 线周期'),
}).description('由 DeepSeek Harness 状态驱动的桌面大肥鱼伴侣')

// Mark fields, rather than the root object: current DSH passes each volatile
// field as a live reference, while the config object remains an object.
for (const [key, field] of Object.entries(Config.dict)) Config.dict[key] = field.volatile()

const defaults = Object.freeze({
  enabled: true,
  scale: 1,
  bubbleScale: 1,
  idleTitle: '小弟陪大哥待命',
  voiceEngine: 'whisper',
  voicePython: '',
  voiceModel: 'openai/whisper-base',
  voiceCache: '',
  voicePreload: false,
  activityLevel: 'normal',
  reducedMotion: false,
  soundEnabled: true,
  soundPack: 'original',
  soundStates: ['SUCCESS', 'ERROR'],
  bubbleMode: 'always',
  bubbleStates: ['SUCCESS', 'ERROR', 'WAITING'],
  includeSubagents: false,
  webOverlay: false,
  clientTarget: 'auto',
  balanceEnabled: true,
  balanceSource: 'auto',
  marketWatchEnabled: false,
  marketWatchSymbols: 'BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,DOGEUSDT',
  marketWatchSymbol: 'BTCUSDT',
  marketWatchInterval: '15m',
})

const SOUND_STATES = new Set(['SUCCESS', 'ERROR', 'APPROVAL'])
const SOUND_PACKS = new Set(['original', 'clean', 'video', 'custom'])
const SOUND_FILES = Object.freeze({
  SUCCESS: 'success.wav', ERROR: 'error.wav', APPROVAL: 'approval.wav',
  SLEEP: 'sleep.wav', ALARM: 'alarm.wav', TODO: 'todo.wav',
})
const SOUND_PREVIEW_STATES = new Set(Object.keys(SOUND_FILES))

export function normalizeSoundPack(value) {
  return SOUND_PACKS.has(value) ? value : defaults.soundPack
}

export function normalizeSoundStates(value) {
  if (!Array.isArray(value)) return [...defaults.soundStates]
  return [...new Set(value.filter((state) => SOUND_STATES.has(state)))]
}

function publicConfig(config = {}) {
  return {
    enabled: config.enabled ?? defaults.enabled,
    scale: config.scale ?? defaults.scale,
    bubbleScale: config.bubbleScale ?? defaults.bubbleScale,
    idleTitle: config.idleTitle ?? defaults.idleTitle,
    voiceEngine: config.voiceEngine ?? defaults.voiceEngine,
    voicePython: config.voicePython ?? defaults.voicePython,
    voiceModel: config.voiceModel ?? defaults.voiceModel,
    voiceCache: config.voiceCache ?? defaults.voiceCache,
    voicePreload: config.voicePreload === true,
    activityLevel: config.activityLevel ?? defaults.activityLevel,
    reducedMotion: config.reducedMotion ?? defaults.reducedMotion,
    soundEnabled: config.soundEnabled ?? defaults.soundEnabled,
    soundPack: normalizeSoundPack(config.soundPack),
    soundStates: normalizeSoundStates(config.soundStates),
    bubbleMode: config.bubbleMode ?? defaults.bubbleMode,
    bubbleStates: Array.isArray(config.bubbleStates) ? config.bubbleStates : defaults.bubbleStates,
    includeSubagents: config.includeSubagents ?? defaults.includeSubagents,
    webOverlay: config.webOverlay === true,
    clientTarget: config.clientTarget ?? defaults.clientTarget,
    balanceEnabled: config.balanceEnabled !== false,
    balanceSource: config.balanceSource ?? defaults.balanceSource,
    marketWatchEnabled: config.marketWatchEnabled === true,
    marketWatchSymbols: normalizeMarketSymbols(config.marketWatchSymbols).join(','),
    marketWatchSymbol: normalizeMarketSymbol(config.marketWatchSymbol, normalizeMarketSymbols(config.marketWatchSymbols)),
    marketWatchInterval: normalizeMarketInterval(config.marketWatchInterval),
  }
}

async function readPatch(req) {
  const chunks = []
  let bytes = 0
  for await (const chunk of req) {
    bytes += chunk.length
    if (bytes > 8192) throw new Error('request body is too large')
    chunks.push(chunk)
  }
  const value = JSON.parse(Buffer.concat(chunks).toString('utf8'))
  if (value === null || typeof value !== 'object' || Array.isArray(value)) throw new Error('patch must be an object')
  const allowed = new Set(Object.keys(defaults))
  if (Object.keys(value).some((key) => !allowed.has(key))) throw new Error('patch contains an unknown setting')
  if ('soundStates' in value) {
    if (!Array.isArray(value.soundStates)) throw new Error('soundStates must be an array')
    value.soundStates = normalizeSoundStates(value.soundStates)
  }
  if ('soundPack' in value && !SOUND_PACKS.has(value.soundPack)) {
    throw new Error('soundPack must be original, clean, video, or custom')
  }
  if ('voiceEngine' in value && !['whisper', 'dsh'].includes(value.voiceEngine)) {
    throw new Error('voiceEngine must be whisper or dsh')
  }
  if ('idleTitle' in value) {
    if (typeof value.idleTitle !== 'string' || !value.idleTitle.trim() || value.idleTitle.trim().length > 40 || /[\r\n\x00-\x1f]/u.test(value.idleTitle)) {
      throw new Error('idleTitle must be a single line of 1–40 characters')
    }
    value.idleTitle = value.idleTitle.trim()
  }
  for (const key of ['voicePython', 'voiceModel', 'voiceCache']) {
    if (key in value && (typeof value[key] !== 'string' || value[key].length > 1024 || /[\r\n\x00-\x1f]/u.test(value[key]))) {
      throw new Error(`${key} must be a single-line string under 1024 characters`)
    }
  }
  return value
}

export function createConfigHandler(settings) {
  return async (req, res) => {
    if (!isLocalRequest(req)) {
      jsonResponse(res, 403, { error: 'local access only' })
      return
    }
    if (req.method === 'GET') {
      jsonResponse(res, 200, settings.get())
      return
    }
    if (req.method !== 'PATCH') {
      jsonResponse(res, 405, { error: 'method not allowed' })
      return
    }
    if (typeof settings.update !== 'function') {
      jsonResponse(res, 503, { error: 'settings are read-only; restart DSH or use a supported host version' })
      return
    }
    try {
      await settings.update(await readPatch(req))
      jsonResponse(res, 200, settings.get())
    } catch (error) {
      jsonResponse(res, 400, { error: error instanceof Error ? error.message : String(error) })
    }
  }
}

// Server-sent events channel mirroring the companion protocol for in-page
// consumers (the future web overlay). Snapshot kinds are remembered so a client
// that connects late still renders the current state immediately.
export function createEventStream() {
  const clients = new Set()
  const snapshot = new Map()
  return {
    get clientCount() {
      return clients.size
    },
    broadcast(message) {
      if (message?.kind === 'hello' || message?.kind === 'state' || message?.kind === 'task'
        || message?.kind === 'tasks' || message?.kind === 'config' || message?.kind === 'balance') {
        snapshot.set(message.kind, message)
      }
      const payload = `data: ${JSON.stringify(message)}\n\n`
      for (const res of clients) {
        try {
          res.write(payload)
        } catch {
          clients.delete(res)
        }
      }
    },
    add(res) {
      clients.add(res)
      for (const message of snapshot.values()) {
        res.write(`data: ${JSON.stringify(message)}\n\n`)
      }
      return () => clients.delete(res)
    },
  }
}

export function createEventsHandler(stream) {
  return (req, res) => {
    if (!isLocalRequest(req)) {
      jsonResponse(res, 403, { error: 'local access only' })
      return
    }
    res.writeHead(200, {
      'content-type': 'text/event-stream; charset=utf-8',
      'cache-control': 'no-store',
      connection: 'keep-alive',
    })
    res.write('retry: 2000\n\n')
    const remove = stream.add(res)
    req.on('close', remove)
  }
}

// Frame bytes are served only for paths the manifest declares, so the query
// parameter can never steer the reader outside assets/pet. Returns null when
// the manifest cannot be read; the overlay routes then stay unregistered.
export function createAssetRoutes({ customDirectory = customSoundsDirectory } = {}) {
  let manifest
  try {
    manifest = JSON.parse(readFileSync(join(assetsRoot, 'pet-manifest-custom.json'), 'utf8'))
  } catch {
    return null
  }
  const frames = new Set()
  for (const clip of Object.values(manifest.clips ?? {})) {
    for (const frame of clip.frames ?? []) frames.add(frame)
  }
  return {
    manifestHandler(req, res) {
      if (!isLocalRequest(req)) {
        jsonResponse(res, 403, { error: 'local access only' })
        return
      }
      jsonResponse(res, 200, manifest)
    },
    frameHandler(req, res) {
      if (!isLocalRequest(req)) {
        jsonResponse(res, 403, { error: 'local access only' })
        return
      }
      let frame
      try {
        frame = new URL(req.url ?? '', 'http://dsh.local').searchParams.get('frame')
      } catch {
        frame = null
      }
      if (!frame || !frames.has(frame)) {
        jsonResponse(res, 404, { error: 'unknown frame' })
        return
      }
      let bytes
      try {
        bytes = readFileSync(join(assetsRoot, 'pet', frame))
      } catch {
        jsonResponse(res, 404, { error: 'frame unavailable' })
        return
      }
      res.writeHead(200, {
        'content-type': frame.endsWith('.png') ? 'image/png' : 'image/webp',
        'cache-control': 'public, max-age=86400',
        'content-length': bytes.length,
      })
      res.end(bytes)
    },
    soundHandler(req, res) {
      if (!isLocalRequest(req)) {
        jsonResponse(res, 403, { error: 'local access only' })
        return
      }
      if (req.method && req.method !== 'GET') {
        jsonResponse(res, 405, { error: 'method not allowed' })
        return
      }
      let pack
      let state
      try {
        const query = new URL(req.url ?? '', 'http://dsh.local').searchParams
        pack = query.get('pack')
        state = query.get('state')
      } catch {
        // Invalid requests fall through to the fixed allowlist below.
      }
      if (!SOUND_PACKS.has(pack) || !SOUND_PREVIEW_STATES.has(state)) {
        jsonResponse(res, 404, { error: 'unknown sound' })
        return
      }
      const customPath = pack === 'custom' ? customSoundPath(state, customDirectory) : null
      const path = customPath && existsSync(customPath)
        ? customPath : join(assetsRoot, 'sounds', ...(pack === 'original' || pack === 'custom' ? [] : [pack]), SOUND_FILES[state])
      let bytes
      try {
        bytes = readFileSync(path)
      } catch {
        jsonResponse(res, 404, { error: 'sound unavailable' })
        return
      }
      res.writeHead(200, {
        'content-type': 'audio/wav',
        'cache-control': 'private, no-store',
        'content-length': bytes.length,
        'x-content-type-options': 'nosniff',
        'cross-origin-resource-policy': 'same-origin',
      })
      res.end(bytes)
    },
  }
}

function mount(ctx, config = {}, eventCtx = ctx) {
  const logger = ctx.logger ?? console
  try {
    mountCompanion(ctx, config, eventCtx, logger)
  } catch (error) {
    // DSH treats a failing plugin activation as fatal for the whole boot
    // (dsh-app-boot rethrows init rejections). A host-side API change must
    // cost the pet its session, never the host its startup.
    logger.error?.(`dsh-dafeilian failed to activate and stays disabled for this session: ${error instanceof Error ? error.message : String(error)}`)
  }
}

// The host's settings layer is authoritative while it works. The override
// store only fills in fields whose settings.update() write failed, so a
// native menu choice survives a Helper restart on hosts that cannot expose the
// bundle-patch entry (issue #95). A later host-side change clears that field's
// fallback again.
function createEffectiveSettings(host, overrides, logger) {
  const watchers = new Set()
  const current = () => overrides.apply(host.get())
  const announce = () => {
    const next = current()
    for (const callback of watchers) {
      try {
        callback(next)
      } catch (error) {
        logger.warn?.(`dsh-dafeilian failed to deliver settings: ${error instanceof Error ? error.message : String(error)}`)
      }
    }
  }
  const offHost = host.watch?.(() => announce())
  return {
    namespace: host.namespace,
    describe: host.describe?.bind(host),
    get: current,
    watch(callback) {
      watchers.add(callback)
      return () => watchers.delete(callback)
    },
    ...(typeof host.update === 'function' ? {
      async update(patch) {
        await host.update(patch)
        overrides.clear(Object.keys(patch))
        announce()
      },
    } : {}),
    refresh: announce,
    dispose() {
      offHost?.()
      watchers.clear()
      host.dispose?.()
    },
  }
}

function mountCompanion(ctx, config = {}, eventCtx = ctx, logger) {
  const eventStream = createEventStream()
  const helperConfig = config.helper ?? {}
  // `helper.logFile: null` is the explicit test/custom-launch switch used by
  // HelperProcess; keep the settings diagnostics in the same file.
  const diagnosticsLog = createHelperLog(
    helperConfig.logFile === undefined ? defaultHelperLogPath() : helperConfig.logFile,
  )
  const hostSettings = createSettingsScope(ctx, Config, config, publicConfig)
  const overrides = createUserSettingsStore(defaultUserSettingsPath(), {
    warn(message) {
      diagnosticsLog.write('WARN', message)
      logger.warn?.(`dsh-dafeilian ${message}`)
    },
  })
  const settings = createEffectiveSettings(hostSettings, overrides, logger)
  const voice = new VoiceTranscriber(settings.get())
  const dshVoice = new DshSpeechTranscriber(() => {
    try {
      const service = ctx.get?.('speechToText')
      if (service) return service
    } catch { /* Some Host versions do not expose optional services through get(). */ }
    return ctx.speechToText
  })
  const selectedVoice = () => settings.get().voiceEngine === 'dsh' ? dshVoice : voice
  let diagnosticsLogged = false

  let bridge
  let reducer
  let restartTimer
  let activeSessionId
  let voiceCallActive = false
  let lastSpokenReply = ''
  let lastVisibleReply = ''
  let voiceIdleTimer
  let customSoundRevision = 0
  const balance = createBalanceMonitor({
    query: createBalanceQuery(ctx),
    onChange(snapshot) {
      const message = createMessage(CompanionMessageKind.BALANCE, snapshot)
      if (bridge) bridge.send(message)
      else eventStream.broadcast(message)
    },
  })

  const marketWatch = createMarketWatchMonitor({
    logger,
    onUpdate(snapshot) {
      if (bridge) bridge.send(createMessage(CompanionMessageKind.MARKET, snapshot))
    },
  })
  let marketWatchActive = false
  const configureMarketWatch = (resolved) => {
    const enabled = resolved.enabled !== false && resolved.marketWatchEnabled === true
    if (!enabled && !marketWatchActive) return
    marketWatchActive = enabled
    marketWatch.configure({
      enabled,
      symbols: resolved.marketWatchSymbols,
      selectedSymbol: resolved.marketWatchSymbol,
      interval: resolved.marketWatchInterval,
    })
  }

  const stopRuntime = (reason = 'settings-change') => {
    if (marketWatchActive) marketWatch.stop()
    marketWatchActive = false
    bridge?.stop(reason)
    bridge = undefined
    reducer = undefined
    voiceCallActive = false
    lastSpokenReply = ''
    if (voiceIdleTimer) clearTimeout(voiceIdleTimer)
    voiceIdleTimer = undefined
    voice.dispose()
    dshVoice.dispose()
  }

  const preloadVoice = () => {
    const started = Date.now()
    diagnosticsLog.write('INFO', 'voice model background preload started')
    void selectedVoice().warm().then(() => {
      diagnosticsLog.write('INFO', `voice model background preload ready after ${Date.now() - started}ms`)
    }).catch((error) => {
      diagnosticsLog.write('WARN', `voice model background preload failed: ${error instanceof Error ? error.message : String(error)}`)
    })
  }

  const restartRuntime = (next) => {
    stopRuntime('settings-change')
    startRuntime(next)
  }

  // `settings.describe()` lists the settings-page namespaces, not the
  // configEditor entries that `settings.update()` writes. Its absence of
  // "dsh-dafeilian" is not evidence of a failed write (issue #95), so it is only
  // printed on an actual failure and labelled explicitly.
  const settingsPageNamespaceList = () => {
    try {
      return (hostSettings.describe?.() ?? []).map((row) => row.ns).join(',')
    } catch {
      return ''
    }
  }

  const helperEnvironment = (resolved) => ({
    ...helperConfig.env,
    DSH_DAFEIYU_SCALE: String(resolved.scale ?? defaults.scale),
    DSH_DAFEIYU_BUBBLE_SCALE: String(resolved.bubbleScale ?? defaults.bubbleScale),
    DSH_DAFEIYU_IDLE_TITLE: String(resolved.idleTitle ?? defaults.idleTitle),
    DSH_DAFEIYU_VOICE_DIR: voiceDirectory,
    DSH_DAFEIYU_ACTIVITY_LEVEL: String(resolved.activityLevel ?? defaults.activityLevel),
    DSH_DAFEIYU_REDUCED_MOTION: resolved.reducedMotion === true ? '1' : '0',
    DSH_DAFEIYU_SOUND_ENABLED: resolved.soundEnabled !== false ? '1' : '0',
    DSH_DAFEIYU_SOUND_PACK: normalizeSoundPack(resolved.soundPack),
    DSH_DAFEIYU_CUSTOM_SOUNDS_DIR: customSoundsDirectory,
    DSH_DAFEIYU_SOUND_STATES: normalizeSoundStates(resolved.soundStates).join(','),
    DSH_DAFEIYU_BUBBLE_MODE: String(resolved.bubbleMode ?? defaults.bubbleMode),
    DSH_DAFEIYU_BUBBLE_STATES: (Array.isArray(resolved.bubbleStates) ? resolved.bubbleStates : defaults.bubbleStates).join(','),
    DSH_DAFEIYU_WEBUI_URL: resolveClientTarget({ ...config, ...resolved }).url,
    DSH_DAFEIYU_OPEN_LABEL: resolveClientTarget({ ...config, ...resolved }).label,
  })

  const applyLiveSettings = (next) => {
    if (!bridge || !reducer) return
    // Keep the environment used by a later Helper spawn in sync with the live
    // config; otherwise a crashed Helper would restart with stale values until
    // the replayed CONFIG snapshot arrives.
    bridge.options.env = { ...bridge.options.env, ...helperEnvironment(next) }
    for (const message of reducer.setIncludeSubagents(next.includeSubagents === true)) bridge.send(message)
    bridge.send(createMessage(CompanionMessageKind.CONFIG, {
      scale: next.scale ?? defaults.scale,
      bubbleScale: next.bubbleScale ?? defaults.bubbleScale,
      idleTitle: next.idleTitle ?? defaults.idleTitle,
      activityLevel: next.activityLevel ?? defaults.activityLevel,
      reducedMotion: next.reducedMotion === true,
      soundEnabled: next.soundEnabled !== false,
      soundPack: normalizeSoundPack(next.soundPack),
      soundStates: normalizeSoundStates(next.soundStates),
      bubbleMode: next.bubbleMode ?? defaults.bubbleMode,
      bubbleStates: Array.isArray(next.bubbleStates) ? next.bubbleStates : defaults.bubbleStates,
      openUrl: resolveClientTarget({ ...config, ...next }).url,
      openLabel: resolveClientTarget({ ...config, ...next }).label,
      marketWatchEnabled: next.marketWatchEnabled === true,
      marketWatchSymbols: normalizeMarketSymbols(next.marketWatchSymbols),
      marketWatchSymbol: normalizeMarketSymbol(next.marketWatchSymbol, normalizeMarketSymbols(next.marketWatchSymbols)),
      marketWatchInterval: normalizeMarketInterval(next.marketWatchInterval),
    }))
  }

  const scheduleRestart = (next) => {
    if (restartTimer) clearTimeout(restartTimer)
    restartTimer = setTimeout(() => {
      restartTimer = undefined
      restartRuntime(next)
    }, 400)
    restartTimer.unref?.()
  }

  const startRuntime = (resolved) => {
    if (resolved.enabled === false) {
      logger.info?.('dsh-dafeilian is disabled')
      return
    }
    bridge = new HelperProcess({
      ...helperConfig,
      env: helperEnvironment(resolved),
      onSettingsChange: (report) => {
        if (typeof settings.update !== 'function') return
        const patch = {}
        if (Number.isFinite(report.scale)) patch.scale = Math.min(1.4, Math.max(0.55, report.scale))
        if (Number.isFinite(report.bubbleScale)) patch.bubbleScale = Math.min(1.2, Math.max(0.8, report.bubbleScale))
        if (typeof report.reducedMotion === 'boolean') patch.reducedMotion = report.reducedMotion
        if (typeof report.soundEnabled === 'boolean') patch.soundEnabled = report.soundEnabled
        if (SOUND_PACKS.has(report.soundPack)) patch.soundPack = report.soundPack
        if (typeof report.marketWatchEnabled === 'boolean') patch.marketWatchEnabled = report.marketWatchEnabled
        if (typeof report.marketWatchSymbol === 'string') patch.marketWatchSymbol = report.marketWatchSymbol
        if (['1m', '15m', '1h', '4h'].includes(report.marketWatchInterval)) patch.marketWatchInterval = report.marketWatchInterval
        if (Object.keys(patch).length === 0) return
        // Capture the host values before the write: the fallback only applies
        // while the host still holds the same baseline.
        const hostBefore = hostSettings.get()
        // Record before the write: DSH can resolve settings.update() without
        // the profile patch actually reaching disk. The store keeps the menu
        // value while the host holds either the old baseline or that value, and
        // a later host-side change (a third value) clears it.
        overrides.record(patch, hostBefore)
        void Promise.resolve(hostSettings.update(patch)).then(() => {
          diagnosticsLog.write('INFO', `persisted native menu settings: ${JSON.stringify(patch)}; fallback retained: ${JSON.stringify(overrides.snapshot())}`)
        }).catch((error) => {
          const detail = error instanceof Error ? error.message : String(error)
          diagnosticsLog.write(
            'ERROR',
            `settings.update failed for namespace "${hostSettings.namespace ?? 'dsh-dafeilian'}": ${detail}; settings-page namespaces (describe, not write targets): ${settingsPageNamespaceList() || '(none)'}; kept native menu values: ${JSON.stringify(overrides.snapshot())}`,
          )
          logger.warn?.(`dsh-dafeilian failed to persist helper settings: ${detail}`)
        }).finally(() => {
          // The Helper already applied the menu choice locally. Re-sending the
          // effective CONFIG keeps that choice in the replay snapshot if the
          // process restarts, and updates the environment for a later spawn.
          if (bridge) applyLiveSettings(settings.get())
        })
      },
      onSubmitTask: (report) => {
        const sourceBridge = bridge
        let controller
        let fileUploads
        try {
          controller = ctx.get?.('sessionController') ?? ctx.sessionController
        } catch { controller = undefined }
        try {
          fileUploads = ctx.get?.('fileUploads') ?? ctx.fileUploads
        } catch { fileUploads = undefined }
        diagnosticsLog.write('INFO', `task submission received: target=${activeSessionId ? 'selected' : 'missing'}, controller=${typeof controller?.prompt === 'function' ? 'available' : 'missing'}, files=${Array.isArray(report.files) ? report.files.length : 0}`)
        void submitDesktopTask(report, { sessionId: activeSessionId, controller, fileUploads }).then((result) => {
          diagnosticsLog.write(result.accepted ? 'INFO' : 'WARN', `task submission ${result.accepted ? 'accepted' : 'rejected'}${result.error ? `: ${result.error}` : ''}`)
          if (bridge !== sourceBridge) return
          sourceBridge.send(createMessage(CompanionMessageKind.TASK_RESULT, {
            requestId: report.requestId,
            ...result,
          }))
        })
      },
      onVoiceTranscribe: (report) => {
        const sourceBridge = bridge
        const started = Date.now()
        let clipBytes = 'unavailable'
        try { clipBytes = statSync(report.path).size } catch { /* The transcriber reports missing files. */ }
        diagnosticsLog.write('INFO', `voice segment received: bytes=${clipBytes}`)
        void selectedVoice().transcribe(report.path).then((text) => {
          diagnosticsLog.write(text ? 'INFO' : 'WARN', `voice segment recognized after ${Date.now() - started}ms: characters=${text.length}`)
          if (bridge === sourceBridge) sourceBridge.send(createMessage(CompanionMessageKind.VOICE_TRANSCRIPT, { requestId: report.requestId, text }))
        }).catch((error) => {
          diagnosticsLog.write('WARN', `voice segment failed after ${Date.now() - started}ms: ${error instanceof Error ? error.message : String(error)}`)
          if (bridge === sourceBridge) sourceBridge.send(createMessage(CompanionMessageKind.VOICE_TRANSCRIPT, {
            requestId: report.requestId, error: error instanceof Error ? error.message : String(error),
          }))
        })
      },
      onVoiceMode: (report) => {
        voiceCallActive = report.active === true
        lastSpokenReply = ''
        lastVisibleReply = ''
        if (voiceIdleTimer) clearTimeout(voiceIdleTimer)
        voiceIdleTimer = undefined
        if (report.mode === 'call' || report.mode === 'dictation') {
          const sourceBridge = bridge
          const started = Date.now()
          diagnosticsLog.write('INFO', `voice ${report.mode} model warm requested`)
          void selectedVoice().warm().then(() => {
            diagnosticsLog.write('INFO', `voice ${report.mode} model ready after ${Date.now() - started}ms`)
            if (bridge === sourceBridge) sourceBridge.send(createMessage(CompanionMessageKind.VOICE_STATUS, { ready: true }))
          }).catch((error) => {
            diagnosticsLog.write('WARN', `voice ${report.mode} model warm failed: ${error instanceof Error ? error.message : String(error)}`)
            if (bridge === sourceBridge) sourceBridge.send(createMessage(CompanionMessageKind.VOICE_STATUS, {
              ready: false, error: error instanceof Error ? error.message : String(error),
            }))
          })
        } else {
          if (settings.get().voicePreload === true) return
          const releaseVoice = () => {
            if (voiceCallActive || selectedVoice().pending.size > 0) {
              voiceIdleTimer = setTimeout(releaseVoice, 30_000)
              voiceIdleTimer.unref?.()
              return
            }
            selectedVoice().dispose()
            voiceIdleTimer = undefined
          }
          voiceIdleTimer = setTimeout(releaseVoice, 120_000)
          voiceIdleTimer.unref?.()
        }
      },
    }, logger)
    // Mirror every companion message to in-page subscribers without changing
    // what the helper receives; the wrap is per-runtime and dies with it.
    const deliver = bridge.send.bind(bridge)
    bridge.send = (message) => {
      deliver(message)
      eventStream.broadcast(message)
    }
    reducer = new CompanionReducer({ includeSubagents: resolved.includeSubagents === true })
    if (!diagnosticsLogged) {
      diagnosticsLogged = true
      diagnosticsLog.write(
        'INFO',
        `settings persistence (activation): namespace="${hostSettings.namespace ?? 'dsh-dafeilian'}"; update=${typeof hostSettings.update === 'function'}; native-menu fallback: ${JSON.stringify(overrides.snapshot())}`,
      )
    }
    bridge.start()
    if (resolved.voicePreload === true) preloadVoice()
    bridge.send(createMessage(CompanionMessageKind.HELLO, {
      state: CompanionState.IDLE,
      host: 'deepseek-harness',
      pluginVersion: pkg.version,
      message: 'BigFish connected to DSH',
    }))
    bridge.send(createMessage(CompanionMessageKind.STATE, {
      state: CompanionState.IDLE,
      phase: 'plugin-start',
      stage: '等待任务',
      message: resolved.idleTitle ?? defaults.idleTitle,
      detail: 'DSH · 等待下一次任务',
    }))
    if (balance.get().status !== 'disabled') bridge.send(createMessage(CompanionMessageKind.BALANCE, balance.get()))
    configureMarketWatch(resolved)
    logger.info?.('dsh-dafeilian companion bridge started')
  }

  startRuntime(settings.get())
  balance.configure(settings.get().enabled !== false && settings.get().balanceEnabled, settings.get().balanceSource)

  // The companion intentionally observes every DSH session. Loader entries may
  // live inside a scoped composition, so use the unscoped root bus and dispose
  // the registrations explicitly with this plugin's lifecycle.
  // Never let an exception from this optional companion escape into the shared
  // session bus: a throw here could stop every other subscriber from seeing
  // the event, which would look exactly like "installing the pet broke other
  // plugins".
  const offEvent = eventCtx.on('session/event', (session, event) => {
    if (!bridge || !reducer) return
    try {
      if (voiceCallActive && String(session?.header?.id ?? session?.id ?? '') === activeSessionId) {
        if (event?.type === 'turn/start') {
          lastSpokenReply = ''
          lastVisibleReply = ''
        }
        else if (event?.type === 'assistant/message') {
          const spoken = spokenReply(event)
          const visible = displayReply(event)
          if (spoken) lastSpokenReply = spoken
          if (visible) lastVisibleReply = visible
        } else if (event?.type === 'turn/end' && (lastVisibleReply || lastSpokenReply)) {
          if (lastVisibleReply) bridge.send(createMessage(CompanionMessageKind.CALL_MESSAGE, { text: lastVisibleReply }))
          if (lastSpokenReply) bridge.send(createMessage(CompanionMessageKind.SPEAK, { text: lastSpokenReply }))
          lastSpokenReply = ''
          lastVisibleReply = ''
        }
      }
      for (const message of reducer.handle(session, event)) bridge.send(message)
    } catch (error) {
      logger.error?.('dsh-dafeilian failed to handle session event', error)
    }
  }, { global: true })
  const offDisposed = eventCtx.on('session/disposed', (session) => {
    if (!bridge || !reducer) return
    try {
      for (const message of reducer.disposeSession(session)) bridge.send(message)
    } catch (error) {
      logger.error?.('dsh-dafeilian failed to dispose session', error)
    }
  }, { global: true })

  const unwatch = settings.watch((next) => {
    // Disabling is the only path that tears the helper down.  Every other
    // setting is applied live through a CONFIG message, so sliders never
    // restart the pet.  Starting a previously-disabled runtime is debounced
    // to avoid spawning repeatedly while settings settle.
    try {
      voice.configure(next)
      if (next.voiceEngine === 'dsh') voice.dispose()
      else dshVoice.dispose()
      if (next.voicePreload === true && next.enabled !== false && (next.voiceEngine === 'dsh' || !voice.child)) preloadVoice()
      balance.configure(next.enabled !== false && next.balanceEnabled, next.balanceSource)
      configureMarketWatch(next)
      if (next.enabled === false) {
        if (restartTimer) {
          clearTimeout(restartTimer)
          restartTimer = undefined
        }
        stopRuntime('settings-change')
        return
      }
      if (!bridge) {
        scheduleRestart(next)
        return
      }
      if (restartTimer) {
        clearTimeout(restartTimer)
        restartTimer = undefined
      }
      applyLiveSettings(next)
    } catch (error) {
      // This callback runs inside the host's settings dispatch; a throw here
      // would take the host's settings service down with the pet.
      logger.error?.(`dsh-dafeilian failed to apply settings: ${error instanceof Error ? error.message : String(error)}`)
    }
  })
  // A credential or account change invalidates the old display immediately.
  const refreshBalance = () => {
    const next = settings.get()
    balance.configure(next.enabled !== false && next.balanceEnabled, next.balanceSource, true)
  }
  const offCredential = eventCtx.on('credentials/reference-updated', refreshBalance, { global: true })
  const offAccount = eventCtx.on('deepseek-account/signed-out', refreshBalance, { global: true })
  const offAccountCredential = eventCtx.on('credentials/record-updated', refreshBalance, { global: true })
  const offProvider = eventCtx.on('settings/document-updated', (ns) => {
    if (['llm-deepseek', 'llm-deepseek-api-key', balanceProviderNamespace(ctx)].includes(ns)) refreshBalance()
  }, { global: true })
  if (typeof ctx.inject === 'function') {
    ctx.inject(['webServer'], (httpCtx) => {
      httpCtx.effect(
        () => httpCtx.webServer.register({ kind: 'exact', path: CONFIG_ENDPOINT, handler: createConfigHandler(settings) }),
        'dsh-dafeilian: local settings endpoint',
      )
      httpCtx.effect(
        () => httpCtx.webServer.register({ kind: 'exact', path: EVENTS_ENDPOINT, handler: createEventsHandler(eventStream) }),
        'dsh-dafeilian: local event stream',
      )
      httpCtx.effect(
        () => httpCtx.webServer.register({ kind: 'exact', path: BALANCE_ENDPOINT, handler: createBalanceHandler(balance) }),
        'dsh-dafeilian: local balance endpoint',
      )
      httpCtx.effect(
        () => httpCtx.webServer.register({ kind: 'exact', path: TASK_TARGET_ENDPOINT,
          handler: createTaskTargetHandler((sessionId) => {
            activeSessionId = sessionId
            diagnosticsLog.write('INFO', 'current conversation target selected')
          }) }),
        'dsh-dafeilian: current conversation target',
      )
      const assetRoutes = createAssetRoutes()
      if (assetRoutes) {
        httpCtx.effect(
          () => httpCtx.webServer.register({ kind: 'exact', path: MANIFEST_ENDPOINT, handler: assetRoutes.manifestHandler }),
          'dsh-dafeilian: local manifest endpoint',
        )
        httpCtx.effect(
          () => httpCtx.webServer.register({ kind: 'exact', path: FRAME_ENDPOINT, handler: assetRoutes.frameHandler }),
          'dsh-dafeilian: local frame endpoint',
        )
        httpCtx.effect(
          () => httpCtx.webServer.register({ kind: 'exact', path: SOUND_ENDPOINT, handler: assetRoutes.soundHandler }),
          'dsh-dafeilian: local sound preview endpoint',
        )
        httpCtx.effect(
          () => httpCtx.webServer.register({ kind: 'exact', path: CUSTOM_SOUND_ENDPOINT,
            handler: createCustomSoundsHandler({ onChange() {
              if (bridge) bridge.send(createMessage(CompanionMessageKind.CONFIG, { customSoundRevision: ++customSoundRevision }))
            } }) }),
          'dsh-dafeilian: local custom sound upload endpoint',
        )
      }
    })
  }
  ctx.effect(() => () => {
    if (restartTimer) clearTimeout(restartTimer)
    restartTimer = undefined
    offEvent?.()
    offDisposed?.()
    offCredential?.()
    offAccount?.()
    offAccountCredential?.()
    offProvider?.()
    unwatch()
    settings.dispose?.()
    balance.stop()
    marketWatch.dispose()
    stopRuntime('dsh-host-stop')
  })
}

export function apply(ctx, config = {}) {
  // Settings is already a declared dependency. Keep observers on this fiber
  // so Loader's fiber-scoped volatile updates reach them.
  mount(ctx, config)
}

export {
  CompanionMessageKind,
  CompanionReducer,
  CompanionState,
  HelperProcess,
}
