import { useState } from 'react'
import { moldName } from './moldLabel'
import { api, csrfToken } from './liveApi'
import type { LiveMold } from './liveApi'
import MoldMetadataFields from './MoldMetadataFields'
import { metadataForm, metadataPayload } from './moldMetadataForm'

export default function MoldMetadataEditor({ mold, onSaved, onCancel }: { mold: LiveMold; onSaved: () => Promise<void>; onCancel: () => void }) {
  const [value, setValue] = useState(() => metadataForm(mold))
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function save() {
    setBusy(true); setError('')
    try {
      await api(`/molds/${mold.id}/metadata`, { method: 'PATCH', headers: { 'X-CSRF-Token': csrfToken() }, body: JSON.stringify({ ...metadataPayload(value), expected_version: mold.version, reason: reason.trim() }) })
      await onSaved()
    } catch (cause) { setError(cause instanceof Error ? cause.message : '标签资料保存失败') }
    finally { setBusy(false) }
  }
  return <form className="card management-card" onSubmit={(event) => { event.preventDefault(); void save() }}>
    <h2>编辑标签资料 · {moldName(mold)}</h2>
    <p>款号、类别和码数用于识别实物，标签资料可在此补录。</p>
    <MoldMetadataFields value={value} onChange={setValue} />
    <label>修改原因<input value={reason} minLength={3} maxLength={300} required onChange={(event) => setReason(event.target.value)} placeholder="例如：补录厂家提供的标签资料" /></label>
    {error && <p className="live-error" role="alert">{error}</p>}
    <div className="management-editor-actions"><button className="primary-button" disabled={busy}>保存标签资料</button><button className="secondary-button" type="button" disabled={busy} onClick={onCancel}>取消</button></div>
  </form>
}
