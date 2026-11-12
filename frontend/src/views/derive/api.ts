/** 推导证据接口的类型定义与请求封装，供数据标签、数据筛选两个模块共用。 */
import { request } from '@/api/client'

export interface FieldCatalogItem {
  key: string
  label: string
  source: string
  kind: string
}

export interface SampleObject {
  id: number
  客户编号: string
  客户名称: string
  城市: string | null
  会员等级: string | null
  风控等级: string | null
  近30天消费金额: number | null
  近90天登录次数: number | null
  最近联系日期: string | null
  是否企业客户: boolean | null
}

export interface FieldTrace {
  label: string
  key: string
  source: string
  value: unknown
  isNull: boolean
}

export interface RuleSnapshot {
  ruleId: number
  ruleCode: string
  version: number
  status: string
  conditionText: string
}

export interface TraceNode {
  kind: 'compare' | 'logic' | 'rule'
  hit: boolean
  text: string
  field?: FieldTrace
  op?: string
  expected?: unknown
  valueNote?: string
  ruleCode?: string
  ruleMissing?: boolean
  snapshot?: RuleSnapshot
  jump?: { module: string; ruleId: number; version: number }
  statusNote?: string
  steps?: TraceNode[]
}

export interface RunResult {
  objectId: string
  objectLabel: string
  hit: boolean
  trace: TraceNode
}

export interface RunPayload {
  runId: string
  ranAt: string
  version: number
  expression?: string
  conditionText?: string
  status?: string
  ruleCode?: string
  tagCode?: string
  tagName?: string
  identityMap?: Record<string, string>
  coverageCount: number
  totalCount: number
  results: RunResult[]
}

export interface StaleNote {
  ruleCode: string
  snapshotVersion: number
  currentVersion: number | null
  snapshotStatus: string
  currentStatus: string | null
  stale: boolean
  reason: string
  jump: { module: string; ruleId: number; version: number }
}

export interface Explanation {
  explId: string
  scope: string
  ownerId: number
  version: number
  objectId: string
  objectLabel: string
  hit: boolean
  trace: TraceNode
  expression?: string
  runId: string
  confirmedAt: string
  confirmedBy: string
  evidenceState: string
  staleNotes: StaleNote[]
}

export interface TagVersion {
  version: number
  expression: string
  createdAt: string
  note: string
  identityMap: Record<string, string>
}

export interface TagBoard {
  tagId: number
  tagCode?: string
  legacy: boolean
  message: string
  currentVersion?: number
  versions: TagVersion[]
  explanations: Explanation[]
}

export interface FilterCondition {
  ruleId: number
  ruleCode?: string
  version: number
  status?: string
  identityMap: Record<string, string>
  conditionText: string
  revisions: { version: number; conditionText: string; changedAt: string; note: string }[]
}

export interface AmbiguityCandidate {
  key: string
  label: string
  source: string
  kind: string
}

export interface Ambiguity {
  field: string
  candidates: AmbiguityCandidate[]
}

export interface ApiErrorDetail {
  message?: string
  ambiguities?: Ambiguity[]
}

/** 统一取错误体：409 的 detail 是对象，其余多为字符串。 */
export async function readError(response: Response): Promise<{ message: string; ambiguities: Ambiguity[] }> {
  let detail: unknown
  try {
    detail = (await response.json()).detail
  } catch {
    detail = '请求失败，请稍后重试'
  }
  if (typeof detail === 'string') {
    return { message: detail, ambiguities: [] }
  }
  const obj = detail as ApiErrorDetail
  return { message: obj.message ?? '请求失败，请稍后重试', ambiguities: obj.ambiguities ?? [] }
}

async function getJson<T>(path: string): Promise<T> {
  const response = await request(path)
  if (!response.ok) {
    const err = await readError(response)
    throw new Error(err.message)
  }
  return (await response.json()) as T
}

export const deriveApi = {
  catalog: () => getJson<{ fields: FieldCatalogItem[] }>('/api/derive/catalog'),
  samples: () => getJson<{ items: SampleObject[] }>('/api/derive/samples'),
  patchSample: (objectId: string, values: Partial<SampleObject>) =>
    request(`/api/derive/samples/${encodeURIComponent(objectId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ values }),
    }),
  resetSamples: () => request('/api/derive/samples/reset', { method: 'POST' }),
  resetAll: () => request('/api/derive/reset', { method: 'POST' }),

  filterCondition: (ruleId: number) => getJson<FilterCondition>(`/api/derive/filter/${ruleId}/condition`),
  putFilterCondition: (ruleId: number, conditionText: string, identityMap: Record<string, string>, note?: string) =>
    request(`/api/derive/filter/${ruleId}/condition`, {
      method: 'PUT',
      body: JSON.stringify({ conditionText, identityMap, note }),
    }),
  filterTrial: (ruleId: number, objectId?: string) =>
    getJson<RunPayload>(`/api/derive/filter/${ruleId}/trial${objectId ? `?object_id=${encodeURIComponent(objectId)}` : ''}`),
  filterRuns: (ruleId: number) =>
    getJson<{ items: { runId: string; ranAt: string; version: number; expression?: string; coverageCount: number; totalCount: number }[] }>(
      `/api/derive/filter/${ruleId}/runs`,
    ),
  filterConfirm: (ruleId: number, body: { runId: string; objectId?: string; all?: boolean; confirmedBy?: string }) =>
    request(`/api/derive/filter/${ruleId}/confirm`, { method: 'POST', body: JSON.stringify(body) }),
  filterExplanations: (ruleId: number, version?: number) =>
    getJson<{ items: Explanation[] }>(
      `/api/derive/filter/${ruleId}/explanations${version ? `?version=${version}` : ''}`,
    ),

  tagBoard: (tagId: number, version?: number) =>
    getJson<TagBoard>(`/api/derive/tag/${tagId}/board${version ? `?version=${version}` : ''}`),
  createTagVersion: (tagId: number, expression: string, identityMap: Record<string, string>, note?: string) =>
    request(`/api/derive/tag/${tagId}/version`, {
      method: 'POST',
      body: JSON.stringify({ expression, identityMap, note }),
    }),
  recompute: (tagId: number, body: { version?: number; objectId?: string; identityMap?: Record<string, string> }) =>
    request(`/api/derive/tag/${tagId}/recompute`, { method: 'POST', body: JSON.stringify(body) }),
  tagRuns: (tagId: number) =>
    getJson<{ items: { runId: string; ranAt: string; version: number; expression?: string; coverageCount: number; totalCount: number }[] }>(
      `/api/derive/tag/${tagId}/runs`,
    ),
  tagRunDetail: (tagId: number, runId: string) => getJson<RunPayload>(`/api/derive/tag/${tagId}/runs/${runId}`),
  tagConfirm: (tagId: number, body: { runId: string; objectId?: string; all?: boolean; confirmedBy?: string }) =>
    request(`/api/derive/tag/${tagId}/confirm`, { method: 'POST', body: JSON.stringify(body) }),
}
