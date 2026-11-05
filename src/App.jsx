import { useEffect, useMemo, useState } from 'react'
import report from '../data/report.json'

const PAGE_SIZE = 5
const people = [...report.people].sort((a, b) => b.wpr - a.wpr || a.login.localeCompare(b.login))
const periods = report.periods
const number = new Intl.NumberFormat('en-US')

function RankInsignia({ rank }) {
  if (rank > 5) return <span className="plain-rank">{String(rank).padStart(2, '0')}</span>
  return (
    <span className={`rank-insignia rank-${rank}`} aria-label={`WPR rank ${rank}`}>
      <svg aria-hidden="true" viewBox="0 0 40 40" fill="none">
        <path d="M20 2.5 24.6 8l7.1-.8.8 7.1L38 20l-5.5 5.7.8 7.1-7.1.8L20 39l-5.7-5.4-7.1.8-.8-7.1L1 20l5.4-5.7-.8-7.1 7.1.8L20 2.5Z" />
      </svg>
      <span>{rank}</span>
    </span>
  )
}

function PeriodCell({ cell, person, index, onOpen }) {
  const label = periods[index].label
  return (
    <div className={`period-cell ${index === 6 ? 'period-cell-current' : ''} ${cell.wpr > 0 ? 'has-evidence' : ''}`}>
      <button
        type="button"
        className="period-metric"
        onClick={() => onOpen(person, index)}
        aria-label={`${person.login}, period ending ${label}: ${number.format(cell.wpr)} WPR across ${cell.prs.length} merged PRs. View PR list. Outcome not assessed.`}
      >
        <span className="cell-score">{cell.prs.length ? number.format(cell.wpr) : '—'}<small> WPR</small></span>
        <span className="cell-merged">{cell.prs.length} merged PRs</span>
      </button>
      <div className="period-outcome"><span>Outcome</span><strong>—</strong></div>
    </div>
  )
}

function PeriodPrBreakdown({ prs, wpr }) {
  const [visibleCount, setVisibleCount] = useState(5)
  const shown = prs.slice(0, visibleCount)
  return (
    <section className="panel-section pr-breakdown">
      <h3>PRs behind this WPR total ({prs.length})</h3>
      <p className="panel-reconciliation">
        {prs.length} authored merged PRs contribute {number.format(wpr)} WPR. This estimates review load from file changes; it does not measure author effort or outcome.
      </p>
      {shown.length ? (
        <ul className="pr-breakdown-list">
          {shown.map((pr) => (
            <li key={pr.number}>
              <a href={`https://github.com/PostHog/posthog/pull/${pr.number}`} target="_blank" rel="noopener noreferrer">
                <span>#{pr.number} {pr.title}</span>
                <strong>{pr.wpr == null ? 'Pending' : `${pr.wpr} WPR`}</strong>
              </a>
            </li>
          ))}
        </ul>
      ) : <p className="no-evidence">No PRs by this contributor merged in this interval.</p>}
      {prs.length > shown.length && (
        <p className="more-evidence">
          Showing {shown.length} of {prs.length} PRs.{' '}
          <button type="button" onClick={() => setVisibleCount(Math.min(prs.length, visibleCount + 25))}>Show more PRs</button>
        </p>
      )}
    </section>
  )
}

function ReviewDesk() {
  return (
    <section className="review-desk" aria-labelledby="review-desk-title">
      <div className="review-desk-header">
        <div>
          <h2 id="review-desk-title">Outcome score: reserved</h2>
          <p>No outcome metric is assigned in this snapshot. WPR cannot fill that gap.</p>
        </div>
        <span className="review-desk-state">Not assessed</span>
      </div>
      <div className="review-plan">
        <strong>Review queue ready · model run paused</strong>
        <p>In a future run, two independent local Qwen reviewers would read complete PR diffs and each propose a 1–3 tier or abstain. GPT-6 Sol can supply provisional training labels; three separate human decisions are held out for calibration.</p>
        <p>The existing queue flags reviewer disagreements, abstentions, grouping issues and large WPR–tier gaps: WPR ≥ 7 with tier 1, or WPR &lt; 3 with tier 3. A flag is not a score correction. A human inspects the code, makes the final tier call and saves the reason as calibration; nothing automatically changes the dashboard.</p>
      </div>
      <p className="review-desk-caveat">No Qwen reviewer is trained or running. Even two agreeing reviewers cannot prove customer benefit.</p>
    </section>
  )
}

function EvidencePanel({ selected, onClose }) {
  useEffect(() => {
    if (!selected) return undefined
    const onKey = (event) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selected, onClose])
  if (!selected) return null
  const { person, index } = selected
  const cell = index == null ? null : person.periods[index]
  const prs = cell ? cell.prs : person.periods.flatMap((period) => period.prs).sort((a, b) => b.wpr - a.wpr || a.number - b.number)
  return (
    <>
      <button className="panel-scrim" aria-label="Close evidence panel" onClick={onClose} />
      <aside className="evidence-panel" aria-label={`Evidence for ${person.login}`}>
        <div className="panel-head">
          <div>
            <p className="panel-context">{index == null ? 'Contributor file' : `${periods[index].start} to ${periods[index].end}`}</p>
            <h2>{person.login}</h2>
            <p>{number.format(cell ? cell.wpr : person.wpr)} WPR across {prs.length} authored merged PRs · outcome not assessed</p>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Close panel">×</button>
        </div>
        <div className="panel-statline">
          {cell ? <>
            <span>{cell.prs.length} merged PRs in interval</span>
            <span>{number.format(cell.wpr)} WPR on those PRs</span>
            <span>Outcome — not assessed</span>
          </> : <>
            <span>{number.format(person.merged_prs)} merged PRs</span>
            <span>{number.format(person.reviewed_prs)} PRs reviewed</span>
            <span>{number.format(person.wpr)} WPR on authored PRs</span>
            <span>Outcome — not assessed</span>
          </>}
        </div>
        <PeriodPrBreakdown key={index ?? 'all'} prs={prs} wpr={cell ? cell.wpr : person.wpr} />
      </aside>
    </>
  )
}

export default function App() {
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState('wpr')
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState(null)
  const [methodOpen, setMethodOpen] = useState(false)
  const filtered = useMemo(() => {
    const text = search.trim().toLowerCase()
    const result = people
      .filter((person) => person.login.toLowerCase().includes(text))
      .slice()
    if (sort === 'name') result.sort((a, b) => a.login.localeCompare(b.login))
    if (sort === 'wpr') result.sort((a, b) => b.wpr - a.wpr || a.login.localeCompare(b.login))
    return result
  }, [search, sort])
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const visible = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
  const rankByLogin = useMemo(() => new Map(people.map((person, index) => [person.login, index + 1])), [])
  const open = (person, index = null) => setSelected({ person, index })
  const reset = (setter) => (event) => {
    setter(event.target.value)
    setPage(1)
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand"><span className="brand-mark"><i /><i /><i /></span><span>weave<span className="brand-dot">.</span></span></div>
        <span className="topbar-label">Public PR review load / PostHog</span>
        <a href="https://github.com/PostHog/posthog" target="_blank" rel="noopener noreferrer" className="source-link">Source repository <span aria-hidden="true">↗</span></a>
      </header>

      <main>
        <section className="intro" aria-label="Report overview">
          <div className="intro-copy">
            <h1>Review load, estimated.</h1>
            <p>Weighted PR (WPR) is a public-code proxy for review scope. Outcome scores are intentionally unassigned.</p>
          </div>
          <div className="snapshot">
            <span className="snapshot-indicator" />
            <div><strong>98-day snapshot</strong><span>{report.manifest.window_start} — {report.manifest.window_end}</span></div>
          </div>
        </section>

        <div className="coverage">
          <div><strong>{number.format(report.manifest.merged_prs)}</strong> merged PRs audited</div>
          <span className="coverage-separator" />
          <div><strong>{number.format(people.length)}</strong> observed human contributors</div>
          <span className="coverage-separator" />
          <div><strong>{number.format(report.manifest.human_prs)}</strong> human-authored PRs with WPR</div>
          <button className="method-trigger" onClick={() => setMethodOpen(!methodOpen)} aria-expanded={methodOpen}>How WPR works <span aria-hidden="true">{methodOpen ? '−' : '+'}</span></button>
        </div>
        <p className="coverage-warning"><strong>WPR is not an outcome score.</strong> It estimates review load, grows with PR volume, and cannot establish author effort, adoption or customer benefit. The order below is not a performance ranking.</p>

        {methodOpen && <section className="method-panel" aria-label="WPR methodology">
          <div><h2>What is WPR?</h2><p>Each merged PR gets a 0–10 weighted review-load estimate from its changed files. Trivial and generated files are discounted; a net revert receives zero. The table sums PR WPR by author and merge period.</p></div>
          <div><h2>What is left blank?</h2><p>The outcome field is unassigned, not zero. A code-reviewed 1–3 tier could describe visible work later, but even that would not prove a real user outcome. No title-based points or AI tiers contribute to this display.</p></div>
          <div><h2>What is missing?</h2><p>Public GitHub cannot verify private work, reviews, mentorship, deployments, user adoption or individual ownership. Slush-branch PR overlap is not subtracted in this snapshot. WPR is not an effort or performance measure.</p></div>
        </section>}

        <ReviewDesk />

        <section className="contributor-board" aria-label="Contributor review-load index">
          <div className="board-heading">
            <div><h2>Public review-load index</h2><p>Highest WPR totals first. Top-five symbols mark rank by this proxy, not impact.</p></div>
            <div className="board-actions">
              <label className="search-wrap">
                <svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="8.8" cy="8.8" r="5.9"/><path d="m13.4 13.4 4.3 4.3"/></svg>
                <span className="sr-only">Search contributors</span>
                <input value={search} onChange={reset(setSearch)} placeholder="Find contributor" type="search" />
              </label>
              <label className="sort-wrap"><span className="sr-only">Sort contributors</span><select value={sort} onChange={reset(setSort)}><option value="wpr">Sort: WPR</option><option value="name">Sort: name</option></select></label>
            </div>
          </div>
          <div className="board-filterbar">
            <span>Showing {filtered.length} of {people.length} contributors</span>
            <span>Outcome score: not assessed</span>
          </div>

          <div className="table-scroll">
            <table>
              <thead><tr><th className="rank-column" scope="col">WPR rank</th><th className="person-column" scope="col">Contributor</th>{periods.map((period, index) => <th key={period.end} className={`period-heading ${index === 6 ? 'current-heading' : ''}`} scope="col"><span>{period.label}</span><small>{index === 6 ? 'LATEST' : `${period.start.slice(5)} – ${period.end.slice(5)}`}</small></th>)}</tr></thead>
              <tbody>{visible.map((person) => <tr key={person.login}>
                <td className="rank-column"><RankInsignia rank={rankByLogin.get(person.login)} /></td>
                <th scope="row" className="person-column"><button type="button" className="person-button" onClick={() => open(person)}><span className="person-name">{person.login}</span><span className="person-sub">{number.format(person.wpr)} WPR <span aria-hidden="true">·</span> {number.format(person.merged_prs)} PRs</span></button></th>
                {person.periods.map((cell, index) => <td className="timeline-td" key={periods[index].end}><PeriodCell cell={cell} person={person} index={index} onOpen={open} /></td>)}
              </tr>)}</tbody>
            </table>
          </div>
          {!visible.length && <p className="empty-results">No contributors match this name. Try another search.</p>}
          <div className="board-footer">
            <p><span className="legend-swatch" /> WPR estimates review load <span className="legend-current" /> Latest interval · outcome deliberately blank</p>
            <nav className="pagination" aria-label="Contributor pages"><button onClick={() => setPage(Math.max(1, page - 1))} disabled={page === 1} aria-label="Previous page">←</button><span>Page <strong>{page}</strong> of {pages}</span><button onClick={() => setPage(Math.min(pages, page + 1))} disabled={page === pages} aria-label="Next page">→</button></nav>
          </div>
        </section>
        <footer className="site-footer"><span>WPR is a scope proxy, not measured impact, author effort or a performance review.</span><span>Snapshot taken {report.manifest.retrieved_at.slice(0, 10)} UTC · <a href="https://github.com/PostHog/posthog" target="_blank" rel="noopener noreferrer">PostHog/posthog ↗</a></span></footer>
      </main>
      <EvidencePanel
        key={selected ? `${selected.person.login}:${selected.index}` : 'closed'}
        selected={selected}
        onClose={() => setSelected(null)}
      />
    </div>
  )
}
