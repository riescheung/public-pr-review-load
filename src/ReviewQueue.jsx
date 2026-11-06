import { useEffect, useState } from 'react'
import { checkedAnswer, feedbackExport } from './queueFeedback.js'

const queueUrl = new URL('../data/reference_queue.json', import.meta.url)
const tier = score => score == null ? 'Unassessed' : `Tier ${score}`

function QueueEditor({ queue }) {
  const key = `weave-feedback:${queue.sha256}`
  const [index, setIndex] = useState(0)
  const [reviewer, setReviewer] = useState('')
  const [answers, setAnswers] = useState({})
  const [drafts, setDrafts] = useState({})
  const [message, setMessage] = useState('')
  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(key) || '{}')
      if (!saved || typeof saved !== 'object' || Array.isArray(saved)) throw new Error()
      setAnswers(saved)
    } catch {
      setMessage('Previous browser feedback could not be restored. Export a backup before changing this browser’s stored data.')
    }
  }, [key])
  if (!queue.cases.length) return <p>No completed frontier references are published yet. The held-out cases are not in this queue.</p>
  const entry = queue.cases[index]
  const saved = answers[entry.case_id]
  const draft = drafts[entry.case_id] || {
    text: JSON.stringify(saved?.review || entry.proposed_review, null, 2),
    note: saved?.reason || '', checked: false,
  }
  const update = values => setDrafts(current => ({
    ...current, [entry.case_id]: { ...draft, ...values },
  }))
  let draftScore = ''
  try { draftScore = String(JSON.parse(draft.text).score) } catch { /* Keep malformed JSON editable. */ }
  const changeTier = value => {
    try {
      const review = JSON.parse(draft.text)
      review.score = value === 'null' ? null : Number(value)
      if (review.score === null) {
        review.confidence = 'none'
        review.evidence = []
        review.abstention_reason = draft.note
      } else {
        review.confidence = review.confidence === 'none' ? 'low' : review.confidence
        review.evidence = review.evidence.length ? review.evidence : entry.proposed_review.evidence
        review.abstention_reason = null
      }
      update({ text: JSON.stringify(review, null, 2), checked: false })
      setMessage('Check the explanation and citations against your selected tier before saving.')
    } catch {
      setMessage('Fix the review JSON in the advanced editor before changing its tier.')
    }
  }
  const save = event => {
    event.preventDefault()
    try {
      const review = JSON.parse(draft.text)
      review.reason = draft.note
      if (review.score === null) review.abstention_reason = draft.note
      const answer = checkedAnswer(entry, reviewer || saved?.reviewer || '', draft.note, JSON.stringify(review), draft.checked)
      const next = { ...answers, [entry.case_id]: answer }
      localStorage.setItem(key, JSON.stringify(next))
      setAnswers(next)
      setMessage(`${entry.case_id} saved in this browser. Export feedback to include it in a tuning round.`)
    } catch (error) {
      setMessage(error instanceof DOMException
        ? 'Browser storage is unavailable or full. Keep this tab open; the correction was not saved.'
        : error.message)
    }
  }
  const download = () => {
    const blob = new Blob([JSON.stringify(feedbackExport(queue, answers), null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `qwen-feedback-${queue.sha256.slice(0, 12)}.json`
    link.click()
    URL.revokeObjectURL(url)
    setMessage('Feedback exported. A local import and versioned training run are still required; no weights change in the browser.')
  }
  return (
    <div className="queue-editor">
      <div className="queue-toolbar">
        <p>{queue.cases.length} development cases · {Object.keys(answers).length} saved corrections</p>
        <button type="button" onClick={download} disabled={!Object.keys(answers).length}>Export feedback</button>
      </div>
      <nav className="queue-navigation" aria-label="Review cases">
        <button type="button" disabled={index === 0} onClick={() => setIndex(index - 1)}>Previous case</button>
        <span>{index + 1} of {queue.cases.length}</span>
        <button type="button" disabled={index === queue.cases.length - 1} onClick={() => setIndex(index + 1)}>Next case</button>
      </nav>
      <h3>{entry.case_id}</h3>
      <p className="queue-estimates">Frontier estimate: <strong>{tier(entry.reference_review.score)}</strong> · Qwen: <strong>{entry.qwen_review ? tier(entry.qwen_review.score) : 'No valid review'}</strong></p>
      <p>{entry.flags.length ? entry.flags.join(' · ').replaceAll('_', ' ') : 'No disagreement flag'} · {entry.source === 'user_feedback' ? 'Previously corrected by a user' : 'AI reference, not human gold'}</p>
      <p>{entry.reference_review.reason}</p>
      <details><summary>Read the rubric and complete diff ({entry.packet.chunks.length} chunks)</summary>
        <pre className="queue-rubric">{entry.packet.system}</pre>
        {entry.packet.chunks.map((chunk, chunkIndex) => (
          <div key={chunkIndex}><h4>Chunk {chunkIndex + 1}</h4><pre>{chunk.text}</pre></div>
        ))}
      </details>
      {entry.qwen_review && <details><summary>Inspect Qwen’s explanation and citations</summary><pre>{JSON.stringify(entry.qwen_review, null, 2)}</pre></details>}
      <form onSubmit={save}>
        <label>Your tier estimate
          <select value={draftScore} onChange={event => changeTier(event.target.value)} required>
            <option value="" disabled>Fix the advanced review JSON</option>
            <option value="1">Tier 1</option><option value="2">Tier 2</option>
            <option value="3">Tier 3</option><option value="null">Unassessed</option>
          </select>
        </label>
        <label>Reviewer identifier
          <input value={reviewer || saved?.reviewer || ''} onChange={event => setReviewer(event.target.value)} required minLength={2} autoComplete="off" />
        </label>
        <label>Why do you accept or change this estimate?
          <textarea value={draft.note} onChange={event => update({ note: event.target.value })} required minLength={15} rows={2} />
        </label>
        <details><summary>Edit explanation details and citations</summary>
          <label>Approved review JSON
            <span className="queue-help">Your note becomes the decision reason. Correct observations and citations here if the proposed explanation is wrong. Keep one observation set per chunk.</span>
            <textarea className="queue-json" spellCheck={false} value={draft.text} onChange={event => update({ text: event.target.value, checked: false })} required rows={13} />
          </label>
        </details>
        <label className="queue-check">
          <input type="checkbox" checked={draft.checked} onChange={event => update({ checked: event.target.checked })} />
          I checked the changed code and the explanation’s supporting evidence.
        </label>
        <button type="submit">Save correction locally</button>
      </form>
      <p role="status" aria-live="polite" className="queue-message">{message}</p>
    </div>
  )
}

export default function ReviewQueue() {
  const [open, setOpen] = useState(false)
  const [queue, setQueue] = useState(null)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    if (!open || queue) return undefined
    const controller = new AbortController()
    setError('')
    fetch(queueUrl, { signal: controller.signal })
      .then(response => {
        if (!response.ok) throw new Error('The review queue could not be loaded.')
        return response.json()
      })
      .then(data => {
        if (data.version !== 1 || !Array.isArray(data.cases) || !data.sha256) throw new Error('The published queue has an unsupported format.')
        setQueue(data)
      })
      .catch(failure => {
        if (failure.name !== 'AbortError') setError(`${failure.message} Your saved corrections are unchanged.`)
      })
    return () => controller.abort()
  }, [open, queue, attempt])
  return (
    <section className="review-desk review-queue" id="review-queue" aria-labelledby="queue-title">
      <div className="review-desk-header">
        <div><h2 id="queue-title">Improve Qwen’s estimates</h2><p>Frontier-model references first. Your code-checked corrections feed later tuning rounds.</p></div>
        <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? 'Hide review queue' : 'Open review queue'}</button>
      </div>
      {(open || queue) && <div hidden={!open}>
        <p className="queue-help">Corrections stay in this browser until exported. This static site cannot retrain Qwen itself. Export, import locally, train a new version, then compare it before rollout. The 60 final-test cases never enter this queue.</p>
        {error ? <p role="alert">{error} <button type="button" onClick={() => setAttempt(attempt + 1)}>Retry loading</button></p>
          : queue ? <QueueEditor queue={queue} /> : <p role="status">Loading development references and code diffs…</p>}
      </div>}
    </section>
  )
}
