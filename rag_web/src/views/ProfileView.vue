<template>
  <div class="profile-container">
    <div class="profile-card">
      <h2 class="profile-title">个人信息</h2>
      
      <div v-if="isLoading" class="loading-spinner">加载中...</div>
      
      <div v-if="errorMessage" class="error-message">{{ errorMessage }}</div>
      <div v-if="successMessage" class="success-message">{{ successMessage }}</div>

      <form v-if="user" @submit.prevent="handleUpdate">
        <div class="form-group">
          <label for="username">用户名</label>
          <input id="username" v-model="user.username" type="text" class="form-input">
        </div>
        <div class="form-group">
          <label for="email">邮箱</label>
          <input id="email" v-model="user.email" type="email" class="form-input">
        </div>
        <div class="form-group">
          <label for="age">年龄</label>
          <input id="age" v-model.number="user.age" type="number" class="form-input">
        </div>
        <div class="form-group">
          <label for="gender">性别</label>
          <select id="gender" v-model="user.gender" class="form-input">
            <option value="M">男</option>
            <option value="F">女</option>
            <option value="O">其他</option>
          </select>
        </div>
        <button type="submit" class="submit-btn" :disabled="isUpdating">{{ isUpdating ? '更新中...' : '保存更改' }}</button>
      </form>

      <button @click="goBack" class="back-btn">返回聊天</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getCurrentUser, updateUser, type User } from '../services/api'

const router = useRouter()
const user = ref<User | null>(null)
const isLoading = ref(true)
const isUpdating = ref(false)
const errorMessage = ref('')
const successMessage = ref('')

onMounted(async () => {
  try {
    const response = await getCurrentUser()
    if (response.success && response.user) {
      user.value = response.user
    } else {
      errorMessage.value = '无法加载用户信息，请先登录。'
    }
  } catch (error: any) {
    errorMessage.value = error.message || '加载用户信息失败。'
  } finally {
    isLoading.value = false
  }
})

const handleUpdate = async () => {
  if (!user.value) return

  isUpdating.value = true
  errorMessage.value = ''
  successMessage.value = ''

  try {
    const response = await updateUser({
      username: user.value.username,
      email: user.value.email,
      age: user.value.age,
      gender: user.value.gender,
    })

    if (response.success) {
      successMessage.value = '用户信息更新成功！'
    } else {
      errorMessage.value = response.error || '更新失败。'
    }
  } catch (error: any) {
    errorMessage.value = error.message || '更新失败，请稍后重试。'
  } finally {
    isUpdating.value = false
  }
}

const goBack = () => {
  router.push('/')
}
</script>

<style scoped>
.profile-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  background-color: #f3f4f6;
}

.profile-card {
  background: white;
  padding: 40px;
  border-radius: 12px;
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.1);
  width: 100%;
  max-width: 500px;
}

.profile-title {
  font-size: 28px;
  font-weight: 600;
  margin-bottom: 30px;
  text-align: center;
}

.form-group {
  margin-bottom: 20px;
}

.form-group label {
  display: block;
  margin-bottom: 8px;
  font-weight: 500;
}

.form-input {
  width: 100%;
  padding: 12px;
  border-radius: 8px;
  border: 1px solid #d1d5db;
  font-size: 16px;
}

.submit-btn {
  width: 100%;
  padding: 14px;
  border: none;
  border-radius: 8px;
  background-color: #19c37d;
  color: white;
  font-size: 16px;
  cursor: pointer;
  transition: background-color 0.3s;
}

.submit-btn:hover {
  background-color: #16a066;
}

.submit-btn:disabled {
  background-color: #a7f3d0;
  cursor: not-allowed;
}

.back-btn {
  width: 100%;
  padding: 14px;
  margin-top: 10px;
  border: none;
  border-radius: 8px;
  background-color: #6b7280;
  color: white;
  font-size: 16px;
  cursor: pointer;
  transition: background-color 0.3s;
}

.back-btn:hover {
  background-color: #4b5563;
}

.error-message, .success-message, .loading-spinner {
  margin-bottom: 20px;
  padding: 12px;
  border-radius: 8px;
  text-align: center;
}

.error-message {
  background-color: #fee2e2;
  color: #dc2626;
}

.success-message {
  background-color: #d1fae5;
  color: #065f46;
}
</style>
