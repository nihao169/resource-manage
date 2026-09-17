import { expect, test } from 'vitest'
import { modules } from './index'

test('module ownership uses the three-member assignment', () => {
  expect(modules.filter(module => ['login', 'files', 'admin'].includes(module.path))
    .every(module => module.owner.includes('B PostgreSQL'))).toBe(true)
  expect(modules.find(module => module.path === 'uploads')?.owner)
    .toBe('A 前端 / C MinIO / B 事务')
  expect(modules.every(module => !/\bD\b/.test(module.owner))).toBe(true)
})
