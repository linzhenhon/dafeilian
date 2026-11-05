export const DEFAULT_MARKET_SYMBOLS = Object.freeze(['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'DOGEUSDT'])
export const MARKET_INTERVALS = Object.freeze(['1m', '15m', '1h', '4h'])

export function normalizeMarketSymbols(value) {
  const parts = Array.isArray(value) ? value : String(value ?? '').split(',')
  const symbols = [...new Set(parts.map((part) => String(part).trim().toUpperCase())
    .filter((part) => /^[A-Z0-9]{5,20}$/.test(part)))].slice(0, 5)
  return symbols.length ? symbols : [...DEFAULT_MARKET_SYMBOLS]
}

export function normalizeMarketInterval(value) {
  return MARKET_INTERVALS.includes(value) ? value : '15m'
}

export function normalizeMarketSymbol(value, symbols = DEFAULT_MARKET_SYMBOLS) {
  const normalized = String(value ?? '').trim().toUpperCase()
  return symbols.includes(normalized) ? normalized : symbols[0] ?? DEFAULT_MARKET_SYMBOLS[0]
}

export function parseBinanceKlineMessage(value) {
  const packet = value?.data ?? value
  const kline = packet?.k
  const symbol = String(kline?.s ?? packet?.s ?? '').toUpperCase()
  const open = Number(kline?.o)
  const price = Number(kline?.c)
  if (!symbol || !Number.isFinite(open) || open <= 0 || !Number.isFinite(price) || price <= 0) return undefined
  return {
    symbol,
    open,
    price,
    changePercent: Number((((price / open) - 1) * 100).toFixed(8)),
    closed: kline?.x === true,
    updatedAt: Number(packet?.E) || Date.now(),
  }
}

function messageText(data) {
  if (typeof data === 'string') return Promise.resolve(data)
  if (typeof Buffer !== 'undefined' && Buffer.isBuffer(data)) return Promise.resolve(data.toString('utf8'))
  if (data instanceof ArrayBuffer) return Promise.resolve(new TextDecoder().decode(data))
  if (ArrayBuffer.isView(data)) return Promise.resolve(new TextDecoder().decode(data))
  if (data && typeof data.text === 'function') return data.text()
  return Promise.resolve(String(data ?? ''))
}

export function createMarketWatchMonitor({
  WebSocketImpl = globalThis.WebSocket,
  onUpdate = () => {},
  logger = console,
  reconnectBaseMs = 2000,
  reconnectMaxMs = 30000,
} = {}) {
  let config = { enabled: false, symbols: [...DEFAULT_MARKET_SYMBOLS], interval: '15m', selectedSymbol: DEFAULT_MARKET_SYMBOLS[0] }
  let signature = ''
  let socket
  let reconnectTimer
  let generation = 0
  let reconnectDelay = reconnectBaseMs
  const quotes = new Map()

  const snapshot = (status) => ({
    enabled: config.enabled,
    status,
    symbols: [...config.symbols],
    interval: config.interval,
    selectedSymbol: config.selectedSymbol,
    quotes: [...quotes.values()],
  })
  const publish = (status) => {
    try { onUpdate(snapshot(status)) } catch (error) { logger.warn?.(`market watch update failed: ${error instanceof Error ? error.message : String(error)}`) }
  }
  const disconnect = () => {
    generation += 1
    if (reconnectTimer) clearTimeout(reconnectTimer)
    reconnectTimer = undefined
    const active = socket
    socket = undefined
    if (active) {
      try { active.close() } catch {}
    }
  }
  const scheduleReconnect = (token) => {
    if (!config.enabled || token !== generation || reconnectTimer) return
    const delay = reconnectDelay
    reconnectDelay = Math.min(reconnectMaxMs, Math.max(reconnectBaseMs, reconnectDelay * 2))
    publish('reconnecting')
    reconnectTimer = setTimeout(() => {
      reconnectTimer = undefined
      if (config.enabled && token === generation) connect(token)
    }, delay)
    reconnectTimer.unref?.()
  }
  const connect = (token) => {
    if (!config.enabled || token !== generation) return
    if (typeof WebSocketImpl !== 'function') {
      publish('unavailable')
      logger.warn?.('market watch requires a WebSocket implementation')
      return
    }
    const streams = config.symbols.map((symbol) => `${symbol.toLowerCase()}@kline_${config.interval}`).join('/')
    const url = `wss://stream.binance.com:9443/stream?streams=${streams}`
    publish('connecting')
    let next
    try { next = new WebSocketImpl(url) } catch (error) {
      logger.warn?.(`market watch connection failed: ${error instanceof Error ? error.message : String(error)}`)
      scheduleReconnect(token)
      return
    }
    socket = next
    next.addEventListener('open', () => {
      if (token !== generation) return
      reconnectDelay = reconnectBaseMs
      publish('connected')
    })
    next.addEventListener('message', (event) => {
      if (token !== generation) return
      void messageText(event?.data).then((text) => {
        if (token !== generation) return
        let packet
        try { packet = JSON.parse(text) } catch { return }
        const quote = parseBinanceKlineMessage(packet)
        if (!quote || !config.symbols.includes(quote.symbol)) return
        quotes.set(quote.symbol, { ...quote, interval: config.interval })
        publish('connected')
      }).catch((error) => logger.warn?.(`market watch message failed: ${error instanceof Error ? error.message : String(error)}`))
    })
    next.addEventListener('error', () => {
      if (token === generation) {
        try { next.close() } catch {}
      }
    })
    next.addEventListener('close', () => {
      if (token !== generation) return
      socket = undefined
      scheduleReconnect(token)
    })
  }

  return {
    configure(options = {}) {
      const symbols = normalizeMarketSymbols(options.symbols)
      const interval = normalizeMarketInterval(options.interval)
      const selectedSymbol = normalizeMarketSymbol(options.selectedSymbol, symbols)
      const enabled = options.enabled === true
      const nextSignature = JSON.stringify({ enabled, symbols, interval })
      config = { enabled, symbols, interval, selectedSymbol }
      if (nextSignature === signature) {
        publish(enabled ? (socket ? 'connected' : 'connecting') : 'disabled')
        return
      }
      signature = nextSignature
      disconnect()
      quotes.clear()
      reconnectDelay = reconnectBaseMs
      const token = generation
      if (!enabled) {
        publish('disabled')
        return
      }
      connect(token)
    },
    stop() {
      config = { ...config, enabled: false }
      signature = JSON.stringify({ enabled: false, symbols: config.symbols, interval: config.interval })
      disconnect()
      quotes.clear()
    },
    dispose() {
      this.stop()
    },
  }
}
