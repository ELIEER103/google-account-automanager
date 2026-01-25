<script setup>
import { ref, onMounted } from 'vue'
import { configApi } from '../api'

const loading = ref(false)
const saving = ref(false)
const message = ref('')
const messageType = ref('success')

const config = ref({
  sheerid_api_key: '',
  card_number: '',
  card_exp_month: '',
  card_exp_year: '',
  card_cvv: '',
  card_zip: '',
})

async function loadConfig() {
  loading.value = true
  try {
    const res = await configApi.get()
    config.value = {
      sheerid_api_key: res.data.sheerid_api_key || '',
      card_number: res.data.card_number || '',
      card_exp_month: res.data.card_exp_month || '',
      card_exp_year: res.data.card_exp_year || '',
      card_cvv: res.data.card_cvv || '',
      card_zip: res.data.card_zip || '',
    }
  } catch (e) {
    console.error('加载配置失败:', e)
    showMessage('加载配置失败: ' + e.message, 'error')
  } finally {
    loading.value = false
  }
}

async function saveConfig() {
  saving.value = true
  try {
    await configApi.update(config.value)
    showMessage('配置保存成功', 'success')
  } catch (e) {
    console.error('保存配置失败:', e)
    showMessage('保存失败: ' + e.message, 'error')
  } finally {
    saving.value = false
  }
}

function showMessage(msg, type = 'success') {
  message.value = msg
  messageType.value = type
  setTimeout(() => {
    message.value = ''
  }, 3000)
}

function maskCardNumber(num) {
  if (!num || num.length < 8) return num
  return num.slice(0, 4) + ' **** **** ' + num.slice(-4)
}

onMounted(() => {
  loadConfig()
})
</script>

<template>
  <div class="space-y-6">
    <div class="flex justify-between items-center">
      <h1 class="text-2xl font-bold text-gray-900">系统配置</h1>
    </div>

    <!-- 提示消息 -->
    <div
      v-if="message"
      class="rounded-md p-4"
      :class="messageType === 'success' ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'"
    >
      {{ message }}
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="text-center py-8">
      <span class="text-gray-500">加载中...</span>
    </div>

    <div v-else class="space-y-6">
      <!-- SheerID 配置 -->
      <div class="bg-white shadow rounded-lg p-6">
        <h2 class="text-lg font-medium text-gray-900 mb-4">SheerID 验证服务</h2>
        <p class="text-sm text-gray-500 mb-4">
          用于自动验证 SheerID 学生资格链接。API 密钥来自 batch.1key.me 服务。
        </p>
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">API Key</label>
          <input
            v-model="config.sheerid_api_key"
            type="password"
            class="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500"
            placeholder="输入 SheerID API Key"
          />
        </div>
      </div>

      <!-- 虚拟卡配置 -->
      <div class="bg-white shadow rounded-lg p-6">
        <h2 class="text-lg font-medium text-gray-900 mb-4">虚拟卡信息</h2>
        <p class="text-sm text-gray-500 mb-4">
          用于年龄验证和绑卡订阅任务。请确保卡片有效且有足够余额。
        </p>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div class="md:col-span-2">
            <label class="block text-sm font-medium text-gray-700 mb-1">卡号</label>
            <input
              v-model="config.card_number"
              type="text"
              class="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500"
              placeholder="16位卡号"
              maxlength="16"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">过期月份</label>
            <input
              v-model="config.card_exp_month"
              type="text"
              class="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500"
              placeholder="MM (如 01)"
              maxlength="2"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">过期年份</label>
            <input
              v-model="config.card_exp_year"
              type="text"
              class="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500"
              placeholder="YY (如 32)"
              maxlength="2"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">CVV</label>
            <input
              v-model="config.card_cvv"
              type="password"
              class="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500"
              placeholder="3位安全码"
              maxlength="4"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">邮编 (可选)</label>
            <input
              v-model="config.card_zip"
              type="text"
              class="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500"
              placeholder="账单地址邮编"
              maxlength="10"
            />
          </div>
        </div>
      </div>

      <!-- 保存按钮 -->
      <div class="flex justify-end">
        <button
          @click="saveConfig"
          :disabled="saving"
          class="px-6 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {{ saving ? '保存中...' : '保存配置' }}
        </button>
      </div>

      <!-- 安全提示 -->
      <div class="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
        <h3 class="text-sm font-medium text-yellow-800 mb-2">安全提示</h3>
        <ul class="text-sm text-yellow-700 list-disc list-inside space-y-1">
          <li>配置信息存储在本地数据库中，不会上传到任何服务器</li>
          <li>请勿在公共电脑上保存敏感信息</li>
          <li>建议定期更换虚拟卡以保护账户安全</li>
        </ul>
      </div>
    </div>
  </div>
</template>
