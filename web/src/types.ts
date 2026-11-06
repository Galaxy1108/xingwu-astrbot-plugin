/** 与 docs/API.md 对齐的前端类型定义。字段变更必须同步契约。 */

export type Role = 'user' | 'admin'
export type UserStatus = 'active' | 'disabled' | 'deleted'
export type Platform = 'weixin_oc' | 'qq_official'
export type BotStatus = 'creating' | 'pending_qr' | 'ready' | 'disabled' | 'deleting' | 'deleted'
export type QrStatus = 'pending' | 'scanned' | 'created' | 'expired'
export type EncryptionState =
  | 'encrypted'
  | 'decrypting'
  | 'decrypted'
  | 'encrypting'
  | 'paused'
  | 'plaintext'

export interface Quota {
  max_bots: number
  monthly_tokens: number
  max_memories: number
}

export interface EncryptionInfo {
  enabled: boolean
  state: EncryptionState
}

export interface User {
  id: string
  email: string
  role: Role
  status: UserStatus
  created_at: number
  encryption: EncryptionInfo
}

export interface Limits {
  max_bots: number
  max_memories: number
  monthly_tokens: number
}

export interface MeResponse {
  user: User
  csrf_token: string
  limits: Limits
  version: string
}

export interface OtpRequestPayload {
  email: string
  invite?: string
}

export interface OtpRequestResult {
  sent: boolean
  resend_after: number
  dev_code?: string
}

export interface OtpVerifyPayload {
  email: string
  code: string
  invite?: string
}

export interface OtpVerifyResult {
  user: User
  is_new: boolean
  csrf_token: string
}

export interface MemoryDefaults {
  auto?: boolean
  max_items?: number
  retention_days?: number
  recall_top_k?: number
}

export interface PrivacyDefaults {
  allow_disable?: boolean
}

export interface Template {
  id: string
  name: string
  description: string
  persona_prompt: string
  begin_dialogs: string[]
  config_patch: Record<string, unknown>
  memory_defaults: MemoryDefaults
  privacy_defaults: PrivacyDefaults
  quota: Quota
  user_overridable: string[]
  enabled: boolean
  created_at: number
  updated_at: number
}

/** 管理端模板创建/更新入参（字段同 Template，服务端校验必填项）。 */
export interface TemplateInput {
  name: string
  description?: string
  persona_prompt?: string
  begin_dialogs?: string[]
  config_patch?: Record<string, unknown>
  memory_defaults?: MemoryDefaults
  privacy_defaults?: PrivacyDefaults
  quota?: Quota
  user_overridable?: string[]
  enabled?: boolean
}

export interface QrSession {
  id: string
  status: QrStatus
  qr_content: string
  qr_image: string
  expires_at: number
  refresh_count: number
  interval: number
}

export interface Bot {
  id: string
  name: string
  platform: Platform
  status: BotStatus
  template_id: string
  template_name: string
  persona_name: string
  conf_id: string
  enabled: boolean
  bound: boolean
  created_at: number
  updated_at: number
  last_active_at: number
  qr: QrSession | null
}

export interface BotCreatePayload {
  name: string
  template_id: string
  platform: Platform
}

export interface BotPatchPayload {
  name?: string
  enabled?: boolean
}

export interface QrPollResult {
  qr: QrSession
  message?: string
}

export interface Wallet {
  balance: number
  currency: string
}

export interface LedgerEntry {
  id: number | string
  amount: number
  balance_after?: number
  reason?: string
  detail?: unknown
  created_at: number
}

export interface PageResult<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface AccessLogEntry {
  id: number | string
  actor_id?: string
  actor_email?: string
  action?: string
  target_type?: string
  target_id?: string
  reason?: string
  detail?: unknown
  ip?: string
  created_at: number
}

export interface AdminUser extends User {
  bot_count: number
  quota: Quota
  balance: number
}

export interface AdminUserPatch {
  status?: UserStatus
  quota?: Partial<Quota>
}

export interface AdminBot extends Bot {
  owner_email: string
}

export interface AuditLog {
  id: number | string
  actor_id: string
  actor_role: string
  action: string
  target_type: string
  target_id: string
  reason?: string | null
  detail?: unknown
  ip?: string
  created_at: number
}

export interface Invite {
  code?: string
  code_prefix?: string
  expires_at: number
  max_uses: number
  used_count?: number
  revoked_at?: number | null
  created_at?: number
}

export interface EncryptionStatus {
  enabled: boolean
  state: EncryptionState
  done?: number
  total?: number
  eta?: number | null
}

export interface VersionInfo {
  version: string
  build?: string
}

export interface PageQuery {
  page?: number
  page_size?: number
}

export interface AdminUserQuery extends PageQuery {
  q?: string
  status?: string
}

export interface AuditQuery extends PageQuery {
  action?: string
  actor_id?: string
  target_id?: string
}
