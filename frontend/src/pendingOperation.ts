export interface OperationPayload {
  request_id: string
  type: 'ISSUE' | 'RETURN' | 'MOVE' | 'TRANSFER'
  target_location_id: number
  items: { mold_id: number; expected_version: number; return_condition?: 'READY' | 'PENDING_INSPECTION' | 'IN_REPAIR'; exception_location_id?: number | null; note?: string | null }[]
}

function key(userId: number, client: 'work' | 'mobile') { return `warehouse-${client}-pending-${userId}` }

export function readPending(userId: number, client: 'work' | 'mobile'): OperationPayload | null {
  const raw = localStorage.getItem(key(userId, client))
  if (!raw) return null
  const payload = JSON.parse(raw) as OperationPayload
  if (!payload.request_id || !['ISSUE', 'RETURN', 'MOVE', 'TRANSFER'].includes(payload.type) || !Number.isInteger(payload.target_location_id) || !Array.isArray(payload.items) || !payload.items.length || payload.items.some((item) => !Number.isInteger(item.mold_id) || !Number.isInteger(item.expected_version))) throw new Error('待确认请求读取失败，请保留浏览器数据并人工核对原单据')
  return payload
}

export function rememberPending(userId: number, client: 'work' | 'mobile', payload: OperationPayload) {
  // Persist before sending. If storage fails, no inventory request is issued.
  localStorage.setItem(key(userId, client), JSON.stringify(payload))
}

export function clearPending(userId: number, client: 'work' | 'mobile') { localStorage.removeItem(key(userId, client)) }
