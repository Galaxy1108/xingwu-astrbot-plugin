import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { h, nextTick } from 'vue'
import { VApp } from 'vuetify/components'
import { vuetify } from '@/theme'
import AdminContentDrawer from '../AdminContentDrawer.vue'
import { ApiError } from '@/api/client'
import type { AdminConversation, MemoryItem } from '@/types'

vi.mock('@/api/admin', () => ({
  listAdminBotConversations: vi.fn(),
  listAdminBotMemories: vi.fn(),
  patchAdminBotMemory: vi.fn(),
  deleteAdminBotMemory: vi.fn(),
  exportAdminBotMemories: vi.fn(),
}))

import {
  listAdminBotConversations,
  listAdminBotMemories,
  patchAdminBotMemory,
} from '@/api/admin'

const listConversations = vi.mocked(listAdminBotConversations)
const listMemories = vi.mocked(listAdminBotMemories)
const patchMemory = vi.mocked(patchAdminBotMemory)

// jsdom 缺少 Vuetify 布局/覆盖层所需的浏览器 API
if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  } as unknown as typeof ResizeObserver
}

if (!window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
}


const conversation: AdminConversation = {
  id: 'c_1',
  platform_id: 'b_1',
  user_id: 'b_1',
  title: '关于西湖的聊天',
  history: [
    { role: 'user', content: '我想去西湖' },
    { role: 'assistant', content: '西湖很适合散步' },
  ],
  encrypted: true,
  decrypt_error: false,
  token_usage: 12,
  created_at: 1_700_000_000,
  updated_at: 1_700_000_100,
}

const memory: MemoryItem = {
  id: 7,
  kind: 'preference',
  kind_label: '偏好',
  content: '用户喜欢深夜聊天',
  reasoning: '多次提到',
  importance: 4,
  pinned: true,
  tags: ['作息'],
  metadata: {},
  created_at: 1_700_000_000,
  updated_at: 1_700_000_100,
  last_recalled_at: 0,
  recall_count: 2,
}

function mountDrawer() {
  // VNavigationDrawer 需要 VApp 提供 layout 上下文
  return mount(VApp, {
    slots: {
      default: () =>
        h(AdminContentDrawer, {
          modelValue: true,
          bot: { id: 'b_1', name: '小明' },
        }),
    },
    global: {
      plugins: [createPinia(), vuetify],
      stubs: { teleport: true },
    },
    attachTo: document.body,
  })
}

beforeEach(() => {
  listConversations.mockReset()
  listMemories.mockReset()
  patchMemory.mockReset()
  listConversations.mockResolvedValue({ items: [conversation], total: 1 })
  listMemories.mockResolvedValue({ items: [memory], total: 1, page: 1, page_size: 10 })
})

afterEach(() => {
  document.body.innerHTML = ''
})

describe('AdminContentDrawer · 对话与记忆', () => {
  it('打开即显示访问提示，并加载对话列表与消息', async () => {
    const wrapper = mountDrawer()
    await flushPromises()
    await nextTick()

    expect(wrapper.text()).toContain('本次访问会记录在案')
    expect(wrapper.text()).toContain('关于西湖的聊天')
    expect(listConversations).toHaveBeenCalledWith('b_1')

    const messages = wrapper.findAll('[data-testid="admin-conversation-message"]')
    expect(messages).toHaveLength(2)
    expect(messages[0].text()).toContain('我想去西湖')
    expect(messages[0].text()).toContain('用户')

    wrapper.unmount()
  })

  it('加载中显示骨架', async () => {
    listConversations.mockReturnValue(new Promise(() => {}))
    const wrapper = mountDrawer()
    await nextTick()

    expect(wrapper.text()).toContain('本次访问会记录在案')
    expect(wrapper.findComponent({ name: 'LoadingSkeleton' }).exists()).toBe(true)

    wrapper.unmount()
  })

  it('加载失败显示错误态并可重试', async () => {
    listConversations.mockRejectedValueOnce(
      new ApiError({ status: 500, code: 'internal_error', message: '服务器开小差了' }),
    )
    const wrapper = mountDrawer()
    await flushPromises()
    await nextTick()

    expect(wrapper.text()).toContain('服务器开小差了')
    expect(wrapper.text()).toContain('重试')

    listConversations.mockResolvedValueOnce({ items: [conversation], total: 1 })
    const retry = wrapper
      .findAll('button')
      .find((button) => button.text().includes('重试'))
    expect(retry).toBeTruthy()
    await retry!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('关于西湖的聊天')
    wrapper.unmount()
  })

  it('解密失败时显示红色提示', async () => {
    listConversations.mockResolvedValue({
      items: [
        {
          ...conversation,
          decrypt_error: true,
          history: [{ role: 'system', content: '【该条对话无法解密：密钥缺失或数据损坏】' }],
        },
      ],
      total: 1,
    })
    const wrapper = mountDrawer()
    await flushPromises()
    await nextTick()

    expect(wrapper.find('[data-testid="admin-conversation-decrypt-error"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('切换到记忆 tab 时加载记忆，展示内容并支持打开编辑', async () => {
    const wrapper = mountDrawer()
    await flushPromises()

    await wrapper.get('[data-testid="admin-content-tab-memories"]').trigger('click')
    await flushPromises()
    await nextTick()

    expect(listMemories).toHaveBeenCalledWith('b_1', {
      page: 1,
      page_size: 10,
      q: undefined,
      kind: undefined,
    })
    expect(wrapper.text()).toContain('用户喜欢深夜聊天')
    expect(wrapper.findAll('[data-testid="admin-memory-row"]')).toHaveLength(1)

    await wrapper.get('[data-testid="admin-memory-edit"]').trigger('click')
    await nextTick()
    expect(wrapper.text()).toContain('编辑记忆')
    expect(
      (wrapper.get('textarea').element as HTMLTextAreaElement).value,
    ).toContain('用户喜欢深夜聊天')

    wrapper.unmount()
  })

  it('筛选记忆时把关键字与类型传给 API', async () => {
    const wrapper = mountDrawer()
    await flushPromises()
    await wrapper.get('[data-testid="admin-content-tab-memories"]').trigger('click')
    await flushPromises()

    const search = wrapper.get('[data-testid="admin-memory-search"] input')
    await search.setValue('西湖')
    await nextTick()
    await wrapper.get('form.memory-filters').trigger('submit')
    await flushPromises()

    expect(listMemories).toHaveBeenLastCalledWith('b_1', {
      page: 1,
      page_size: 10,
      q: '西湖',
      kind: undefined,
    })
    wrapper.unmount()
  })
})
