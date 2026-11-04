import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { runInNewContext } from 'node:vm'
import test from 'node:test'

test('client exposes its own bundle configuration and preserves older settings entries', async () => {
  const source = await readFile(new URL('../lib/client.js', import.meta.url), 'utf8')

  let capturedOptions
  const registrations = []
  const ctx = {
    slots: {
      inject(name, register) {
        assert.ok(['plugins.bundle.config', 'settings.plugins.tab', 'settings.plugin.item', 'conversation.composer.dock'].includes(name))
        register()
      },
      register(options, component) {
        capturedOptions = options
        registrations.push({ ...options, component })
        return {}
      },
    },
  }

  const React = {
    createElement(type, props, ...children) { return { type, props, children } },
    useEffect() {},
    useRef(initial) { return { current: initial } },
    useState(initial) { return [initial, () => {}] },
  }

  let client
  const sandbox = {
    window: {
      __ModuleLoader__: {
        load({ factory }) {
          client = factory((id) => {
            if (id === 'react') return React
            throw new Error(`unexpected require: ${id}`)
          })
        },
      },
    },
    console,
  }

  runInNewContext(source, sandbox)
  client.apply(ctx)

  assert.ok(capturedOptions, 'expected current conversation reporter registration')
  assert.equal(registrations[2].name, 'settings.plugin.item')
  assert.equal(registrations[2].key, 'dsh-dafeilian')
  assert.equal(registrations[2].id, 'dsh-dafeilian')
  assert.equal(registrations[0].name, 'plugins.bundle.config')
  assert.equal(registrations[0].key, 'dsh-dafeilian')
  const page = registrations[0].component({ view: 'page' })
  assert.equal(page.type, 'section')
  assert.equal(page.props['data-testid'], 'dsh-dafeilian-settings')
  assert.equal(registrations[2].component().type, 'li')
  assert.equal(registrations[1].name, 'settings.plugins.tab')
  assert.equal(registrations[1].label(), '大肥鱼')
  assert.equal(registrations[3].name, 'conversation.composer.dock')
})

test('client apply does not throw when the slot contract changes or fails', async () => {
  const source = await readFile(new URL('../lib/client.js', import.meta.url), 'utf8')

  const React = {
    createElement() {},
    useEffect() {},
    useRef() { return { current: undefined } },
    useState() { return [] },
  }

  let client
  const sandbox = {
    window: {
      __ModuleLoader__: {
        load({ factory }) {
          client = factory((id) => {
            if (id === 'react') return React
            throw new Error(`unexpected require: ${id}`)
          })
        },
      },
    },
    console: { error() {} },
  }

  runInNewContext(source, sandbox)

  // DSH may invoke the inject callback asynchronously, so a throw must be
  // contained inside that callback too. A broken card must degrade to "missing",
  // never fail the whole WebUI load.
  let registerAttempted = 0
  let injectAttempted = 0
  const deferred = []
  const ctx = {
    slots: {
      inject(name, register) {
        injectAttempted += 1
        assert.ok(['plugins.bundle.config', 'settings.plugins.tab', 'settings.plugin.item', 'conversation.composer.dock'].includes(name))
        deferred.push(register)
      },
      register() {
        registerAttempted += 1
        throw new Error('keyed slot settings.plugin.item requires options.key')
      },
    },
  }

  assert.doesNotThrow(() => client.apply(ctx))
  assert.equal(injectAttempted, 4)
  assert.equal(registerAttempted, 0)
  for (const register of deferred) assert.doesNotThrow(register)
  assert.equal(registerAttempted, 4)
})

test('client apply also contains a synchronous inject failure', async () => {
  const source = await readFile(new URL('../lib/client.js', import.meta.url), 'utf8')

  const React = {
    createElement() {},
    useEffect() {},
    useRef() { return { current: undefined } },
    useState() { return [] },
  }

  let client
  const sandbox = {
    window: {
      __ModuleLoader__: {
        load({ factory }) {
          client = factory((id) => {
            if (id === 'react') return React
            throw new Error(`unexpected require: ${id}`)
          })
        },
      },
    },
    console: { error() {} },
  }
  runInNewContext(source, sandbox)

  let registerAttempted = 0
  const ctx = {
    slots: {
      inject() { throw new Error('slots service contract changed') },
      register() { registerAttempted += 1 },
    },
  }

  assert.doesNotThrow(() => client.apply(ctx))
  assert.equal(registerAttempted, 0)
})

test('client reports the selected conversation to the native pet bridge', async () => {
  const source = await readFile(new URL('../lib/client.js', import.meta.url), 'utf8')
  let client
  let reporter
  let runEffect
  const requests = []
  const sandbox = {
    window: {
      addEventListener() {}, removeEventListener() {},
      __ModuleLoader__: { load({ factory }) {
        client = factory((id) => {
          if (id === 'react') return {
            createElement() {}, useEffect(effect) { runEffect = effect },
            useRef() { return { current: undefined } }, useState() { return [] },
          }
          throw new Error(`unexpected require: ${id}`)
        })
      } },
    },
    console,
    fetch(url, options) {
      requests.push({ url, options })
      return Promise.resolve({ ok: false })
    },
  }
  runInNewContext(source, sandbox)
  client.apply({ slots: {
    inject(name, register) { register() },
    register(options, component) {
      if (options.name === 'conversation.composer.dock') reporter = component
    },
  } })
  assert.equal(typeof reporter, 'function')
  reporter({ sessionId: 'selected-session' })
  runEffect()
  const report = requests.find((request) => request.url.endsWith('/task-target'))
  assert.equal(report.options.method, 'POST')
  assert.equal(JSON.parse(report.options.body).sessionId, 'selected-session')
})
