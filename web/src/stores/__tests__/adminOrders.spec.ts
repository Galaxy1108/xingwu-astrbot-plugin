import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AdminOrder, AdminUser } from '@/types'

vi.mock('@/api/admin', () => ({
  listAdminOrders: vi.fn(),
  createAdminOrder: vi.fn(),
  confirmAdminOrder: vi.fn(),
  adjustAdminLedger: vi.fn(),
  patchAdminUser: vi.fn(),
}))

import * as adminApi from '@/api/admin'
import { useAdminStore } from '../admin'
import {
  buildAdjustPayload,
  buildOrderPayload,
  hasErrors,
  validateAdjustForm,
  validateOrderForm,
} from '@/utils/walletAdmin'

function order(overrides: Partial<AdminOrder> = {}): AdminOrder {
  return {
    id: 'o_1',
    user_id: 'u_1',
    user_email: 'ui@example.com',
    amount_cny: 9.9,
    credits: 10,
    source: 'manual',
    external_ref: 'REF-1',
    status: 'pending',
    created_at: 1000,
    paid_at: 0,
    operator: 'u_admin',
    ...overrides,
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
})

describe('手动充值 · 校验与 payload', () => {
  it('新建充值单：用户必选、credits 必须为正整数', () => {
    const invalid = validateOrderForm({
      user_id: '',
      credits: '1.5',
      external_ref: '',
      note: '',
    })
    expect(invalid.user_id).toBeTruthy()
    expect(invalid.credits).toContain('整数')

    const valid = validateOrderForm({
      user_id: 'u_1',
      credits: '10',
      external_ref: '',
      note: '',
    })
    expect(hasErrors(valid)).toBe(false)

    expect(buildOrderPayload({
      user_id: 'u_1',
      credits: '10',
      external_ref: ' REF-1 ',
      note: ' 备注 ',
    })).toEqual({
      user_id: 'u_1',
      credits: 10,
      external_ref: 'REF-1',
      note: '备注',
    })
  })

  it('扣减参数：拒绝 0 与小数的 delta，允许负数并保留幂等键', () => {
    expect(validateAdjustForm({
      user_id: 'u_1',
      delta: '0',
      reason: '',
      idem_key: '',
    }).delta).toContain('不能为 0')

    expect(validateAdjustForm({
      user_id: 'u_1',
      delta: '1.5',
      reason: '',
      idem_key: '',
    }).delta).toContain('整数')

    expect(hasErrors(validateAdjustForm({
      user_id: 'u_1',
      delta: '-50',
      reason: '修正余额',
      idem_key: 'adj-1',
    }))).toBe(false)

    expect(buildAdjustPayload({
      user_id: 'u_1',
      delta: '-50',
      reason: ' 修正余额 ',
      idem_key: ' adj-1 ',
    })).toEqual({
      user_id: 'u_1',
      delta: -50,
      reason: '修正余额',
      idem_key: 'adj-1',
    })
  })
})

describe('admin store · 充值单', () => {
  it('createOrder 原样透传 credits/external_ref/note 并返回幂等标记', async () => {
    vi.mocked(adminApi.createAdminOrder).mockResolvedValueOnce({
      order: order(),
      idempotent: false,
    })

    const store = useAdminStore()
    const result = await store.createOrder({
      user_id: 'u_1',
      credits: 10,
      external_ref: 'REF-1',
      note: '测试',
    })

    expect(adminApi.createAdminOrder).toHaveBeenCalledWith({
      user_id: 'u_1',
      credits: 10,
      external_ref: 'REF-1',
      note: '测试',
    })
    expect(result.idempotent).toBe(false)
  })

  it('confirmOrder 调用确认接口并用返回订单更新列表状态', async () => {
    vi.mocked(adminApi.listAdminOrders).mockResolvedValueOnce({
      items: [order()],
      total: 1,
      page: 1,
      page_size: 20,
    })
    vi.mocked(adminApi.confirmAdminOrder).mockResolvedValueOnce({
      order: order({ status: 'paid', paid_at: 2000 }),
      already_paid: false,
    })

    const store = useAdminStore()
    await store.loadOrders({ page: 1 })
    const result = await store.confirmOrder('o_1')

    expect(adminApi.confirmAdminOrder).toHaveBeenCalledWith('o_1')
    expect(result.already_paid).toBe(false)
    expect(store.orders[0].status).toBe('paid')
    expect(store.orders[0].paid_at).toBe(2000)
  })

describe('admin store · 用户配额', () => {
  it('updateUserQuota 用嵌套 quota payload 并刷新列表条目', async () => {
    const user: AdminUser = {
      id: 'u_1',
      email: 'quota@example.com',
      display_name: 'quota',
      role: 'user',
      status: 'active',
      created_at: 1000,
      encryption: { enabled: true, state: 'encrypted' },
      bot_count: 1,
      quota: { max_bots: 3, max_memories: 2000, monthly_tokens: 1000000 },
      balance: 0,
    }
    vi.mocked(adminApi.patchAdminUser).mockResolvedValueOnce({
      user: { ...user, quota: { max_bots: 5, max_memories: 5000, monthly_tokens: 2000000 } },
    })

    const store = useAdminStore()
    store.users = [user]
    const updated = await store.updateUserQuota('u_1', {
      max_bots: 5,
      max_memories: 5000,
      monthly_tokens: 2000000,
    })

    expect(adminApi.patchAdminUser).toHaveBeenCalledWith('u_1', {
      quota: { max_bots: 5, max_memories: 5000, monthly_tokens: 2000000 },
    })
    expect(updated.quota.max_bots).toBe(5)
    expect(store.users[0].quota.max_memories).toBe(5000)
  })
})
})
