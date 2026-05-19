import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import prettierConfig from 'eslint-config-prettier'
import prettierPlugin from 'eslint-plugin-prettier'

export default [
  // 基础 JS 推荐规则
  js.configs.recommended,

  // Vue 3 推荐规则
  ...pluginVue.configs['flat/recommended'],

  // Prettier 格式化集成（必须放最后，覆盖冲突的格式规则）
  prettierConfig,

  {
    plugins: {
      prettier: prettierPlugin
    },
    rules: {
      // Prettier 格式化作为 ESLint 错误上报
      'prettier/prettier': 'error',

      // Vue 组件规范
      'vue/component-name-in-template-casing': ['error', 'PascalCase'],
      'vue/component-definition-name-casing': ['error', 'PascalCase'],
      'vue/no-unused-vars': 'error',
      'vue/no-unused-components': 'warn',
      'vue/require-default-prop': 'off', // 工业项目 props 可以不设默认值
      'vue/multi-word-component-names': 'warn', // 建议多词组件名，不强制报错

      // JS 通用规范
      'no-console': ['warn', { allow: ['warn', 'error'] }],
      'no-debugger': 'error',
      'no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      'no-var': 'error',
      'prefer-const': 'error',
      eqeqeq: ['error', 'always'],
      'no-duplicate-imports': 'error',

      // 关闭与 Prettier 冲突的格式规则
      indent: 'off',
      quotes: 'off',
      semi: 'off'
    }
  },

  {
    // 忽略构建产物和依赖
    ignores: ['dist/**', 'node_modules/**', '*.min.js', 'public/**']
  }
]
