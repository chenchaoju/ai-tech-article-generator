export async function copyText(text) {
  const value = String(text || '')
  if (!value) throw new Error('没有可复制的内容')

  if (window.isSecureContext && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value)
      return
    } catch {
      // Some browsers expose Clipboard API but reject it because of a policy
      // or permission. Continue with the selection-based fallback below.
    }
  }

  const textarea = document.createElement('textarea')
  const previousFocus = document.activeElement
  textarea.value = value
  textarea.setAttribute('readonly', '')
  textarea.style.position = 'fixed'
  textarea.style.left = '-9999px'
  textarea.style.top = '0'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.focus()
  textarea.select()
  textarea.setSelectionRange(0, textarea.value.length)

  let copied = false
  try {
    copied = document.execCommand('copy')
  } finally {
    textarea.remove()
    previousFocus?.focus?.()
  }
  if (!copied) {
    throw new Error('浏览器未允许复制，请选中正文后手动复制')
  }
}
