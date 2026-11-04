import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import test from 'node:test'
import { createAssetRoutes } from '../src/index.js'

function fakeRes() {
  return {
    statusCode: 0,
    headers: undefined,
    body: undefined,
    writeHead(status, headers) {
      this.statusCode = status
      this.headers = headers
    },
    end(payload) {
      this.body = payload
    },
  }
}

function fakeReq(url, address = '127.0.0.1') {
  const req = new EventEmitter()
  req.url = url
  req.socket = { remoteAddress: address }
  req.headers = { host: '127.0.0.1:3080' }
  return req
}

test('asset routes serve manifest-declared frames only', async () => {
  const routes = createAssetRoutes()
  assert.ok(routes, 'routes should load from the real package manifest')

  const ok = fakeRes()
  routes.frameHandler(fakeReq('/plugins/dsh-dafeiyu/frame?frame=custom/front.png'), ok)
  assert.equal(ok.statusCode, 200)
  assert.equal(ok.headers['content-type'], 'image/png')
  assert.ok(ok.body.length > 100)

  const unknown = fakeRes()
  routes.frameHandler(fakeReq('/plugins/dsh-dafeiyu/frame?frame=custom/nope.png'), unknown)
  assert.equal(unknown.statusCode, 404)

  const traversal = fakeRes()
  routes.frameHandler(fakeReq('/plugins/dsh-dafeiyu/frame?frame=../../package.json'), traversal)
  assert.equal(traversal.statusCode, 404, 'paths outside the manifest allowlist must never resolve')

  const missing = fakeRes()
  routes.frameHandler(fakeReq('/plugins/dsh-dafeiyu/frame'), missing)
  assert.equal(missing.statusCode, 404)
})

test('asset routes stay loopback-only and serve the manifest', () => {
  const routes = createAssetRoutes()

  const foreign = fakeRes()
  routes.frameHandler(fakeReq('/plugins/dsh-dafeiyu/frame?frame=custom/front.png', '203.0.113.7'), foreign)
  assert.equal(foreign.statusCode, 403)

  const manifest = fakeRes()
  routes.manifestHandler(fakeReq('/plugins/dsh-dafeiyu/manifest'), manifest)
  assert.equal(manifest.statusCode, 200)
  const value = JSON.parse(manifest.body)
  assert.equal(value.formatVersion, 1)
  assert.equal(value.characterId, 'dafeilian-insect')
  assert.ok(Object.keys(value.clips).length >= 15)
})

test('sound preview route serves all three packs and reminder voice lines', () => {
  const routes = createAssetRoutes()
  for (const pack of ['original', 'clean', 'video']) {
    for (const state of ['SUCCESS', 'ERROR', 'APPROVAL', 'SLEEP', 'ALARM', 'TODO']) {
      const response = fakeRes()
      routes.soundHandler(fakeReq(`/plugins/dsh-dafeiyu/sound?pack=${pack}&state=${state}`), response)
      assert.equal(response.statusCode, 200)
      assert.equal(response.headers['content-type'], 'audio/wav')
      assert.equal(response.headers['cross-origin-resource-policy'], 'same-origin')
      assert.equal(response.body.subarray(0, 4).toString('ascii'), 'RIFF')
    }
  }
  for (const query of ['pack=../../&state=SUCCESS', 'pack=clean&state=IDLE', 'state=ERROR']) {
    const response = fakeRes()
    routes.soundHandler(fakeReq(`/plugins/dsh-dafeiyu/sound?${query}`), response)
    assert.equal(response.statusCode, 404)
  }
  const remote = fakeRes()
  routes.soundHandler(fakeReq('/plugins/dsh-dafeiyu/sound?pack=clean&state=SUCCESS', '203.0.113.7'), remote)
  assert.equal(remote.statusCode, 403)
})
