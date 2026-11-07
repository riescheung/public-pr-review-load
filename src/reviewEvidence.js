export async function loadReviewRecord(entry, {
  baseUrl = '/', fetcher = globalThis.fetch, signal,
} = {}) {
  if (Object.prototype.hasOwnProperty.call(entry, 'review')) return entry
  const expected = entry.evidence_sha256
  if (!/^[0-9a-f]{64}$/.test(expected || '')) {
    throw new Error('Cited review failed integrity verification.')
  }
  const base = baseUrl.endsWith('/') ? baseUrl : `${baseUrl}/`
  const response = await fetcher(`${base}review-evidence/${expected}.json`, { signal })
  if (!response.ok) throw new Error('Cited review could not be loaded.')
  const bytes = await response.arrayBuffer()
  const actual = Array.from(new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256', bytes)),
    byte => byte.toString(16).padStart(2, '0')).join('')
  if (actual !== expected) throw new Error('Cited review failed integrity verification.')
  const record = JSON.parse(new TextDecoder().decode(bytes))
  const fields = ['id', 'run', 'source', 'status', 'tier', 'known_calibration']
  if (fields.some(field => record[field] !== entry[field])
      || JSON.stringify(record.prs) !== JSON.stringify(entry.prs)) {
    throw new Error('Cited review metadata does not match its index.')
  }
  return record
}
