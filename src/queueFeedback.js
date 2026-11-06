export function checkedAnswer(entry, reviewer, note, text, evidenceChecked) {
  if (reviewer.trim().length < 2) throw new Error('Enter a reviewer identifier.')
  if (note.trim().length < 15) throw new Error('Explain your decision in at least 15 characters.')
  if (!evidenceChecked) throw new Error('Check the cited code before saving a training correction.')
  let review
  try { review = JSON.parse(text) } catch { throw new Error('The approved review must be valid JSON.') }
  if (!review || ![1, 2, 3, null].includes(review.score)) throw new Error('Use tier 1, 2, 3 or null.')
  for (const key of ['reason', 'uncertainty']) {
    if (typeof review[key] !== 'string' || !review[key].trim()) throw new Error(`Add ${key} to the review.`)
  }
  if (review.metadata_dependency !== false || typeof review.grouping_issue !== 'boolean') {
    throw new Error('Set metadata_dependency to false and grouping_issue to a boolean.')
  }
  if (!Array.isArray(review.observations) || review.observations.length !== entry.packet.chunks.length) {
    throw new Error('Approve one observation set for every diff chunk.')
  }
  const observed = new Set()
  review.observations.forEach((chunk, index) => {
    if (!Array.isArray(chunk.observations) || !chunk.observations.length ||
        typeof chunk.limitations !== 'string' || !chunk.limitations.trim()) {
      throw new Error('Each chunk needs code-backed observations and limitations.')
    }
    chunk.observations.forEach(item => {
      const lines = entry.packet.chunks[index].changed_lines[item.hunk] || []
      if (typeof item.code_quote !== 'string' || item.code_quote.trim().length < 8 ||
          !lines.some(line => line.trim() === item.code_quote.trim())) {
        throw new Error('Every quote must match one changed line in its cited hunk.')
      }
      for (const key of ['behavior', 'posthog_connection']) {
        if (typeof item[key] !== 'string' || !item[key].trim()) throw new Error(`Add ${key} to each observation.`)
      }
      observed.add(item.hunk)
    })
  })
  if (!Array.isArray(review.evidence) || review.evidence.some(hunk => !observed.has(hunk))) {
    throw new Error('Decision evidence must cite observed hunk IDs.')
  }
  if (review.score === null) {
    if (review.confidence !== 'none' || review.evidence.length ||
        typeof review.abstention_reason !== 'string' || !review.abstention_reason.trim()) {
      throw new Error('Abstain with confidence none, empty evidence and a specific abstention reason.')
    }
  } else if (!['low', 'medium', 'high'].includes(review.confidence) || !review.evidence.length ||
      review.grouping_issue || review.abstention_reason != null ||
      typeof review.posthog_relevance !== 'string' || !review.posthog_relevance.trim()) {
    throw new Error('A tier needs confidence, cited evidence, PostHog relevance and coherent grouping.')
  }
  return {
    case_id: entry.case_id, packet_sha256: entry.packet_sha256,
    reference_sha256: entry.reference_sha256, supersedes: entry.supersedes,
    source: 'user_feedback', human_gold: false,
    reviewer: reviewer.trim(), reason: note.trim(), score: review.score, review,
    evidence_checked: true,
  }
}

export function feedbackExport(queue, answers) {
  return { version: 1, queue_sha256: queue.sha256, answers: Object.values(answers) }
}
