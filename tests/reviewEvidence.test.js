import test from 'node:test'
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { loadReviewRecord } from '../src/reviewEvidence.js'

const record = {
  id: 'change', prs: [42], status: 'ok', tier: 2, run: 'qwen',
  source: 'publication', known_calibration: false, review: { reason: 'Cited code change' },
}
const hash = text => createHash('sha256').update(text).digest('hex')
const text = JSON.stringify(record)
const entry = { ...record, evidence_sha256: hash(text) }
delete entry.review

test('legacy inline reviews require no network request', async () => {
  assert.equal(await loadReviewRecord(record, {
    fetcher: () => assert.fail('inline records should not fetch'),
  }), record)
})

test('evidence loads from the Pages base and verifies its exact bytes', async () => {
  let requested
  const loaded = await loadReviewRecord(entry, {
    baseUrl: '/project/',
    fetcher: async url => { requested = url; return new Response(text) },
  })
  assert.deepEqual([requested, loaded], [
    `/project/review-evidence/${hash(text)}.json`, record,
  ])
})

test('missing, corrupted and foreign evidence fail closed', async () => {
  const foreign = JSON.stringify({ ...record, id: 'another-change' })
  for (const [indexed, response, message] of [
    [entry, new Response('missing', { status: 404 }), /could not be loaded/],
    [entry, new Response(text + ' '), /integrity verification/],
    [{ ...entry, evidence_sha256: hash(foreign) }, new Response(foreign), /does not match/],
  ]) {
    await assert.rejects(loadReviewRecord(indexed, {
      fetcher: async () => response,
    }), message)
  }
})
