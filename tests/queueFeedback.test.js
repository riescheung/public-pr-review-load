import assert from 'node:assert/strict'
import test from 'node:test'
import { checkedAnswer, feedbackExport } from '../src/queueFeedback.js'

const entry = {
  case_id: 'opaque', packet_sha256: 'packet', reference_sha256: 'reference', supersedes: null,
  packet: { chunks: [{ changed_lines: { 'P1.F1.H1': ['return safe'] } }] },
}
const review = {
  score: 2, reason: 'A bounded behavior change.', posthog_relevance: 'Query correctness.',
  uncertainty: 'No adoption evidence.', confidence: 'medium', evidence: ['P1.F1.H1'],
  metadata_dependency: false, grouping_issue: false, abstention_reason: null,
  observations: [{ observations: [{
    hunk: 'P1.F1.H1', code_quote: 'return safe',
    behavior: 'Changes returned behavior.', posthog_connection: 'Query correctness.',
  }], limitations: 'Missing caller context.' }],
}
const save = (value = review, checked = true) =>
  checkedAnswer(entry, 'reviewer', 'I checked the code behavior.', JSON.stringify(value), checked)

test('feedback is an explicit user correction bound to code, not human gold or an outcome', () => {
  const answer = save()
  assert.equal(answer.source, 'user_feedback')
  assert.equal(answer.human_gold, false)
  assert.equal(answer.packet_sha256, 'packet')
  assert.equal(answer.reference_sha256, 'reference')
  assert.deepEqual(feedbackExport({ sha256: 'queue' }, { opaque: answer }), {
    version: 1, queue_sha256: 'queue', answers: [answer],
  })
})

test('all tiers and an intentional abstention can be approved', () => {
  for (const score of [1, 2, 3]) assert.equal(save({ ...review, score }).score, score)
  const abstention = { ...review, score: null, confidence: 'none', evidence: [],
    abstention_reason: 'Insufficient surrounding code context.' }
  assert.equal(save(abstention).score, null)
})

test('unchecked evidence, unknown hunk IDs, invented quotes and malformed decisions fail', () => {
  assert.throws(() => save(review, false), /Check the cited code/)
  assert.throws(() => save({ ...review, score: true }), /tier/)
  assert.throws(() => save({ ...review, evidence: ['unknown'] }), /observed/)
  assert.throws(() => save({ ...review, confidence: 'none' }), /confidence/)
  assert.throws(() => save({ ...review, observations: [] }), /every diff chunk/)
  const broken = structuredClone(review)
  broken.observations[0].observations[0].code_quote = 'invented quote'
  assert.throws(() => save(broken), /changed line/)
  assert.throws(() => checkedAnswer(entry, '', 'reason', '{}', true), /reviewer/)
})
