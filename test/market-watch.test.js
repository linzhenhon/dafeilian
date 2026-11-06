import test from 'node:test'
import assert from 'node:assert/strict'
import {
  DEFAULT_MARKET_SYMBOLS,
  createMarketWatchMonitor,
  normalizeMarketInterval,
  normalizeMarketSymbol,
  normalizeMarketSymbols,
  parseBinanceKlineMessage,
} from '../src/market-watch.js'

test('market watch normalizes the five-symbol limit, selection, and timeframe', () => {
  assert.deepEqual(normalizeMarketSymbols(' btcusdt,ETHUSDT,btcusdt, SOLUSDT,BNBUSDT,DOGEUSDT,XRPUSDT '), [
    'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'DOGEUSDT',
  ])
  assert.deepEqual(normalizeMarketSymbols('??'), [...DEFAULT_MARKET_SYMBOLS])
  assert.equal(normalizeMarketSymbol('solusdt', ['BTCUSDT', 'SOLUSDT']), 'SOLUSDT')
  assert.equal(normalizeMarketSymbol('XRPUSDT', ['BTCUSDT']), 'BTCUSDT')
  assert.equal(normalizeMarketInterval('4h'), '4h')
  assert.equal(normalizeMarketInterval('5m'), '15m')
})

test('Binance kline updates report the selected candle movement', () => {
  assert.deepEqual(parseBinanceKlineMessage({
    stream: 'btcusdt@kline_15m',
    data: { E: 1700000000000, k: { s: 'BTCUSDT', o: '100', c: '101.25', x: false } },
  }), {
    symbol: 'BTCUSDT', open: 100, price: 101.25, changePercent: 1.25, closed: false, updatedAt: 1700000000000,
  })
  assert.equal(parseBinanceKlineMessage({ data: { k: { s: 'BTCUSDT', o: '0', c: '1' } } }), undefined)
})

test('market watch subscribes to five public streams and publishes quotes without credentials', async () => {
  class FakeWebSocket {
    static instances = []

    constructor(url) {
      this.url = url
      this.listeners = new Map()
      this.closed = false
      FakeWebSocket.instances.push(this)
    }

    addEventListener(name, listener) {
      const listeners = this.listeners.get(name) ?? []
      listeners.push(listener)
      this.listeners.set(name, listeners)
    }

    emit(name, event = {}) {
      for (const listener of this.listeners.get(name) ?? []) listener(event)
    }

    close() {
      this.closed = true
    }
  }

  const updates = []
  const monitor = createMarketWatchMonitor({ WebSocketImpl: FakeWebSocket, onUpdate: (snapshot) => updates.push(snapshot) })
  monitor.configure({ enabled: true, symbols: DEFAULT_MARKET_SYMBOLS, selectedSymbol: 'BTCUSDT', interval: '15m' })
  const socket = FakeWebSocket.instances[0]
  assert.match(socket.url, /^wss:\/\/stream\.binance\.com:9443\/stream\?streams=/)
  for (const symbol of DEFAULT_MARKET_SYMBOLS) assert.ok(socket.url.includes(`${symbol.toLowerCase()}@kline_15m`))
  assert.equal(updates.at(-1).enabled, true)
  socket.emit('open')
  socket.emit('message', { data: JSON.stringify({ data: { E: 1234, k: { s: 'BTCUSDT', o: '10', c: '11', x: false } } }) })
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(updates.at(-1).status, 'connected')
  assert.equal(updates.at(-1).quotes[0].changePercent, 10)
  assert.equal(updates.at(-1).quotes[0].interval, '15m')

  monitor.configure({ enabled: true, symbols: DEFAULT_MARKET_SYMBOLS, selectedSymbol: 'ETHUSDT', interval: '15m' })
  assert.equal(FakeWebSocket.instances.length, 1)
  assert.equal(updates.at(-1).selectedSymbol, 'ETHUSDT')
  monitor.stop()
  assert.equal(socket.closed, true)
  monitor.dispose()
})

test('market watch rotates Binance endpoints after a stalled or closed connection', async () => {
  class FakeWebSocket {
    static instances = []

    constructor(url) {
      this.url = url
      this.listeners = new Map()
      this.closed = false
      FakeWebSocket.instances.push(this)
    }

    addEventListener(name, listener) {
      const listeners = this.listeners.get(name) ?? []
      listeners.push(listener)
      this.listeners.set(name, listeners)
    }

    emit(name, event = {}) {
      for (const listener of this.listeners.get(name) ?? []) listener(event)
    }

    close() {
      this.closed = true
      this.emit('close')
    }
  }

  const waitForSockets = async (count) => {
    const deadline = Date.now() + 1000
    while (FakeWebSocket.instances.length < count && Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 2))
    }
    assert.ok(FakeWebSocket.instances.length >= count, `expected ${count} WebSocket connections`)
  }

  const updates = []
  const monitor = createMarketWatchMonitor({
    WebSocketImpl: FakeWebSocket,
    onUpdate: (snapshot) => updates.push(snapshot),
    reconnectBaseMs: 1,
    reconnectMaxMs: 1,
    connectTimeoutMs: 15,
  })
  monitor.configure({ enabled: true, symbols: ['BTCUSDT'], selectedSymbol: 'BTCUSDT', interval: '15m' })
  assert.match(FakeWebSocket.instances[0].url, /^wss:\/\/stream\.binance\.com:9443\//)

  await waitForSockets(2)
  assert.match(FakeWebSocket.instances[1].url, /^wss:\/\/stream\.binance\.com:443\//)
  assert.ok(updates.some((snapshot) => snapshot.status === 'reconnecting' && snapshot.endpoint === 'stream.binance.com:443'))

  FakeWebSocket.instances[1].emit('open')
  FakeWebSocket.instances[1].emit('close')
  await waitForSockets(3)
  assert.match(FakeWebSocket.instances[2].url, /^wss:\/\/data-stream\.binance\.vision:443\//)
  assert.ok(updates.some((snapshot) => snapshot.status === 'reconnecting' && snapshot.endpoint === 'data-stream.binance.vision'))

  monitor.stop()
})
