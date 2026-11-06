import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import { estimateValue } from '../src/contributionEstimates.js'

test('only validated, scored mean tiers become numeric estimates', () => {
  assert.equal(estimateValue({ scored: 2, mean_tier: 1.5 }), '1.5/3')
  for (const mean_tier of [null, NaN, Infinity, 0, 4]) {
    assert.equal(estimateValue({ scored: 2, groups: 10, mean_tier }), 'Pending')
  }
  assert.equal(estimateValue({ groups: 10, scored: 0, score: 9000, wpr: 500 }), 'Pending')
})

test('unassessed, reserved and absent work are distinct from zero contribution', () => {
  assert.equal(estimateValue({ groups: 1, abstained: 1 }), 'Unassessed')
  assert.equal(estimateValue({ groups: 1, failed: 1 }), 'Unassessed')
  assert.equal(estimateValue({ groups: 1, reserved: 1 }), 'Reserved')
  assert.equal(estimateValue({ groups: 0, unmapped_prs: 0 }), 'No changes')
  assert.equal(estimateValue({ groups: 0, unmapped_prs: 1 }), 'Pending')
  assert.equal(estimateValue(undefined), 'Pending')
})

test('published estimates identify models and reconcile every period coverage count', () => {
  const data = JSON.parse(fs.readFileSync(new URL('../data/contribution_estimates.json', import.meta.url)))
  assert.equal(data.human_gold, false)
  assert.ok(Object.values(data.models).some(model => model.adapter_sha256))
  for (const person of Object.values(data.people)) {
    assert.equal(person.periods.reduce((n, p) => n + p.groups, 0), person.total.groups)
    for (const summary of person.periods) {
      assert.equal(summary.scored + summary.abstained + summary.failed + summary.reserved + summary.pending, summary.groups)
      assert.equal(Object.values(summary.tiers).reduce((n, x) => n + x, 0), summary.scored)
      assert.equal(summary.scored > 0, summary.mean_tier !== null)
    }
  }
})
