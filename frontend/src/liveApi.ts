export interface SessionUser { id: number; username: string; role: string; person: string | null }
export interface Location { id: number; code: string; name: string; type: string; zone: string | null; rack: string | null; level: string | null; active: boolean }
export interface LiveMold { id: number; code: string; set_code: string; model_code: string; name: string; size_label: string; status: string; version: number; current_location_id: number; current_location: string; default_location_id: number; default_location: string; custodian: string | null }
export interface LiveOperation { id: number; request_id: string; type: string; actor_name: string; target_location_code: string; reason: string | null; correction_of_operation_id?: number | null; created_at: string; items: { mold_code: string; before_status: string; after_status: string; before_location_id: number | null; after_location_id: number; note: string | null }[] }
export interface MoldPage { total: number; items: LiveMold[] }
export interface DashboardSummary { total_molds: number; ready_molds: number; in_use_molds: number; exception_molds: number; ready_sets: number; total_sets: number }
export interface SetSummary { set_id: number; set_code: string; name: string; model_code: string; default_location: string; complete: boolean; items: LiveMold[] }
export interface LineSummary { line_id: number; line_code: string; sets: { set_code: string; name: string; mold_count: number; sizes: string[]; custodians: string[] }[] }

export const stateNames: Record<string, string> = { NOT_REGISTERED: '未建档', READY: '在库可用', IN_USE: '产线领用', PENDING_INSPECTION: '待检', IN_REPAIR: '维修中', UNVERIFIED: '待核查', SCRAPPED: '已报废' }
export const kindNames: Record<string, string> = { INITIALIZE: '初始建档', ISSUE: '领用', RETURN: '归还', MOVE: '移库', TRANSFER: '转线', CORRECTION: '补偿更正', STOCKTAKE_ADJUST: '盘点调整', RETURN_FOR_INSPECTION: '异常归还待检', SEND_REPAIR: '送修', REPAIR_COMPLETE: '维修完成', INSPECTION_PASS: '检验通过', SCRAP: '报废', FOUND: '核查找回' }

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api${path}`, { credentials: 'same-origin', ...init, headers: { 'Content-Type': 'application/json', ...init?.headers } })
  } catch {
    throw new Error('无法连接仓库服务。请先启动后端，再刷新页面。')
  }
  if (!response.ok) {
    if ([502, 503, 504].includes(response.status)) {
      throw new Error(`仓库服务未启动或暂时不可用，请启动仓库服务后重试（${response.status}）`)
    }
    const body = await response.json().catch(() => null) as { detail?: { message?: string } } | null
    throw new Error(body?.detail?.message ?? `请求失败（${response.status}）`)
  }
  return response.json() as Promise<T>
}

export function csrfToken() {
  return document.cookie.split('; ').find((part) => part.startsWith('warehouse_csrf='))?.split('=')[1] ?? ''
}

export function localTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' }).format(new Date(value)).replaceAll('/', '-')
}
