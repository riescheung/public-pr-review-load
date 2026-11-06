import { useState } from 'react'
import estimates from '../data/contribution_estimates.json'
import { estimateValue } from './contributionEstimates.js'

export { estimates }

export function contributionSummary(login, index = null) {
  const person = estimates.people[login]
  return index == null ? person?.total : person?.periods[index]
}

export function ContributionCell({ login, index, onOpen }) {
  const summary = contributionSummary(login, index)
  const value = estimateValue(summary)
  return (
    <button type="button" className={`period-estimate ${summary?.scored ? 'has-estimate' : ''}`}
      onClick={onOpen}
      aria-label={`AI-estimated contribution for ${login}: ${value}. ${summary?.scored || 0} of ${summary?.groups || 0} grouped changes scored. Open evidence.`}>
      <span><span>AI estimate</span><strong>{value}</strong></span>
      <small>{summary?.scored || 0}/{summary?.groups || 0} changes scored</small>
    </button>
  )
}

export function ContributionEvidence({ login, index }) {
  const [limit, setLimit] = useState(5)
  const summary = contributionSummary(login, index)
  const records = (summary?.review_ids || []).map(id => estimates.reviews[id])
  return (
    <section className="panel-section contribution-evidence">
      <h3>AI-estimated contribution: {estimateValue(summary)}</h3>
      <p>{summary?.scored || 0} of {summary?.groups || 0} grouped changes scored. This is the mean 1–3 code-change tier among scored groups, not a total impact score or a comparison of people. Unreviewed work is not zero.</p>
      <p>A group counts once per contributor, in their latest interval containing a member PR. Shared groups describe associated work, not individual ownership. WPR and the table’s ordering are unchanged.</p>
      {!!(summary?.abstained || summary?.failed || summary?.reserved || summary?.unmapped_prs) &&
        <p>{summary.abstained} abstentions · {summary.failed} failed or deferred · {summary.reserved} reserved test groups · {summary.unmapped_prs} PRs without an eligible group.</p>}
      {records.slice(0, limit).map(record => (
        <details key={record.id}>
          <summary>{record.tier == null ? 'Unassessed' : `Tier ${record.tier}`} · {record.prs.map(pr => `#${pr}`).join(', ')}</summary>
          <p>{record.review?.reason || 'No valid model review was saved for this attempt.'}</p>
          <p className="estimate-source">{estimates.models[record.run].name} · {record.run}{record.known_calibration ? ' · Previously inspected calibration example' : ''}</p>
          <p>{record.prs.map(pr => <a key={pr} href={`https://github.com/PostHog/posthog/pull/${pr}`} target="_blank" rel="noopener noreferrer">PR #{pr} </a>)}</p>
          {record.review?.observations?.flatMap(chunk => chunk.observations).map((observation, n) =>
            <div key={`${observation.hunk}:${n}`} className="estimate-citation">
              <strong>{observation.hunk}</strong><p>{observation.behavior}</p>
              <pre>{observation.code_quote}</pre>
            </div>)}
          {record.review?.uncertainty && <p>Uncertainty: {record.review.uncertainty}</p>}
          <p className="estimate-source">Prediction SHA-256: <code>{record.prediction_sha256}</code></p>
        </details>
      ))}
      {records.length > limit && <button type="button" onClick={() => setLimit(limit + 10)}>Show more AI reviews</button>}
      {!records.length && <p>No Qwen reviews are available for these groups yet. No estimate has been inferred from PR titles or WPR.</p>}
    </section>
  )
}
