/** Keep the final answer intact for the scrollable call transcript. */
export function displayReply(event) {
  const message = event?.data?.message
  if (!message || (message.role && message.role !== 'assistant')) return ''
  const channel = message.channel ?? message.source?.channel ?? event.data?.channel
  if (channel && channel !== 'final') return ''
  const content = message.content
  const raw = typeof content === 'string' ? content
    : Array.isArray(content) ? content
      .filter((part) => part && ['text', 'output_text'].includes(part.type))
      .map((part) => part.text ?? '').join('\n')
      : ''
  return raw.trim()
}

/** Turn a final answer into concise speech without changing the visible text. */
export function spokenReply(event) {
  return displayReply(event)
    .replace(/```[\s\S]*?```/gu, ' 代码内容请查看对话。 ')
    .replace(/!?(?:\[([^\]]+)\])\([^)]*\)/gu, '$1')
    .replace(/https?:\/\/\S+/gu, '链接请查看对话')
    .replace(/[#*_`>~]/gu, '')
    .replace(/\s+/gu, ' ')
    .trim()
    .slice(0, 2400)
}
