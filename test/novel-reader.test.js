import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync, readdirSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'
import { createNovelReader, createNovelHandler, decodeNovel, paginateNovel, MAX_NOVEL_BYTES } from '../src/novel-reader.js'

test('novels keep user text, page boundaries, settings and progress after restart', t => {
  const directory = mkdtempSync(join(tmpdir(), 'dsh-novel-'))
  t.after(() => rmSync(directory, { recursive: true, force: true }))
  let changed
  const reader = createNovelReader({ directory, onChange: value => { changed = value } })
  reader.update({ enabled: false, autoTurn: true, secondsPerPage: 30 })
  assert.equal(createNovelReader({ directory }).get().enabled, false)
  const text = ('第一章 开始\n' + '自己的小说内容🐞。\n'.repeat(140)).trim()
  const imported = reader.importBook('我的小说.txt', Buffer.from(text))
  assert.equal(imported.enabled, true)
  assert.equal(imported.title, '我的小说')
  assert.equal(imported.autoTurn, true)
  assert.equal(paginateNovel(text).join(''), text)
  for (const page of paginateNovel(text)) assert.doesNotMatch(page, /[\uD800-\uDBFF]$/u)
  reader.update({ id: imported.id, page: 2, secondsPerPage: 60 })
  const restored = createNovelReader({ directory }).get()
  assert.equal(restored.page, 2)
  assert.equal(restored.content, paginateNovel(text)[2])
  assert.equal(restored.secondsPerPage, 60)
  assert.deepEqual(changed, restored)
  assert.equal(readFileSync(join(directory, `${imported.id}.txt`), 'utf8'), text)
  assert.throws(() => reader.update({ page: -1 }))
  assert.throws(() => reader.update({ page: restored.totalPages }))
  assert.throws(() => reader.update({ secondsPerPage: 0 }))
  assert.throws(() => reader.update({ enabled: 'true' }))
  assert.throws(() => reader.importBook('bad.pdf', Buffer.from('bad')))
  assert.throws(() => reader.importBook('empty.txt', Buffer.from(' \n')))
  assert.equal(reader.get().id, imported.id, 'failed imports must preserve the existing book')
  const replaced = reader.importBook('第二本.txt', Buffer.from('第二本内容'))
  assert.equal(replaced.page, 0)
  assert.throws(() => reader.update({ id: imported.id, page: 0 }))
  assert.deepEqual(readdirSync(directory).sort(), [`${replaced.id}.txt`, 'reading.json'].sort())
})

test('TXT imports support Chinese encodings and reject binary or oversized files', () => {
  assert.equal(decodeNovel(Buffer.from([0xd6, 0xd0, 0xce, 0xc4])), '中文')
  assert.equal(decodeNovel(Buffer.from('\ufeff中文\r\n内容', 'utf16le')), '中文\n内容')
  assert.throws(() => decodeNovel(Buffer.from('binary\0data')))
  assert.throws(() => decodeNovel(Buffer.alloc(MAX_NOVEL_BYTES + 1)))
})

test('HTTP novel import stays local, enforces size and preserves content as plain text', async t => {
  const directory = mkdtempSync(join(tmpdir(), 'dsh-novel-http-'))
  t.after(() => rmSync(directory, { recursive: true, force: true }))
  const handler = createNovelHandler(createNovelReader({ directory }))
  const call = async (method, body = '', overrides = {}) => {
    const request = { method, url: '/plugins/dsh-dafeiyu/novel?name=novel.txt',
      socket: { remoteAddress: '127.0.0.1' }, headers: { host: 'localhost:3080', origin: 'http://localhost:3080' },
      async *[Symbol.asyncIterator]() { yield Buffer.isBuffer(body) ? body : Buffer.from(body) }, ...overrides }
    const response = { writeHead(status) { this.status = status }, end(body) { this.body = JSON.parse(body) } }
    await handler(request, response)
    return response
  }
  assert.equal((await call('POST', 'text', { socket: { remoteAddress: '8.8.8.8' } })).status, 403)
  assert.equal((await call('POST', 'text', { headers: { host: 'localhost:3080', origin: 'https://evil.example' } })).status, 403)
  assert.equal((await call('POST', Buffer.alloc(MAX_NOVEL_BYTES + 1))).status, 413)
  assert.equal((await call('PATCH', 'null')).status, 400)
  const imported = await call('POST', '<script>user supplied plain text</script>')
  assert.equal(imported.status, 200)
  assert.equal(imported.body.content, '<script>user supplied plain text</script>')
  assert.equal((await call('PATCH', '{"enabled":false}')).body.enabled, false)
  assert.equal((await call('GET')).body.enabled, false)
})
