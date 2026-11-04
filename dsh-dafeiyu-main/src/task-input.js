import { isLocalRequest, jsonResponse } from './local-http.js'
import { createReadStream } from 'node:fs'
import { stat } from 'node:fs/promises'
import { basename, extname, isAbsolute } from 'node:path'

export const TASK_TARGET_ENDPOINT = '/plugins/dsh-dafeiyu/task-target'
export const MAX_TASK_LENGTH = 4000
export const MAX_TASK_FILES = 8
const IMAGE_TYPES = new Map([['.png', 'image/png'], ['.jpg', 'image/jpeg'], ['.jpeg', 'image/jpeg'], ['.webp', 'image/webp']])

export function createTaskTargetHandler(setTarget) {
  return async (req, res) => {
    if (!isLocalRequest(req)) {
      jsonResponse(res, 403, { error: 'local access only' })
      return
    }
    if (req.method !== 'POST') {
      jsonResponse(res, 405, { error: 'method not allowed' })
      return
    }
    try {
      const chunks = []
      let bytes = 0
      for await (const chunk of req) {
        bytes += chunk.length
        if (bytes > 512) throw new Error('request body is too large')
        chunks.push(chunk)
      }
      const value = JSON.parse(Buffer.concat(chunks).toString('utf8'))
      const sessionId = value?.sessionId
      if (typeof sessionId !== 'string' || !sessionId.trim() || sessionId.length > 128) {
        throw new Error('sessionId must be a non-empty string of at most 128 characters')
      }
      setTarget(sessionId)
      jsonResponse(res, 200, { ok: true })
    } catch (error) {
      jsonResponse(res, 400, { error: error instanceof Error ? error.message : String(error) })
    }
  }
}

export async function submitDesktopTask({ requestId, text, files = [] }, { sessionId, controller, fileUploads }) {
  if (typeof requestId !== 'string' || !/^[\w-]{1,128}$/u.test(requestId)) {
    return { accepted: false, error: '任务编号无效，请重试' }
  }
  if (typeof text !== 'string' || text.length > MAX_TASK_LENGTH || (!text.trim() && (!Array.isArray(files) || files.length === 0))) {
    return { accepted: false, error: `请输入不超过 ${MAX_TASK_LENGTH} 字的任务` }
  }
  if (!Array.isArray(files) || files.length > MAX_TASK_FILES || files.some(path => typeof path !== 'string' || !isAbsolute(path) || path.length > 4096)) {
    return { accepted: false, error: `请最多选择 ${MAX_TASK_FILES} 个有效的本地文件` }
  }
  if (!sessionId) return { accepted: false, error: '请先打开要接收任务的 DSH 对话' }
  if (typeof controller?.prompt !== 'function') {
    return { accepted: false, error: '当前 DSH 版本没有提供任务提交接口' }
  }
  if (files.length && typeof fileUploads?.uploadStream !== 'function') {
    return { accepted: false, error: '当前 DSH 版本没有提供文件上传接口' }
  }
  try {
    const content = []
    for (const path of files) {
      const info = await stat(path)
      if (!info.isFile()) throw new Error(`不是普通文件：${basename(path)}`)
      const name = basename(path)
      const mediaType = IMAGE_TYPES.get(extname(path).toLowerCase())
      const upload = mediaType && typeof fileUploads.uploadImageStream === 'function'
        ? await fileUploads.uploadImageStream({ sessionId, data: createReadStream(path), name, mediaType })
        : await fileUploads.uploadStream({ sessionId, data: createReadStream(path), name })
      if (typeof upload?.receiptId !== 'string') throw new Error(`上传文件失败：${name}`)
      content.push({ type: 'file', receiptId: upload.receiptId })
    }
    if (text.trim()) content.push({ type: 'text', text: text.trim() })
    await controller.prompt({
      requestId,
      sessionId,
      mode: 'queue',
      content,
    }, new AbortController().signal)
    return { accepted: true }
  } catch (error) {
    return { accepted: false, error: error instanceof Error ? error.message : String(error) }
  }
}
