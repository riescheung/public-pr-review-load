import test from 'node:test'
import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

test('score guides are separate, initially collapsed disclosures with labelled diagrams', async () => {
  const server = await createServer({ server: { middlewareMode: true }, appType: 'custom' })
  try {
    const { default: ScoreExplainers } = await server.ssrLoadModule('/src/ScoreExplainers.jsx')
    const html = renderToStaticMarkup(createElement(ScoreExplainers))
    assert.equal((html.match(/<details /g) || []).length, 2)
    assert.doesNotMatch(html, /<details[^>]*\bopen(?:[=>\s])/)
    assert.match(html, /What is WPR\?/)
    assert.match(html, /How does Qwen review code\?/)
    assert.equal((html.match(/<figure /g) || []).length, 5)
    assert.equal((html.match(/<figcaption>/g) || []).length, 5)
    assert.match(html, /cap applies to each PR, not the total/)
    assert.match(html, /one final decision per group/)
    assert.match(html, /Coverage is 2 of 3 groups scored/)
    assert.match(html, /not another AI judge/)
    assert.match(html, /Neither WPR nor confidence weights this mean/)
    assert.match(html, /not verified business impact or individual performance/)
  } finally {
    await server.close()
  }
})
