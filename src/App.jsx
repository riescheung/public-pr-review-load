import { useEffect, useMemo, useState } from 'react'
import report from '../data/report.json'
import { notes } from './notes.js'

const PAGE_SIZE = 5
const people = report.people
const periods = report.periods
const number = new Intl.NumberFormat('en-US')
const creditedPoints = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 3 })

function RankInsignia({ rank }) {
  if (rank > 5) return <span className="plain-rank">{String(rank).padStart(2, '0')}</span>
  return (
    <span className={`rank-insignia rank-${rank}`} aria-label={`Rank ${rank}`}>
      <svg aria-hidden="true" viewBox="0 0 40 40" fill="none">
        <path d="M20 2.5 24.6 8l7.1-.8.8 7.1L38 20l-5.5 5.7.8 7.1-7.1.8L20 39l-5.7-5.4-7.1.8-.8-7.1L1 20l5.4-5.7-.8-7.1 7.1.8L20 2.5Z" />
      </svg>
      <span>{rank}</span>
    </span>
  )
}

function AttentionMark({ person }) {
  if (!person.attention) return null
  return (
    <span
      className="attention-mark"
      role="img"
      aria-label="Worth a closer look: high estimated review load and limited visible outcome evidence"
      title="Worth a closer look · review load is high relative to visible outcome evidence"
    >
      <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <path d="M10 1.8 18.2 10 10 18.2 1.8 10 10 1.8Z" />
        <path d="M10 5.5v5.2M10 13.6v.9" />
      </svg>
    </span>
  )
}

function PeriodCell({ cell, person, index, onOpen, mobile = false }) {
  const label = periods[index].label
  return (
    <div className={`period-cell ${index === 6 ? 'period-cell-current' : ''} ${cell.score > 0 ? 'has-evidence' : ''}`}>
      {mobile && <span className="period-mobile-date">{label}</span>}
      <button
        type="button"
        className="period-metric"
        onClick={() => onOpen(person, index, 'outcomes')}
        aria-label={`${person.login}, period ending ${label}: ${cell.score.toFixed(1)} evidence points from ${cell.outcomes} supported outcomes. View outcome list.`}
      >
        <span className="cell-score">{cell.score > 0 ? cell.score.toFixed(1) : '—'}<small> pts</small></span>
        <span className="cell-outcomes">{cell.outcomes} {cell.outcomes === 1 ? 'outcome' : 'outcomes'}</span>
      </button>
      <button
        type="button"
        className="period-metric period-review-metric"
        onClick={() => onOpen(person, index, 'review')}
        aria-label={`${person.login}, period ending ${label}: ${cell.wpr == null ? 'review load pending' : `${cell.wpr} weighted PR review load`} across ${cell.prs.length} merged PRs. View PR list.`}
      >
        <span className="cell-merged">{cell.prs.length} merged PRs</span>
        <span className="cell-wpr">{cell.wpr == null ? 'Review load pending' : `${number.format(cell.wpr)} WPR`}</span>
      </button>
    </div>
  )
}

function PeriodPrBreakdown({ cell }) {
  const [visibleCount, setVisibleCount] = useState(5)
  const shown = cell.prs.slice(0, visibleCount)
  const shownWpr = shown.reduce((sum, pr) => sum + (pr.wpr ?? 0), 0)
  return (
    <section className="panel-section pr-breakdown">
      <h3>PRs behind this interval's review load ({cell.prs.length})</h3>
      <p className="panel-reconciliation">
        {cell.prs.length} merged PRs contribute {cell.wpr == null ? 'pending WPR' : `${number.format(cell.wpr)} WPR`}. WPR estimates review load; evidence points follow supported outcomes, sometimes in a later release period.
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
      {cell.prs.length > shown.length && (
        <p className="more-evidence">
          Showing {shown.length} PRs{cell.wpr == null ? '' : ` (${shownWpr} WPR)`}; {cell.prs.length - shown.length} more{cell.wpr == null ? '' : ` contribute ${cell.wpr - shownWpr} WPR`}.{' '}
          <button type="button" onClick={() => setVisibleCount(cell.prs.length)}>Show all {cell.prs.length} PRs</button>
        </p>
      )}
    </section>
  )
}

function EvidencePanel({ selected, onClose, onSelectView }) {
  const [visibleCount, setVisibleCount] = useState(5)
  useEffect(() => {
    if (!selected) return undefined
    const onKey = (event) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selected, onClose])
  if (!selected) return null
  const { person, index, view } = selected
  const cell = index == null ? null : person.periods[index]
  const items = cell ? cell.examples : person.featured
  const shown = items.slice(0, visibleCount)
  const attentionCohort = report.manifest.attention_cohort
  const showingReview = cell && view === 'review'
  return (
    <>
      <button className="panel-scrim" aria-label="Close evidence panel" onClick={onClose} />
      <aside className="evidence-panel" aria-label={`Evidence for ${person.login}`}>
        <div className="panel-head">
          <div>
            <p className="panel-context">{index == null ? 'Contributor file' : `${periods[index].start} to ${periods[index].end}`}</p>
            <h2>{person.login}</h2>
            <p>{cell
              ? showingReview
                ? `${cell.wpr == null ? 'WPR pending' : `${number.format(cell.wpr)} WPR`} across ${cell.prs.length} merged PRs`
                : `${cell.score.toFixed(1)} evidence points from ${cell.outcomes} supported outcomes`
              : `${person.score.toFixed(1)} evidence points across ${person.outcome_count} supported outcomes`}</p>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Close panel">×</button>
        </div>
        {person.attention && (
          <div className="panel-attention">
            <AttentionMark person={person} />
            {cell ? <span>The attention mark reflects a public-evidence gap across mature work, not a performance verdict or a judgment about this interval.</span> : <div>
              <strong>Public-evidence gap, not a performance verdict.</strong>
              <p>Through {attentionCohort.as_of}, this person's authored PRs had {number.format(person.attention_context.mature_wpr)} WPR (cohort cutoff: {number.format(attentionCohort.wpr_cutoff)}); qualifying outcomes earned {creditedPoints.format(person.attention_context.mature_score)} points (cohort median: {creditedPoints.format(attentionCohort.impact_cutoff)}). Compared among {attentionCohort.contributors} authors with at least {attentionCohort.minimum_merges} merges. Later work does not affect this mark.</p>
              <p>Examples of demanding PRs with no qualifying outcome link in this snapshot:</p>
              <ul>{person.attention_context.unscored_examples.map((pr) => (
                <li key={pr.number}><a href={pr.url} target="_blank" rel="noopener noreferrer">#{pr.number} {pr.title} ({pr.wpr} WPR) ↗</a></li>
              ))}</ul>
              <p>No linked release or result here does not mean the work was unimportant. WPR estimates review load of authored PRs, not the person's review effort.</p>
            </div>}
          </div>
        )}
        <div className="panel-statline">
          {cell ? <>
            <span>{cell.prs.length} merged PRs in interval</span>
            <span>{cell.wpr == null ? 'WPR pending' : `${number.format(cell.wpr)} WPR on those PRs`}</span>
            <span>{cell.outcomes} supported outcomes</span>
          </> : <>
            <span>{number.format(person.merged_prs)} merged PRs</span>
            <span>{number.format(person.reviewed_prs)} PRs reviewed</span>
            <span>{person.wpr == null ? 'WPR pending' : `${number.format(person.wpr)} WPR on authored PRs`}</span>
          </>}
        </div>
        {cell && <nav className="panel-view-switch" aria-label="Interval detail">
          <button type="button" aria-pressed={!showingReview} onClick={() => onSelectView('outcomes')}>Outcomes <span>{cell.outcomes}</span></button>
          <button type="button" aria-pressed={showingReview} onClick={() => onSelectView('review')}>PR review load <span>{cell.wpr == null ? 'Pending' : number.format(cell.wpr)} WPR</span></button>
        </nav>}
        {notes[person.login] && <p className="panel-summary">{notes[person.login]} These are visible themes, not verified customer results.</p>}
        {showingReview && <PeriodPrBreakdown cell={cell} />}
        {!showingReview && <div className="panel-section">
          <h3>{cell ? `All outcomes in this interval (${cell.outcomes})` : 'Strongest visible outcomes (up to 5)'}</h3>
          {cell && cell.outcomes > 0 && <p className="panel-reconciliation">
            {cell.outcomes} credited outcomes total <strong>{creditedPoints.format(items.reduce((sum, item) => sum + item.credited_points, 0))} pts</strong>. The grid rounds this to {cell.score.toFixed(1)} pts.
          </p>}
          {!cell && person.outcome_count > items.length && <p className="panel-reconciliation">
            These {items.length} outcomes are highlights, not a breakdown of the overall {person.score.toFixed(1)} pts. Select a 14-day cell for its complete list.
          </p>}
          <p className="panel-explainer">A release note confirms inclusion in a release, not usage or customer benefit. A PR-reported metric is not independently verified.</p>
          {shown.length ? shown.map((item) => (
            <article className="evidence-item" key={item.id}>
              <div className="evidence-meta"><span>{item.kind}</span><span>{item.status}</span><span>{creditedPoints.format(item.credited_points)} credited pts</span></div>
              <h4>{item.title}</h4>
              <p>{item.rationale} {item.owners.length > 1 ? `Full outcome: ${creditedPoints.format(item.points)} pts, shared across ${item.owners.length} PR owners.` : ''}</p>
              <div className="evidence-links">
                {item.evidence.map((link) => (
                  <a key={`${link.type}-${link.url}`} href={link.url} target="_blank" rel="noopener noreferrer">
                    {link.type} {link.label} <span aria-hidden="true">↗</span>
                  </a>
                ))}
              </div>
            </article>
          )) : <p className="no-evidence">No outcome in this period meets the public evidence threshold. This does not mean no valuable work happened.</p>}
          {cell && items.length > shown.length && (
            <p className="more-evidence">Showing {shown.length} of {items.length} credited outcomes. <button type="button" onClick={() => setVisibleCount(items.length)}>Show all {items.length} outcomes</button></p>
          )}
        </div>}
      </aside>
    </>
  )
}

export default function App() {
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState('impact')
  const [page, setPage] = useState(1)
  const [attentionOnly, setAttentionOnly] = useState(false)
  const [selected, setSelected] = useState(null)
  const [methodOpen, setMethodOpen] = useState(false)
  const ranked = useMemo(() => {
    const text = search.trim().toLowerCase()
    const result = people
      .filter((person) => person.login.toLowerCase().includes(text))
      .filter((person) => !attentionOnly || person.attention)
      .slice()
    if (sort === 'name') result.sort((a, b) => a.login.localeCompare(b.login))
    if (sort === 'wpr') result.sort((a, b) => (b.wpr ?? -1) - (a.wpr ?? -1) || b.score - a.score)
    return result
  }, [search, sort, attentionOnly])
  const pages = Math.max(1, Math.ceil(ranked.length / PAGE_SIZE))
  const visible = ranked.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
  const rankByLogin = useMemo(() => new Map(people.map((person, index) => [person.login, index + 1])), [])
  const open = (person, index = null, view = 'outcomes') => setSelected({ person, index, view })
  const reset = (setter) => (event) => {
    setter(event.target.value)
    setPage(1)
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand"><span className="brand-mark"><i /><i /><i /></span><span>weave<span className="brand-dot">.</span></span></div>
        <span className="topbar-label">Engineering impact / PostHog</span>
        <a href="https://github.com/PostHog/posthog" target="_blank" rel="noopener noreferrer" className="source-link">Source repository <span aria-hidden="true">↗</span></a>
      </header>

      <main>
        <section className="intro" aria-label="Report overview">
          <div className="intro-copy">
            <h1>Impact, with receipts.</h1>
            <p>Who moved the work forward in PostHog’s public repo—and what can we actually prove?</p>
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
          <div><strong>{number.format(report.manifest.scored_outcomes)}</strong> outcomes with qualifying evidence</div>
          <button className="method-trigger" onClick={() => setMethodOpen(!methodOpen)} aria-expanded={methodOpen}>How this ranking works <span aria-hidden="true">{methodOpen ? '−' : '+'}</span></button>
        </div>
        <p className="coverage-warning"><strong>Read with care.</strong> Only {Math.round(report.manifest.scored_outcomes / report.manifest.outcome_groups * 100)}% of observed change groups have qualifying evidence. Public release notes disproportionately cover Desktop; this is not a company-wide performance assessment.</p>

        {methodOpen && <section className="method-panel" aria-label="Ranking methodology">
          <div><h2>What counts as impact?</h2><p>Distinct outcome clusters with a linked release note, closing issue, or explicit quantitative result. PRs for one issue count once. PR-only descriptions without these signals remain visible but unscored; absence of evidence is not absence of impact.</p></div>
          <div><h2>How are points assigned?</h2><p>A documented improvement scores 1–4 by problem severity and demonstrated change; 5 is reserved for independently verified major outcomes, which this snapshot cannot establish. Multiply by evidence strength (0.5 for PR-reported results; 0.75 for issues/releases). Share clustered outcomes across PR owners. Add all outcomes, with no cap.</p></div>
          <div><h2>What is the attention mark?</h2><p>It invites investigation when review load from PRs 28+ days old is in the upper quartile and supported impact is in the lower half (among authors with 10+ merges). WPR estimates review burden, not engineering effort; it never enters impact. Slush-branch residual work is not subtracted. Private, review-only, and longer-lag work remain under-observed.</p></div>
        </section>}

        <section className="leaderboard" aria-label="Contributor leaderboard">
          <div className="board-heading">
            <div><h2>Leaderboard</h2><p>Top five marked. Every observed human contributor is in the list.</p></div>
            <div className="board-actions">
              <label className="search-wrap">
                <svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="8.8" cy="8.8" r="5.9"/><path d="m13.4 13.4 4.3 4.3"/></svg>
                <span className="sr-only">Search contributors</span>
                <input value={search} onChange={reset(setSearch)} placeholder="Find contributor" type="search" />
              </label>
              <label className="sort-wrap"><span className="sr-only">Sort contributors</span><select value={sort} onChange={reset(setSort)}><option value="impact">Sort: impact</option><option value="wpr">Sort: review load</option><option value="name">Sort: name</option></select></label>
            </div>
          </div>
          <div className="board-filterbar">
            <span>Showing {ranked.length} of {people.length} contributors</span>
            <label className="attention-filter"><input type="checkbox" checked={attentionOnly} onChange={(event) => { setAttentionOnly(event.target.checked); setPage(1) }} /><span>Worth a closer look</span><span className="filter-count">{people.filter((person) => person.attention).length}</span></label>
          </div>

          <div className="table-scroll">
            <table>
              <thead><tr><th className="rank-column" scope="col">Rank</th><th className="person-column" scope="col">Contributor</th>{periods.map((period, index) => <th key={period.end} className={`period-heading ${index === 6 ? 'current-heading' : ''}`} scope="col"><span>{period.label}</span><small>{index === 6 ? 'LATEST' : `${period.start.slice(5)} – ${period.end.slice(5)}`}</small></th>)}</tr></thead>
              <tbody>{visible.map((person) => <tr key={person.login}>
                <td className="rank-column"><RankInsignia rank={rankByLogin.get(person.login)} /></td>
                <th scope="row" className="person-column"><button type="button" className="person-button" onClick={() => open(person)}><span className="person-name">{person.login}<AttentionMark person={person} /></span>{notes[person.login] && <span className="person-note" title={notes[person.login]}>{notes[person.login]}</span>}<span className="person-sub">{person.score.toFixed(1)} evidence pts <span aria-hidden="true">·</span> {person.outcome_count} outcomes</span></button></th>
                {person.periods.map((cell, index) => <td className="timeline-td" key={periods[index].end}><PeriodCell cell={cell} person={person} index={index} onOpen={open} /></td>)}
              </tr>)}</tbody>
            </table>
          </div>
          {!visible.length && <p className="empty-results">No contributors match this view. Try another name or turn off the attention filter.</p>}
          <div className="board-footer">
            <p><span className="legend-swatch" /> Supported outcome <span className="legend-current" /> Latest interval <span className="legend-attention"><AttentionMark person={{ attention: true }} /></span> Worth a closer look</p>
            <nav className="pagination" aria-label="Leaderboard pages"><button onClick={() => setPage(Math.max(1, page - 1))} disabled={page === 1} aria-label="Previous page">←</button><span>Page <strong>{page}</strong> of {pages}</span><button onClick={() => setPage(Math.min(pages, page + 1))} disabled={page === pages} aria-label="Next page">→</button></nav>
          </div>
        </section>
        <footer className="site-footer"><span>Public GitHub evidence, not a performance review.</span><span>Snapshot taken {report.manifest.retrieved_at.slice(0, 10)} UTC · <a href="https://github.com/PostHog/posthog" target="_blank" rel="noopener noreferrer">PostHog/posthog ↗</a></span></footer>
      </main>
      <EvidencePanel
        key={selected ? `${selected.person.login}:${selected.index}:${selected.view}` : 'closed'}
        selected={selected}
        onClose={() => setSelected(null)}
        onSelectView={(view) => setSelected((current) => ({ ...current, view }))}
      />
    </div>
  )
}
