import './scoreExplainers.css'

const sourceBase = 'https://github.com/riescheung/public-pr-review-load/blob/qwen-dashboard-results-20261109'

function GuideHeading({ title, description }) {
  return (
    <summary className="score-guide-toggle">
      <span><strong>{title}</strong><span>{description}</span></span>
      <svg viewBox="0 0 20 20" aria-hidden="true" focusable="false">
        <path d="m7 4 6 6-6 6" />
      </svg>
    </summary>
  )
}

export default function ScoreExplainers() {
  return (
    <div className="score-guides">
      <details className="score-guide" id="weighted-pr-guide">
        <GuideHeading
          title="What does weighted PR mean?"
          description="WPR estimates review load from changed files. It is not an impact score."
        />
        <div className="score-guide-body">
          <h3>Not every PR contains the same amount of review work.</h3>
          <p>Weighted PR (WPR) uses a fixed formula, not an AI reviewer. It looks at the size and type of file changes, not what the code means.</p>
          <figure className="score-guide-diagram">
            <ol className="score-guide-flow">
              <li><strong>Changed files</strong><span>File type, added/deleted lines and whether files were added, changed or removed</span></li>
              <li><strong>Fixed weighting rules</strong><span>Code, tests and docs count differently; generated files and assets are excluded</span></li>
              <li className="score-guide-result"><strong>0–10 WPR per PR</strong><span>A capped estimate of review load, not hours spent or value delivered</span></li>
            </ol>
            <figcaption>Trivial edits and net reverts receive zero. Config-heavy PRs get an adjusted weight. More changed files can increase the estimate.</figcaption>
          </figure>
          <figure className="score-guide-example">
            <figcaption>Illustrative table cell: three merged PRs in one period</figcaption>
            <div className="score-guide-equation" aria-label="2 WPR plus 5 WPR plus 1 WPR equals 8 WPR across 3 merged PRs">
              <span><b>2</b><small>PR A · WPR</small></span>
              <i aria-hidden="true">+</i>
              <span><b>5</b><small>PR B · WPR</small></span>
              <i aria-hidden="true">+</i>
              <span><b>1</b><small>PR C · WPR</small></span>
              <i aria-hidden="true">=</i>
              <span className="score-guide-total"><b>8 WPR</b><small>3 merged PRs</small></span>
            </div>
            <p>The table adds per-PR WPR for each contributor and period. A total can exceed 10 because the cap applies to each PR, not the total.</p>
          </figure>
          <p className="score-guide-limit"><strong>More WPR does not mean more impact.</strong> It can reflect more PRs or larger changes. It does not establish effort, code quality, adoption or customer benefit.</p>
          <a className="score-guide-source" href={`${sourceBase}/scripts/weighted_pr.py`} target="_blank" rel="noopener noreferrer">Inspect the WPR formula</a>
        </div>
      </details>

      <details className="score-guide" id="ai-reviewer-guide">
        <GuideHeading
          title="What does the AI reviewer mean?"
          description="Qwen reads changed code and estimates a scope tier, with an explanation and quotes."
        />
        <div className="score-guide-body">
          <h3>Qwen asks: what change does this code demonstrate?</h3>
          <p>Related PRs are reviewed as one change group. Qwen sees the changed code, the tier rubric and PostHog context, but not the author, PR title or WPR.</p>
          <figure className="score-guide-diagram">
            <ol className="score-guide-flow">
              <li><strong>Read the code in pieces</strong><span>A large diff is split without cutting changed-code blocks in half. Qwen writes observations for each piece.</span></li>
              <li><strong>Combine all observations</strong><span>Our Python program puts every note, code quote and limitation into one message to the same Qwen model.</span></li>
              <li className="score-guide-result"><strong>One tier + explanation</strong><span>Qwen reads the combined notes, selects 1, 2, 3 or abstains, then writes a cited explanation.</span></li>
            </ol>
            <figcaption>The pieces do not vote, and their scores are not averaged. There is one final decision per group. Missed context or a mistaken observation can still lead to a wrong answer.</figcaption>
          </figure>
          <dl className="score-guide-tiers">
            <div><dt>Tier 1</dt><dd>Narrow maintenance, docs, tests or a small behaviour correction</dd></div>
            <div><dt>Tier 2</dt><dd>A substantive, bounded capability or correctness/reliability improvement</dd></div>
            <div><dt>Tier 3</dt><dd>Broader capability or systemic risk reduction, demonstrated across components or critical paths with appropriate checks</dd></div>
            <div><dt>Abstain</dt><dd>Not enough evidence to justify a tier. Unassessed, not zero.</dd></div>
          </dl>
          <figure className="score-guide-diagram">
            <ol className="score-guide-flow">
              <li><strong>Qwen's draft</strong><span>A numeric tier or abstention, an explanation and cited evidence</span></li>
              <li><strong>Python checks</strong><span>Required fields, literal code quotes, evidence IDs and specific tier/wording conflicts</span></li>
              <li className="score-guide-result"><strong>Save the result</strong><span>Accepted tier, valid abstention or rejected answer. A wording conflict allows one reconsideration.</span></li>
            </ol>
            <figcaption>Python is ordinary code we wrote, not another AI judge. It can reject tier 2 beside “No score can be assigned.” It cannot establish that the code deserves tier 2.</figcaption>
          </figure>
          <figure className="score-guide-example">
            <figcaption>Illustrative AI estimate: average only the groups with accepted tiers</figcaption>
            <div className="score-guide-average">
              <div><strong>Tier 2 + tier 1</strong><span>2 scored groups</span></div>
              <span aria-hidden="true">=</span>
              <div className="score-guide-total"><strong>1.5/3</strong><span>(2 + 1) ÷ 2</span></div>
              <div className="score-guide-unassessed"><strong>1 abstention</strong><span>Excluded from the mean</span></div>
            </div>
            <p>Coverage is 2 of 3 groups scored. Unlike WPR, the AI estimate is a mean, not a total. Neither WPR nor confidence weights this mean.</p>
          </figure>
          <p className="score-guide-limit"><strong>Consistent does not mean correct.</strong> This experimental model was fine-tuned on AI-proposed examples, not human-verified truth. Scoring does not retrain it. Its tiers are not verified business impact or individual performance.</p>
          <a className="score-guide-source" href={`${sourceBase}/BENCHMARK.md`} target="_blank" rel="noopener noreferrer">Read the review method and model limitations</a>
        </div>
      </details>
    </div>
  )
}
