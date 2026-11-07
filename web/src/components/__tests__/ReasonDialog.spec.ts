import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { describe, expect, it } from 'vitest'
import ReasonDialog from '../ReasonDialog.vue'

function mountDialog(props: Record<string, unknown> = {}) {
  return mount(ReasonDialog, {
    props: {
      modelValue: true,
      title: '封禁用户',
      ...props,
    },
    global: { stubs: { teleport: true } },
    attachTo: document.body,
  })
}

describe('ReasonDialog · 原因必填', () => {
  it('原因为空时显示错误且不 emit confirm', async () => {
    const wrapper = mountDialog()
    await nextTick()
    await wrapper.get('[data-testid="reason-confirm"]').trigger('click')
    expect(wrapper.text()).toContain('请填写原因')
    expect(wrapper.emitted('confirm')).toBeUndefined()
    wrapper.unmount()
  })

  it('填写原因后 emit 去除首尾空白的 reason', async () => {
    const wrapper = mountDialog()
    await wrapper.get('textarea').setValue('  违规行为  ')
    await wrapper.get('[data-testid="reason-confirm"]').trigger('click')
    expect(wrapper.emitted('confirm')?.[0]).toEqual(['违规行为'])
    wrapper.unmount()
  })

  it('required=false 时允许空备注，取消 emit update 与 cancel', async () => {
    const wrapper = mountDialog({ required: false })
    await wrapper.get('[data-testid="reason-confirm"]').trigger('click')
    expect(wrapper.emitted('confirm')?.[0]).toEqual([''])
    await wrapper.get('[data-testid="reason-cancel"]').trigger('click')
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([false])
    expect(wrapper.emitted('cancel')).toHaveLength(1)
    wrapper.unmount()
  })
})
