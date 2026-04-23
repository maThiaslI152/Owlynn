import { useMemo, useState } from 'react'
import { useAppStore } from '../state/useAppStore'

interface VerifyReport {
  schema_version: 'owlynn.audit.verify-report.v1'
  ts: number
  status: 'pass' | 'fail'
  reason: string
  records_checked: number
  root_hash?: string
  manifest_file?: string
  bundle_file?: string
  trace?: string[]
}

export function ToolExecutionPanel() {
  const tool = useAppStore((s) => s.latestToolExecution)
  const history = useAppStore((s) => s.toolExecutionHistory)
  const setOperatorNote = useAppStore((s) => s.setOperatorNote)
  const [filter, setFilter] = useState<'all' | 'risky' | 'error'>('all')
  const [signingKeyId, setSigningKeyId] = useState('')
  const [signingSecret, setSigningSecret] = useState('')
  const [verifyManifestFile, setVerifyManifestFile] = useState<File | null>(null)
  const [verifyJsonlFile, setVerifyJsonlFile] = useState<File | null>(null)
  const [verifySecret, setVerifySecret] = useState('')
  const [lastVerifyReport, setLastVerifyReport] = useState<VerifyReport | null>(null)

  const filteredHistory = useMemo(() => {
    if (filter === 'risky') return history.filter((entry) => Boolean(entry.riskLabel))
    if (filter === 'error') return history.filter((entry) => entry.status === 'error')
    return history
  }, [filter, history])

  const formatTs = (ts: number) => new Date(ts).toLocaleTimeString()
  const formatDuration = (duration?: number) =>
    typeof duration === 'number' ? `${Math.round(duration * 1000)}ms` : 'n/a'

  const toHex = (bytes: Uint8Array) => [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('')

  const exportAuditJsonl = async () => {
    if (filteredHistory.length === 0) {
      setOperatorNote('Audit export skipped: no tool events in current filter.')
      return
    }

    const encoder = new TextEncoder()
    const rows: string[] = []
    let prevHash = '0'.repeat(64)
    const exportTs = Date.now()

    for (let i = 0; i < filteredHistory.length; i += 1) {
      const entry = filteredHistory[i]
      const canonical = {
        schema_version: 'owlynn.audit.tool_execution.v1',
        export_ts: exportTs,
        sequence: i + 1,
        ts: entry.ts,
        tool_name: entry.toolName,
        tool_call_id: entry.toolCallId ?? null,
        status: entry.status,
        duration: entry.duration ?? null,
        risk_label: entry.riskLabel ?? null,
        risk_confidence: entry.riskConfidence ?? null,
        risk_rationale: entry.riskRationale ?? null,
        remediation_hint: entry.remediationHint ?? null,
      }
      const canonicalString = JSON.stringify(canonical)
      const hashInput = `${prevHash}:${canonicalString}`
      const digest = await crypto.subtle.digest('SHA-256', encoder.encode(hashInput))
      const entryHash = toHex(new Uint8Array(digest))
      rows.push(
        JSON.stringify({
          ...canonical,
          prev_hash: prevHash,
          entry_hash: entryHash,
        })
      )
      prevHash = entryHash
    }

    const blob = new Blob([rows.join('\n')], { type: 'application/x-ndjson' })
    const bundleName = `owlynn-tool-audit-${exportTs}.jsonl`
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = bundleName
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)

    const manifestBase = {
      schema_version: 'owlynn.audit.manifest.v1',
      export_ts: exportTs,
      session_id: crypto.randomUUID(),
      records_count: rows.length,
      filter: filter,
      bundle_file: bundleName,
      root_hash: prevHash,
      chain_algo: 'sha256',
      signature_scheme: signingKeyId && signingSecret ? 'hmac-sha256' : 'sha256-manifest-digest',
    }
    const manifestCanonical = JSON.stringify(manifestBase)
    const manifestDigest = await crypto.subtle.digest('SHA-256', encoder.encode(manifestCanonical))
    const manifestHash = toHex(new Uint8Array(manifestDigest))
    let manifestSignature: string | null = null
    if (signingKeyId && signingSecret) {
      const hmacKey = await crypto.subtle.importKey(
        'raw',
        encoder.encode(signingSecret),
        { name: 'HMAC', hash: 'SHA-256' },
        false,
        ['sign']
      )
      const sig = await crypto.subtle.sign('HMAC', hmacKey, encoder.encode(manifestCanonical))
      manifestSignature = toHex(new Uint8Array(sig))
    }
    const manifest = {
      ...manifestBase,
      signing_key_id: signingKeyId || null,
      manifest_hash: manifestHash,
      manifest_signature: manifestSignature,
    }
    const manifestBlob = new Blob([JSON.stringify(manifest, null, 2)], { type: 'application/json' })
    const manifestUrl = URL.createObjectURL(manifestBlob)
    const manifestAnchor = document.createElement('a')
    manifestAnchor.href = manifestUrl
    manifestAnchor.download = `${bundleName}.manifest.json`
    document.body.appendChild(manifestAnchor)
    manifestAnchor.click()
    manifestAnchor.remove()
    URL.revokeObjectURL(manifestUrl)

    setOperatorNote(
      `Audit export complete: ${rows.length} events, tip hash ${prevHash.slice(0, 12)}..., manifest ${manifestHash.slice(0, 12)}...${manifestSignature ? ' signed' : ''}`
    )
  }

  const copyVerifySnippet = async () => {
    const snippet = `import { readFileSync } from 'node:fs'
import { createHash, createHmac } from 'node:crypto'

const manifest = JSON.parse(readFileSync(process.argv[2], 'utf8'))
const rows = readFileSync(process.argv[3], 'utf8').trim().split('\\n').filter(Boolean).map((line) => JSON.parse(line))

let prev = '0'.repeat(64)
for (const row of rows) {
  const canonical = {
    schema_version: row.schema_version,
    export_ts: row.export_ts,
    sequence: row.sequence,
    ts: row.ts,
    tool_name: row.tool_name,
    tool_call_id: row.tool_call_id,
    status: row.status,
    duration: row.duration,
    risk_label: row.risk_label,
    risk_confidence: row.risk_confidence,
    risk_rationale: row.risk_rationale,
    remediation_hint: row.remediation_hint,
  }
  const expected = createHash('sha256').update(\`\${prev}:\${JSON.stringify(canonical)}\`).digest('hex')
  if (row.prev_hash !== prev || row.entry_hash !== expected) throw new Error('Hash chain verification failed')
  prev = row.entry_hash
}
if (manifest.root_hash !== prev) throw new Error('Manifest root hash mismatch')
if (manifest.signature_scheme === 'hmac-sha256') {
  const secret = process.argv[4]
  const manifestBase = {
    schema_version: manifest.schema_version,
    export_ts: manifest.export_ts,
    session_id: manifest.session_id,
    records_count: manifest.records_count,
    filter: manifest.filter,
    bundle_file: manifest.bundle_file,
    root_hash: manifest.root_hash,
    chain_algo: manifest.chain_algo,
    signature_scheme: manifest.signature_scheme,
  }
  const sig = createHmac('sha256', secret).update(JSON.stringify(manifestBase)).digest('hex')
  if (sig !== manifest.manifest_signature) throw new Error('Manifest signature mismatch')
}
console.log('Verification OK')
`
    await navigator.clipboard.writeText(snippet)
    setOperatorNote('Copied offline audit verification snippet to clipboard.')
  }

  const verifyBundle = async () => {
    if (!verifyManifestFile || !verifyJsonlFile) {
      setOperatorNote('Verify failed: select both manifest and JSONL files.')
      return
    }
    try {
      const encoder = new TextEncoder()
      const trace: string[] = []
      const manifestRaw = await verifyManifestFile.text()
      const jsonlRaw = await verifyJsonlFile.text()
      trace.push('loaded files')
      const manifest = JSON.parse(manifestRaw) as {
        schema_version?: string
        export_ts?: number
        session_id?: string
        records_count?: number
        filter?: string
        bundle_file?: string
        root_hash?: string
        chain_algo?: string
        signature_scheme?: string
        manifest_hash?: string
        manifest_signature?: string | null
      }
      const rows = jsonlRaw
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean)
        .map((line) => JSON.parse(line) as Record<string, unknown>)
      trace.push(`parsed ${rows.length} rows`)

      const toHex = (bytes: Uint8Array) => [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('')
      let prev = '0'.repeat(64)
      for (const row of rows) {
        const canonical = {
          schema_version: row.schema_version,
          export_ts: row.export_ts,
          sequence: row.sequence,
          ts: row.ts,
          tool_name: row.tool_name,
          tool_call_id: row.tool_call_id,
          status: row.status,
          duration: row.duration,
          risk_label: row.risk_label,
          risk_confidence: row.risk_confidence,
          risk_rationale: row.risk_rationale,
          remediation_hint: row.remediation_hint,
        }
        const digest = await crypto.subtle.digest(
          'SHA-256',
          encoder.encode(`${prev}:${JSON.stringify(canonical)}`)
        )
        const expected = toHex(new Uint8Array(digest))
        if (row.prev_hash !== prev || row.entry_hash !== expected) {
          const reason = `Hash chain verification failed at sequence ${String(row.sequence)}`
          setLastVerifyReport({
            schema_version: 'owlynn.audit.verify-report.v1',
            ts: Date.now(),
            status: 'fail',
            reason,
            records_checked: Number(row.sequence ?? 0),
            root_hash: prev,
            manifest_file: verifyManifestFile.name,
            bundle_file: verifyJsonlFile.name,
            trace: [...trace, `expected entry_hash=${expected.slice(0, 12)}...`, `actual entry_hash=${String(row.entry_hash).slice(0, 12)}...`],
          })
          throw new Error(reason)
        }
        prev = String(row.entry_hash)
      }
      trace.push('hash chain validated')
      if (manifest.root_hash !== prev) {
        const reason = 'Manifest root hash mismatch'
        setLastVerifyReport({
          schema_version: 'owlynn.audit.verify-report.v1',
          ts: Date.now(),
          status: 'fail',
          reason,
          records_checked: rows.length,
          root_hash: prev,
          manifest_file: verifyManifestFile.name,
          bundle_file: verifyJsonlFile.name,
          trace: [...trace, `expected root=${String(manifest.root_hash).slice(0, 12)}...`, `actual root=${prev.slice(0, 12)}...`],
        })
        throw new Error(reason)
      }
      trace.push('manifest root hash validated')

      const manifestBase = {
        schema_version: manifest.schema_version,
        export_ts: manifest.export_ts,
        session_id: manifest.session_id,
        records_count: manifest.records_count,
        filter: manifest.filter,
        bundle_file: manifest.bundle_file,
        root_hash: manifest.root_hash,
        chain_algo: manifest.chain_algo,
        signature_scheme: manifest.signature_scheme,
      }
      const manifestDigest = await crypto.subtle.digest(
        'SHA-256',
        encoder.encode(JSON.stringify(manifestBase))
      )
      const manifestHash = toHex(new Uint8Array(manifestDigest))
      if (manifest.manifest_hash !== manifestHash) {
        const reason = 'Manifest digest mismatch'
        setLastVerifyReport({
          schema_version: 'owlynn.audit.verify-report.v1',
          ts: Date.now(),
          status: 'fail',
          reason,
          records_checked: rows.length,
          root_hash: prev,
          manifest_file: verifyManifestFile.name,
          bundle_file: verifyJsonlFile.name,
          trace: [...trace, `expected digest=${String(manifest.manifest_hash).slice(0, 12)}...`, `actual digest=${manifestHash.slice(0, 12)}...`],
        })
        throw new Error(reason)
      }
      trace.push('manifest digest validated')
      if (manifest.signature_scheme === 'hmac-sha256') {
        if (!verifySecret) throw new Error('Missing HMAC secret for signed manifest verification')
        const key = await crypto.subtle.importKey(
          'raw',
          encoder.encode(verifySecret),
          { name: 'HMAC', hash: 'SHA-256' },
          false,
          ['sign']
        )
        const sig = await crypto.subtle.sign('HMAC', key, encoder.encode(JSON.stringify(manifestBase)))
        const expectedSig = toHex(new Uint8Array(sig))
        if (manifest.manifest_signature !== expectedSig) {
          const reason = 'Manifest signature mismatch'
          setLastVerifyReport({
            schema_version: 'owlynn.audit.verify-report.v1',
            ts: Date.now(),
            status: 'fail',
            reason,
            records_checked: rows.length,
            root_hash: prev,
            manifest_file: verifyManifestFile.name,
            bundle_file: verifyJsonlFile.name,
            trace: [...trace, `expected sig=${expectedSig.slice(0, 12)}...`, `actual sig=${String(manifest.manifest_signature).slice(0, 12)}...`],
          })
          throw new Error(reason)
        }
        trace.push('manifest signature validated')
      }

      setOperatorNote(`Verify OK: ${rows.length} records, root ${prev.slice(0, 12)}...`)
      setLastVerifyReport({
        schema_version: 'owlynn.audit.verify-report.v1',
        ts: Date.now(),
        status: 'pass',
        reason: 'Verification completed successfully.',
        records_checked: rows.length,
        root_hash: prev,
        manifest_file: verifyManifestFile.name,
        bundle_file: verifyJsonlFile.name,
        trace,
      })
    } catch (error) {
      const reason = (error as Error).message
      setOperatorNote(`Verify failed: ${reason}`)
      setLastVerifyReport((existing) =>
        existing && existing.status === 'fail'
          ? existing
          : {
              schema_version: 'owlynn.audit.verify-report.v1',
              ts: Date.now(),
              status: 'fail',
              reason,
              records_checked: 0,
              manifest_file: verifyManifestFile.name,
              bundle_file: verifyJsonlFile.name,
              trace: ['verification aborted before detailed trace was captured'],
            }
      )
    }
  }

  const exportVerifyReport = () => {
    if (!lastVerifyReport) {
      setOperatorNote('No verification report available to export.')
      return
    }
    const filename = `owlynn-verify-report-${lastVerifyReport.ts}.json`
    const blob = new Blob([JSON.stringify(lastVerifyReport, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
    setOperatorNote(`Verification report exported: ${filename}`)
  }

  return (
    <section className="tool-execution">
      <h3>Tool Execution</h3>
      <div className="row">
        <button type="button" onClick={() => setFilter('all')}>
          all
        </button>
        <button type="button" onClick={() => setFilter('risky')}>
          risky
        </button>
        <button type="button" onClick={() => setFilter('error')}>
          error
        </button>
        <button type="button" onClick={() => void exportAuditJsonl()}>
          export-jsonl
        </button>
        <button type="button" onClick={() => void copyVerifySnippet()}>
          copy-verify-js
        </button>
      </div>
      <label>
        signing key id (optional)
        <input
          value={signingKeyId}
          onChange={(e) => setSigningKeyId(e.target.value)}
          placeholder="operator-key-1"
        />
      </label>
      <label>
        signing secret (optional)
        <input
          type="password"
          value={signingSecret}
          onChange={(e) => setSigningSecret(e.target.value)}
          placeholder="hmac secret"
        />
      </label>
      <label>
        verify manifest file
        <input
          type="file"
          accept=".json,.manifest.json"
          onChange={(e) => setVerifyManifestFile(e.target.files?.[0] ?? null)}
        />
      </label>
      <label>
        verify jsonl file
        <input
          type="file"
          accept=".jsonl,.ndjson"
          onChange={(e) => setVerifyJsonlFile(e.target.files?.[0] ?? null)}
        />
      </label>
      <label>
        verify secret (only for signed manifests)
        <input
          type="password"
          value={verifySecret}
          onChange={(e) => setVerifySecret(e.target.value)}
          placeholder="hmac secret"
        />
      </label>
      <div className="row">
        <button type="button" onClick={() => void verifyBundle()}>
          verify-bundle
        </button>
        <button type="button" onClick={exportVerifyReport}>
          export-verify-report
        </button>
      </div>
      {lastVerifyReport ? (
        <p className="meta">
          Last verify: {lastVerifyReport.status} · {new Date(lastVerifyReport.ts).toLocaleTimeString()}
        </p>
      ) : null}
      {!tool ? (
        <p className="meta">No tool activity yet.</p>
      ) : (
        <>
          <p className="meta">
            Status: <span className={`badge badge-${tool.status}`}>{tool.status}</span>
          </p>
          <p className="meta">Tool: {tool.toolName}</p>
          <p className="meta">Time: {formatTs(tool.ts)}</p>
          <p className="meta">Duration: {formatDuration(tool.duration)}</p>
          {tool.input ? <p className="meta">Input: {tool.input.slice(0, 180)}</p> : null}
          {tool.riskLabel ? <p className="meta">Risk: {tool.riskLabel}</p> : null}
          {typeof tool.riskConfidence === 'number' ? (
            <p className="meta">Confidence: {Math.round(tool.riskConfidence * 100)}%</p>
          ) : null}
          {tool.riskRationale ? <p className="meta">Rationale: {tool.riskRationale}</p> : null}
          {tool.remediationHint ? <p className="meta">Mitigation: {tool.remediationHint}</p> : null}
        </>
      )}
      {filteredHistory.length > 0 ? (
        <div className="tool-history">
          {filteredHistory.slice(0, 8).map((entry, idx) => (
            <article key={`${entry.toolCallId ?? entry.toolName}-${idx}`} className="proposal-item">
              <p className="meta">
                <span className={`badge badge-${entry.status}`}>{entry.status}</span> {entry.toolName}
              </p>
              <p className="meta">
                {formatTs(entry.ts)} · {formatDuration(entry.duration)}
              </p>
              {entry.riskLabel ? <p className="meta">Risk: {entry.riskLabel}</p> : null}
            </article>
          ))}
        </div>
      ) : null}
    </section>
  )
}
