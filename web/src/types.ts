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
  used_tokens?: number
  used_memories?: number
}

export interface EncryptionInfo {
  enabled: boolean
  state: EncryptionState
}

export interface User {
  id: string
  email: string
  username?: string
  display_name: string
  email_verified?: boolean
  has_password?: boolean
  recovery_available?: boolean
  role: Role
  status: UserStatus
  status_reason?: string
  status_changed_at?: number
  pending_appeal?: boolean
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
  astrbot_dashboard_url?: string
  is_admin?: boolean
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

export interface PasswordSessionResult {
  user: User
  csrf_token: string
  recovery_available?: boolean
}

export interface PasswordRegisterPayload {
  invite: string
  username: string
  password: string
  display_name?: string
}

export interface OAuthProvider {
  id: string
  name: string
  enabled: boolean
}

export interface OAuthIdentity {
  provider: string
  login?: string
  email?: string
  created_at?: number
}

export interface AdminOAuthSettings {
  enabled?: boolean
  client_id?: string
  has_client_secret?: boolean
  redirect_uri?: string
  callback_url?: string
}

export interface OAuthStartResult {
  authorize_url: string
  state?: string
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
  /** AstrBot configuration profile this template clones (default: "default"). */
  base_conf_id?: string
  /** 管理端模型目录中的模型配置 id；空字符串表示沿用 base_conf_id 的模型。 */
  model_profile_id?: string
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
  base_conf_id?: string
  model_profile_id?: string
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

export interface BotSettings {
  streaming: boolean
  compression_max_turns: number
  compression_overflow_strategy: string
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
  model_profile_id?: string
  admin_disabled?: boolean
  admin_disabled_reason?: string
  settings?: BotSettings
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
  model_profile_id?: string
  settings?: Partial<BotSettings>
}

export interface QrConnectSession {
  id: string
  status: 'pending' | 'scanned' | 'confirmed' | 'expired'
  qr: QrSession
  message?: string
}

export interface QrPollResult {
  qr: QrSession
  message?: string
}

export interface Wallet {
  balance: number
  currency: string
  /** 后端返回的账本重算余额（用于对账），不是流水条数。 */
  ledger_total?: number
}

export interface RedeemResult {
  balance?: number
  credits?: number
  message?: string
}

export interface LedgerEntry {
  id: number | string
  /** 账本变动值（正数入账、负数扣减） */
  delta?: number
  /** 兼容旧字段 */
  amount?: number
  balance_after?: number
  type?: string
  ref?: string
  note?: string
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
  actor_name?: string
  actor_email?: string
  bot_name?: string
  admin_id?: string
  user_id?: string
  bot_id?: string
  action?: string
  resource?: string
  resource_id?: string
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
  /** 平台点数账本累计充值（负数扣减/消费见 deducted_points） */
  granted_points?: number
  deducted_points?: number
  /** 已用 Token（需接入计量；未接入时为 0） */
  used_tokens?: number
}

export interface ConfProfile {
  id: string
  name: string
  is_default?: boolean
}

export interface AdminOverview {
  users: number
  bots: number
  ready_bots: number
  /** 平台内预付费点数合计，不是上游模型账户余额 */
  balance_total: number
  granted_points: number
  adjusted_in_points: number
  deducted_points: number
  tokens_used: number
  tokens_metered: boolean
  paid_orders: number
  paid_orders_amount_cny: number
  balance_scope: string
}

export interface UsagePoint {
  date: string
  delta: number
  in: number
  out: number
  balance: number
}

export interface UsageDailyPoint {
  date: string
  points: number
  tokens: number
  requests: number
}

export interface UsageDaily {
  days: number
  start: string
  end: string
  bot_id: string
  total_points: number
  total_tokens: number
  total_requests: number
  points: UsageDailyPoint[]
}

export interface UsageStatBucket {
  points: number
  tokens: number
  requests: number
}

export interface ModelUsageStat extends UsageStatBucket {
  model_id: string
  model_name: string
}

export interface BotUsageStat extends UsageStatBucket {
  bot_id: string
  bot_name: string
  platform: string
}

export interface PlatformUsageStat extends UsageStatBucket {
  platform: string
}

export interface MeStats {
  days: number
  start: string
  end: string
  total_points: number
  total_tokens: number
  total_requests: number
  points: UsageDailyPoint[]
  messages?: {
    days: number
    start: string
    end: string
    total: number
    points: Array<{ date: string; count: number }>
    by_platform: Array<{ platform: string; count: number }>
  }
  by_model: ModelUsageStat[]
  by_bot: BotUsageStat[]
  by_platform: PlatformUsageStat[]
}

export interface UsageByBot {
  bot_id: string
  bot_name: string
  points: number
  tokens: number
  requests: number
}

export interface WalletUsage {
  days: number
  start: string
  end: string
  balance: number
  total_in: number
  total_out: number
  points: UsagePoint[]
  scope: string
}

export interface AdminUserPatch {
  status?: UserStatus
  reason?: string
  quota?: Partial<Quota>
}

export type OrderStatus = 'pending' | 'paid'

export interface AdminOrder {
  id: string
  user_id: string
  user_email?: string
  amount_cny: number
  credits: number
  source: string
  external_ref?: string | null
  status: OrderStatus
  created_at: number
  paid_at: number
  operator: string
}

export interface AdminOrderCreatePayload {
  user_id: string
  credits: number
  amount_cny?: number
  external_ref?: string
  note?: string
}

export interface AdminOrderCreateResult {
  order: AdminOrder
  idempotent: boolean
}

export interface AdminOrderConfirmResult {
  order: AdminOrder
  already_paid: boolean
}

export interface AdminLedgerAdjustPayload {
  user_id: string
  delta: number
  reason?: string
  idem_key?: string
}

export interface RedemptionCode {
  code: string
  credits: number
  note?: string
  used_count?: number
  max_uses?: number
  expires_at?: number | null
  status?: string
  disabled?: boolean
  revoked_at?: number | null
  created_at?: number
}

export interface RedemptionCodeCreatePayload {
  credits: number
  note?: string
  quantity?: number
  max_uses?: number
  expires_at?: number
}

export interface RedemptionCodeCreateResult {
  codes?: Array<string | RedemptionCode>
  count?: number
}

export interface AdminLedgerAdjustResult {
  ledger: LedgerEntry
  idempotent: boolean
  balance: number
}

export interface AdminBot extends Bot {
  owner_email: string
  user_id?: string
}

export type AppealStatus = 'pending' | 'approved' | 'rejected'
export type AppealTarget = 'user' | 'bot'

export interface Appeal {
  id: string | number
  target_type: AppealTarget
  target_id?: string
  target_name?: string
  user_id?: string
  user_email?: string
  reason: string
  status: AppealStatus
  note?: string
  created_at: number
  handled_at?: number
  handled_by?: string
}

export interface NoteSummary {
  id: number
  short_id: string
  title: string
  tags: string[]
  content_length: number
  preview: string
  created_at: number
  updated_at: number
}

export interface NoteDetail extends NoteSummary {
  content?: string
}

export interface NoteReadPage {
  short_id: string
  title: string
  content: string
  offset: number
  limit: number
  total_length: number
  has_more: boolean
  next_offset: number | null
  note?: NoteSummary
}

export interface AdminUserUsageItem {
  bot_id?: string
  bot_name?: string
  date?: string
  points?: number
  tokens?: number
  requests?: number
}

export interface AdminUserUsageSummary {
  days?: number
  points?: number
  tokens?: number
  requests?: number
}

export interface AdminUserUsage {
  summary?: AdminUserUsageSummary
  by_bot?: AdminUserUsageItem[]
  items?: AdminUserUsageItem[]
  total?: number
  page?: number
  page_size?: number
}

export interface AdminUserDetail extends AdminUser {
  bots?: AdminBot[]
  recent_ledger?: LedgerEntry[]
  ledger?: LedgerEntry[]
  usage?: AdminUserUsage
}

export interface ConversationMessage {
  role: string
  content: string
}

export interface ConversationShare {
  token: string
  url: string
  expires_at?: number | null
  created_at?: number
}

export interface ConversationSummary {
  id: string
  title: string
  message_count?: number
  history?: ConversationMessage[] | null
  created_at: number
  updated_at?: number
  shared?: boolean
  share?: ConversationShare | null
}

export interface PublicConversation {
  id?: string
  title: string
  messages: ConversationMessage[]
  created_at: number
  updated_at?: number
  expires_at?: number | null
}

export interface AdminConversation {
  id: string
  platform_id: string
  user_id: string
  title: string
  history: ConversationMessage[] | null
  encrypted: boolean
  decrypt_error: boolean
  token_usage?: number
  created_at: number
  updated_at: number
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

export interface EncryptionJob {
  id: string
  direction: 'decrypt' | 'encrypt'
  status: 'queued' | 'running' | 'paused' | 'done' | 'failed'
  total: number
  done: number
  percent: number
  error?: string | null
  created_at?: number
  finished_at?: number
}

export interface EncryptionStatus {
  enabled: boolean
  state: EncryptionState
  done?: number
  total?: number
  percent?: number
  eta?: number | null
  changed_at?: number
  job?: EncryptionJob | null
}

export interface VersionInfo {
  version: string
  build?: string
  dev_mode?: boolean
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

/* ------------------------------------------------------------------ */
/* M2 记忆模块（契约见 lead 提供的接口说明；docs/API.md 尚未收录）        */
/* ------------------------------------------------------------------ */

export type MemoryKind = 'fact' | 'preference' | 'event' | 'note'

export interface MemoryItem {
  id: number
  kind: MemoryKind
  kind_label: string
  content: string
  reasoning: string
  importance: number
  pinned: boolean
  tags: string[]
  metadata: Record<string, unknown>
  source_conversation_id?: string
  source_message_id?: string
  created_at: number
  updated_at: number
  last_recalled_at: number
  recall_count: number
}

export interface MemoryListQuery {
  page?: number
  page_size?: number
  kind?: string
  tag?: string
  q?: string
  importance?: number | string
}

export interface MemoryPatch {
  content?: string
  kind?: MemoryKind
  reasoning?: string
  importance?: number
  pinned?: boolean
  tags?: string[]
  metadata?: Record<string, unknown>
}

export interface MemorySearchPayload {
  q: string
  kind?: string
  limit?: number
}

export interface MemorySnapshotNote {
  short_id?: string
  title?: string
  content?: string
  tags?: string[]
  created_at?: number
  updated_at?: number
}

/** 记忆快照（后端 export_snapshot：memories + notes，兼容旧 items 字段）。 */
export interface MemoryExportResult {
  version?: number
  bot_id: string
  exported_at: number
  count: number
  items?: MemoryItem[]
  memories?: MemoryItem[]
  tags?: string[]
  notes_count?: number
  notes?: MemorySnapshotNote[]
}

export interface MemoryImportCounts {
  total: number
  imported: number
  skipped: number
  failed: number
}

export interface MemoryImportReport {
  bot_id: string
  dry_run: boolean
  memories: MemoryImportCounts
  notes: MemoryImportCounts
  errors?: string[]
  short_id_map?: Record<string, string>
}

/* ------------------------------------------------------------------ */
/* 管理端内容查看 / 记忆 API 设置 / 模型与定价                            */
/* ------------------------------------------------------------------ */

export interface AdminConversationList {
  items: AdminConversation[]
  total: number
}

/** 管理端对话只读查看，不提供整库导出。 */
export interface AdminContentTarget {
  id: string
  name: string
}

/** 记忆 API 设置：embedding / rerank 的 api_key 永远是掩码或空串。 */
export interface MemoryEmbeddingConfig {
  enabled: boolean
  base_url: string
  api_key: string
  model: string
  dimensions: number
  timeout_seconds: number
  batch_size: number
  has_api_key?: boolean
}

export interface MemoryRerankConfig {
  enabled: boolean
  base_url: string
  api_key: string
  model: string
  top_n: number
  timeout_seconds: number
  has_api_key?: boolean
}

export interface MemoryBehaviorConfig {
  vector_candidate_limit: number
  rerank_candidate_limit: number
  rrf_k: number
  recall_top_k: number
  auto_inject?: boolean
  auto_extract?: boolean
}

export interface MemoryProviderStatus {
  state: string
  enabled?: boolean
  configured?: boolean
  last_test_at?: number
  last_tested_at?: number
  last_checked?: number
  last_ok?: boolean | null
  latency_ms?: number
  last_error?: string
  message?: string
}

export interface MemorySettingsStatus {
  embedding?: MemoryProviderStatus
  rerank?: MemoryProviderStatus
  fts?: { available?: boolean; mode?: string }
  behavior?: MemoryBehaviorConfig
}

export interface MemorySettings {
  embedding: MemoryEmbeddingConfig
  rerank: MemoryRerankConfig
  behavior: MemoryBehaviorConfig
}

export type MemorySettingsKind = 'embedding' | 'rerank'

/** PUT 为部分更新：只提交变更的 section，api_key 省略表示不修改。 */
export interface MemorySettingsPatch {
  embedding?: Partial<MemoryEmbeddingConfig>
  rerank?: Partial<MemoryRerankConfig>
  behavior?: Partial<MemoryBehaviorConfig>
}

export interface MemorySettingsTestPayload {
  kind: MemorySettingsKind
}

export interface MemorySettingsTestResult {
  ok: boolean
  dim?: number
  count?: number
  message?: string
}

export interface ModelProfile {
  id: string
  name: string
  provider: string
  base_url: string
  model: string
  /** 服务端只返回掩码或空串，不回显明文。 */
  api_key?: string
  has_api_key?: boolean
  points_per_1k_input: number
  points_per_1k_output: number
  currency: string
  enabled: boolean
  note: string
  created_at?: number
  updated_at?: number
}

export interface ModelProfileInput {
  name: string
  provider: string
  base_url: string
  model: string
  api_key?: string
  points_per_1k_input: number
  points_per_1k_output: number
  currency: string
  enabled: boolean
  note: string
}

export interface ModelProfileList {
  items: ModelProfile[]
}

export interface HealthInfo {
  status: 'ok' | 'degraded'
  db: string
  backend: 'astrbot' | 'fake' | string
  version: string
  recent_errors_1h?: number
}

export interface AdminErrorLog {
  id: number
  level: string
  source: string
  path: string
  method: string
  status: number
  code: string
  message: string
  detail: string
  user_id: string
  ip: string
  created_at: number
}

export interface AdminInvite {
  code_hint: string
  max_uses: number
  used_count: number
  expires_at: number
  revoked_at: number
  created_at: number
  created_by?: string
  note?: string
  status: 'active' | 'used' | 'expired' | 'revoked'
}

export interface AdminInviteCreatePayload {
  max_uses?: number
  ttl_hours?: number
  note?: string
}
