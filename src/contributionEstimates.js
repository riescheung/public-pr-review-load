export function estimateValue(summary) {
  if (summary?.scored > 0 && Number.isFinite(summary.mean_tier)
      && summary.mean_tier >= 1 && summary.mean_tier <= 3) {
    return `${summary.mean_tier.toFixed(1)}/3`
  }
  if (summary?.abstained || summary?.failed) return 'Unassessed'
  if (summary?.groups && summary.reserved === summary.groups) return 'Reserved'
  if (summary && !summary.groups && !summary.unmapped_prs) return 'No changes'
  return 'Pending'
}
