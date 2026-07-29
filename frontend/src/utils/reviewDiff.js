export function changedAfterText(beforeValue, afterValue) {
  const before = String(beforeValue || '')
  const after = String(afterValue || '')
  if (!before || !after || after === '已删除') return after

  let start = 0
  while (start < before.length && start < after.length && before[start] === after[start]) {
    start += 1
  }

  let beforeEnd = before.length - 1
  let afterEnd = after.length - 1
  while (
    beforeEnd >= start
    && afterEnd >= start
    && before[beforeEnd] === after[afterEnd]
  ) {
    beforeEnd -= 1
    afterEnd -= 1
  }

  const changed = after.slice(start, afterEnd + 1).trim()
  return changed || after
}

export function reviewChangeForDisplay(change) {
  const before = String(change?.before || '原稿此处没有对应内容')
  const after = String(change?.after || '已删除')
  return {
    ...change,
    before,
    after: changedAfterText(before, after),
  }
}
