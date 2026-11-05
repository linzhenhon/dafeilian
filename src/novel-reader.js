import { randomUUID } from 'node:crypto'
import { mkdirSync, readFileSync, renameSync, statSync, unlinkSync, writeFileSync } from 'node:fs'
import { dirname, extname, join } from 'node:path'
import { defaultUserSettingsPath } from './user-settings.js'
import { isLocalRequest, jsonResponse } from './local-http.js'

export const NOVEL_ENDPOINT = '/plugins/dsh-dafeiyu/novel'
export const MAX_NOVEL_BYTES = 10 * 1024 * 1024

export function decodeNovel(bytes) {
  if (!bytes.length || bytes.length > MAX_NOVEL_BYTES) throw new Error('请选择 10 MB 以内的 TXT 小说')
  let text
  try {
    const encoding = bytes[0] === 0xff && bytes[1] === 0xfe ? 'utf-16le'
      : bytes[0] === 0xfe && bytes[1] === 0xff ? 'utf-16be' : 'utf-8'
    text = new TextDecoder(encoding, { fatal: true }).decode(bytes)
  } catch {
    try { text = new TextDecoder('gb18030', { fatal: true }).decode(bytes) }
    catch { throw new Error('无法识别文本编码，请另存为 UTF-8 TXT 后导入') }
  }
  text = text.replace(/^\uFEFF/u, '').replace(/\r\n?/gu, '\n').trim()
  if (!text || /[\x00-\x08\x0b\x0c\x0e-\x1f]/u.test(text)) throw new Error('文件不是有效的 TXT 小说')
  if (Buffer.byteLength(text, 'utf8') > MAX_NOVEL_BYTES) throw new Error('小说转换为 UTF-8 后不得超过 10 MB')
  return text
}

export function paginateNovel(text, pageSize = 360) {
  const pages = []
  for (let start = 0; start < text.length;) {
    let end = Math.min(start + pageSize, text.length)
    if (end < text.length) {
      const newline = text.lastIndexOf('\n', end - 1)
      if (newline > start + pageSize / 2) end = newline + 1
      else if (/[\uD800-\uDBFF]/u.test(text[end - 1])) end -= 1
    }
    pages.push(text.slice(start, end))
    start = end
  }
  return pages
}

export function createNovelReader({
  directory = join(dirname(defaultUserSettingsPath()), 'novel-reader'),
  onChange = () => {},
} = {}) {
  const stateFile = join(directory, 'reading.json')
  let state = { enabled: true, autoTurn: false, secondsPerPage: 20, page: 0 }
  let pages = []
  try {
    const saved = JSON.parse(readFileSync(stateFile, 'utf8'))
    state = { ...state,
      enabled: saved.enabled !== false, autoTurn: saved.autoTurn === true,
      secondsPerPage: [10, 20, 30, 60].includes(saved.secondsPerPage) ? saved.secondsPerPage : 20 }
    if (!/^[\da-f-]{36}$/u.test(saved.id)) throw new Error('invalid book id')
    const bookFile = join(directory, `${saved.id}.txt`)
    if (statSync(bookFile).size > MAX_NOVEL_BYTES) throw new Error('book too large')
    pages = paginateNovel(decodeNovel(readFileSync(bookFile)))
    state = { ...state, id: saved.id, title: String(saved.title).slice(0, 100),
      page: Number.isSafeInteger(saved.page) ? Math.max(0, Math.min(pages.length - 1, saved.page)) : 0 }
  } catch { /* First launch or missing book: offer import without inventing content. */ }

  const snapshot = () => ({ ...state, hasBook: pages.length > 0, totalPages: pages.length, content: pages[state.page] ?? '' })
  const save = (next) => {
    mkdirSync(directory, { recursive: true })
    const temporary = `${stateFile}.${randomUUID()}.tmp`
    try {
      writeFileSync(temporary, `${JSON.stringify(next)}\n`, { flag: 'wx', encoding: 'utf8' })
      renameSync(temporary, stateFile)
    } finally {
      try { unlinkSync(temporary) } catch { /* Successfully renamed or not created. */ }
    }
    state = next
  }
  const publish = () => { try { onChange(snapshot()) } catch { /* A UI disconnect must not lose progress. */ } }
  const importBook = (name, bytes) => {
    if (typeof name !== 'string' || extname(name).toLowerCase() !== '.txt') throw new Error('请选择 TXT 小说文件')
    const text = decodeNovel(bytes)
    const nextPages = paginateNovel(text)
    const id = randomUUID()
    const title = name.split(/[\\/]/u).pop().replace(/\.txt$/iu, '').replace(/[\x00-\x1f]/gu, '').slice(0, 100) || '未命名小说'
    const oldId = state.id
    mkdirSync(directory, { recursive: true })
    const file = join(directory, `${id}.txt`)
    writeFileSync(file, text, { flag: 'wx', encoding: 'utf8' })
    try { save({ ...state, id, title, page: 0, enabled: true }) }
    catch (error) { try { unlinkSync(file) } catch {} throw error }
    pages = nextPages
    if (oldId) { try { unlinkSync(join(directory, `${oldId}.txt`)) } catch {} }
    publish()
    return snapshot()
  }

  return {
    get: snapshot,
    importBook,
    importFile(path) {
      if (typeof path !== 'string' || extname(path).toLowerCase() !== '.txt') throw new Error('请选择 TXT 小说文件')
      const stat = statSync(path)
      if (!stat.isFile() || stat.size > MAX_NOVEL_BYTES) throw new Error('请选择 10 MB 以内的 TXT 小说')
      return importBook(path, readFileSync(path))
    },
    update(patch) {
      if (!patch || typeof patch !== 'object' || Array.isArray(patch)
        || Object.keys(patch).some(key => !['id', 'enabled', 'autoTurn', 'secondsPerPage', 'page'].includes(key))) throw new Error('阅读设置无效')
      if (patch.id !== undefined && patch.id !== state.id) throw new Error('小说已更换，请刷新后再翻页')
      const next = { ...state }
      for (const key of ['enabled', 'autoTurn']) {
        if (!(key in patch)) continue
        if (typeof patch[key] !== 'boolean') throw new Error('阅读开关无效')
        next[key] = patch[key]
      }
      if ('secondsPerPage' in patch) {
        if (![10, 20, 30, 60].includes(patch.secondsPerPage)) throw new Error('请选择有效的翻页速度')
        next.secondsPerPage = patch.secondsPerPage
      }
      if ('page' in patch) {
        if (!Number.isSafeInteger(patch.page) || patch.page < 0 || patch.page >= pages.length) throw new Error('阅读页码无效')
        next.page = patch.page
      }
      save(next)
      publish()
      return snapshot()
    },
  }
}

export function createNovelHandler(reader) {
  return async (req, res) => {
    if (!isLocalRequest(req)) return jsonResponse(res, 403, { error: 'local access only' })
    if (req.method === 'GET') return jsonResponse(res, 200, reader.get())
    if (!['POST', 'PATCH'].includes(req.method)) return jsonResponse(res, 405, { error: 'method not allowed' })
    try {
      const chunks = []
      let length = 0
      for await (const chunk of req) {
        length += chunk.length
        if (length > (req.method === 'POST' ? MAX_NOVEL_BYTES : 2048)) return jsonResponse(res, 413, { error: '文件过大，请选择 10 MB 以内的 TXT 小说' })
        chunks.push(chunk)
      }
      const bytes = Buffer.concat(chunks)
      const next = req.method === 'POST'
        ? reader.importBook(new URL(req.url, 'http://localhost').searchParams.get('name'), bytes)
        : reader.update(JSON.parse(bytes.toString('utf8')))
      return jsonResponse(res, 200, next)
    } catch (error) {
      return jsonResponse(res, 400, { error: error instanceof Error ? error.message : '小说处理失败' })
    }
  }
}
