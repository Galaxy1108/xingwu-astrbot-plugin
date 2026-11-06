import type { AdminLedgerAdjustPayload, AdminOrderCreatePayload } from '@/types'

export interface OrderFormState {
  user_id: string
  credits: string
  amount_cny: string
  external_ref: string
  note: string
}

export interface OrderFormErrors {
  user_id?: string
  credits?: string
  amount_cny?: string
}

export interface AdjustFormState {
  user_id: string
  delta: string
  reason: string
  idem_key: string
}

export interface AdjustFormErrors {
  user_id?: string
  delta?: string
}

/**
 * 新建充值单校验：用户必选、credits 正整数（后端只拒绝 0，这里按“充值”语义收紧）、
 * 金额可选但必须是非负数字。
 */
export function validateOrderForm(form: OrderFormState): OrderFormErrors {
  const errors: OrderFormErrors = {}
  if (!form.user_id) errors.user_id = '请选择用户'

  const creditsText = form.credits.trim()
  if (!creditsText) {
    errors.credits = '请输入点数'
  } else {
    const credits = Number(creditsText)
    if (!Number.isInteger(credits)) errors.credits = '点数必须是整数'
    else if (credits <= 0) errors.credits = '充值点数必须大于 0'
  }

  const amountText = form.amount_cny.trim()
  if (amountText) {
    const amount = Number(amountText)
    if (!Number.isFinite(amount) || amount < 0) errors.amount_cny = '金额必须是大于等于 0 的数字'
  }
  return errors
}

/** 手动加/扣额度校验：delta 必须是非零整数（正数加、负数扣）。 */
export function validateAdjustForm(form: AdjustFormState): AdjustFormErrors {
  const errors: AdjustFormErrors = {}
  if (!form.user_id) errors.user_id = '请选择用户'

  const deltaText = form.delta.trim()
  if (!deltaText) {
    errors.delta = '请输入调整点数'
  } else {
    const delta = Number(deltaText)
    if (!Number.isInteger(delta)) errors.delta = '调整点数必须是整数'
    else if (delta === 0) errors.delta = '调整点数不能为 0（正数加、负数扣）'
  }
  return errors
}

export function hasErrors(errors: object): boolean {
  return Object.values(errors).some(Boolean)
}

export function buildOrderPayload(form: OrderFormState): AdminOrderCreatePayload {
  const payload: AdminOrderCreatePayload = {
    user_id: form.user_id,
    credits: Number(form.credits),
  }
  const amountText = form.amount_cny.trim()
  if (amountText) payload.amount_cny = Number(amountText)
  const externalRef = form.external_ref.trim()
  if (externalRef) payload.external_ref = externalRef
  const note = form.note.trim()
  if (note) payload.note = note
  return payload
}

export function buildAdjustPayload(form: AdjustFormState): AdminLedgerAdjustPayload {
  const payload: AdminLedgerAdjustPayload = {
    user_id: form.user_id,
    delta: Number(form.delta),
  }
  const reason = form.reason.trim()
  if (reason) payload.reason = reason
  const idemKey = form.idem_key.trim()
  if (idemKey) payload.idem_key = idemKey
  return payload
}
