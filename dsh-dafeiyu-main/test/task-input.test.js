import assert from 'node:assert/strict'
import test from 'node:test'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { createTaskTargetHandler, submitDesktopTask } from '../src/task-input.js'

function exchange(body, overrides = {}) {
  let status
  let payload
  const req = {
    method: 'POST',
    socket: { remoteAddress: '127.0.0.1' },
    headers: { host: '127.0.0.1:3080', origin: 'http://127.0.0.1:3080' },
    async *[Symbol.asyncIterator]() { yield Buffer.from(JSON.stringify(body)) },
    ...overrides,
  }
  const res = {
    writeHead(next) { status = next },
    end(next) { payload = JSON.parse(next) },
  }
  return { req, res, result: () => ({ status, payload }) }
}

test('current conversation endpoint accepts only a local valid session', async () => {
  let selected
  const handler = createTaskTargetHandler((id) => { selected = id })
  const valid = exchange({ sessionId: 'current-session' })
  await handler(valid.req, valid.res)
  assert.deepEqual(valid.result(), { status: 200, payload: { ok: true } })
  assert.equal(selected, 'current-session')

  const remote = exchange({ sessionId: 'other' }, { socket: { remoteAddress: '203.0.113.7' } })
  await handler(remote.req, remote.res)
  assert.equal(remote.result().status, 403)
  assert.equal(selected, 'current-session')

  const invalid = exchange({ sessionId: '' })
  await handler(invalid.req, invalid.res)
  assert.equal(invalid.result().status, 400)
  assert.equal(selected, 'current-session')
})

test('desktop task is queued into the selected DSH conversation', async () => {
  let submitted
  const controller = {
    async prompt(request, signal) {
      submitted = { request, signal }
      return { accepted: true }
    },
  }
  const result = await submitDesktopTask(
    { requestId: 'task-1', text: '  修改登录页  ' },
    { sessionId: 'current-session', controller },
  )
  assert.deepEqual(result, { accepted: true })
  assert.deepEqual(submitted.request, {
    requestId: 'task-1', sessionId: 'current-session', mode: 'queue',
    content: [{ type: 'text', text: '修改登录页' }],
  })
  assert.equal(submitted.signal.aborted, false)
})

test('desktop task rejects missing target and keeps failed text available for retry', async () => {
  let called = 0
  const controller = { async prompt() { called += 1; throw new Error('session unavailable') } }
  assert.deepEqual(await submitDesktopTask({ requestId: 'task-1', text: 'hello' }, { controller }), {
    accepted: false, error: '请先打开要接收任务的 DSH 对话',
  })
  assert.equal(called, 0)
  assert.deepEqual(await submitDesktopTask({ requestId: 'task-1', text: 'hello' }, { sessionId: 'current', controller }), {
    accepted: false, error: 'session unavailable',
  })
  assert.equal(called, 1)
})

test('desktop task uploads files into the same conversation before queueing', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'dsh-pet-attachments-'))
  try {
    const document = join(directory, '说明.txt')
    const image = join(directory, 'picture.png')
    await writeFile(document, 'file contents')
    await writeFile(image, Buffer.from([137, 80, 78, 71]))
    const uploads = []
    let submitted
    const fileUploads = {
      async uploadStream({ sessionId, data, name }) {
        let bytes = 0
        for await (const chunk of data) bytes += chunk.length
        uploads.push({ sessionId, name, bytes, kind: 'file' })
        return { receiptId: 'document-receipt' }
      },
      async uploadImageStream({ sessionId, data, name, mediaType }) {
        let bytes = 0
        for await (const chunk of data) bytes += chunk.length
        uploads.push({ sessionId, name, bytes, kind: mediaType })
        return { receiptId: 'image-receipt' }
      },
    }
    const controller = { async prompt(request) { submitted = request; return { accepted: true } } }
    assert.deepEqual(await submitDesktopTask(
      { requestId: 'task-files', text: '', files: [document, image] },
      { sessionId: 'current-session', controller, fileUploads },
    ), { accepted: true })
    assert.deepEqual(uploads, [
      { sessionId: 'current-session', name: '说明.txt', bytes: 13, kind: 'file' },
      { sessionId: 'current-session', name: 'picture.png', bytes: 4, kind: 'image/png' },
    ])
    assert.deepEqual(submitted.content, [
      { type: 'file', receiptId: 'document-receipt' },
      { type: 'file', receiptId: 'image-receipt' },
    ])
  } finally {
    await rm(directory, { recursive: true, force: true })
  }
})

test('file task fails without upload service and does not submit a text-only message', async () => {
  let called = false
  const controller = { async prompt() { called = true } }
  const result = await submitDesktopTask(
    { requestId: 'task-files', text: '阅读附件', files: ['C:\\notes.txt'] },
    { sessionId: 'current-session', controller },
  )
  assert.equal(result.accepted, false)
  assert.match(result.error, /文件上传接口/u)
  assert.equal(called, false)
})
