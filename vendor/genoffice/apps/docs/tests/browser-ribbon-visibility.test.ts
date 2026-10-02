import { expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

it('gives hidden ribbon buttons an explicit author display override', () => {
  const style = document.createElement('style')
  style.textContent = readFileSync('src/renderer/styles.css', 'utf8')
  document.head.append(style)
  try {
    const rules = Array.from(style.sheet!.cssRules).filter(
      (rule): rule is CSSStyleRule => rule.type === CSSRule.STYLE_RULE,
    )
    const normal = rules.findIndex((rule) => rule.selectorText === '.rb-big')
    const hidden = rules.findIndex((rule) => rule.selectorText === '.rb-big[hidden]')
    expect(normal).toBeGreaterThanOrEqual(0)
    expect(hidden).toBeGreaterThan(normal)
    expect(rules[hidden]?.style.display).toBe('none')
  } finally {
    style.remove()
  }
})
