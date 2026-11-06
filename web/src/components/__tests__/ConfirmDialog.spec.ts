import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { describe, expect, it } from 'vitest'
import ConfirmDialog from '../ConfirmDialog.vue'

function mountDialog(props: Record<string, unknown> = {}) {
  return mount(ConfirmDialog, {
    props: {
      modelValue: true,
      title: '删除 Bot',
      typeToConfirm: '小明',
      ...props,
    },
    global: { stubs: { teleport: true } },
    attachTo: document.body,
  })
}

describe('ConfirmDialog · 危险操作二次确认', () => {
  it('未输入文字时确认按钮禁用', async () => {
    const wrapper = mountDialog()
    await nextTick()

    const submit = wrapper.get('[data-testid="confirm-submit"]')
    expect(submit.attributes('disabled')).toBeDefined()

    wrapper.unmount()
  })

  it('输入不匹配时仍禁用，输入完全一致后启用并可确认', async () => {
    const wrapper = mountDialog()
    const input = wrapper.get('[data-testid="confirm-input"]')

    await input.setValue('小')
    expect(wrapper.get('[data-testid="confirm-submit"]').attributes('disabled')).toBeDefined()
    expect(wrapper.emitted('confirm')).toBeUndefined()

    await input.setValue('小明')
    const submit = wrapper.get('[data-testid="confirm-submit"]')
    expect(submit.attributes('disabled')).toBeUndefined()

    await submit.trigger('click')
    expect(wrapper.emitted('confirm')).toHaveLength(1)

    wrapper.unmount()
  })

  it('无 typeToConfirm 时默认允许确认', async () => {
    const wrapper = mountDialog({ typeToConfirm: '' })
    const submit = wrapper.get('[data-testid="confirm-submit"]')

    expect(submit.attributes('disabled')).toBeUndefined()
    await submit.trigger('click')
    expect(wrapper.emitted('confirm')).toHaveLength(1)

    wrapper.unmount()
  })

  it('默认焦点在取消按钮，取消会关闭对话框', async () => {
    const wrapper = mountDialog()
    await nextTick()

    const cancel = wrapper.get('[data-testid="confirm-cancel"]')
    expect(document.activeElement).toBe(cancel.element)

    await cancel.trigger('click')
    expect(wrapper.emitted('cancel')).toHaveLength(1)
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([false])

    wrapper.unmount()
  })
})
