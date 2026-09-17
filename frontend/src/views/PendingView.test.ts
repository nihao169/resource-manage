import { expect, test } from 'vitest'
import { mount } from '@vue/test-utils'
import PendingView from './PendingView.vue'
test('marks business entry as unimplemented', () => {
 const view = mount(PendingView, {props:{title:'上传',owner:'C'}})
 expect(view.text()).toContain('待实现')
 expect(view.findAll('button')).toHaveLength(0)
})
