<template>
  <div class="kb-manage-container">
    <div class="container">
      <div class="header">
        <h1 class="title">
          <span class="icon">📚</span>
          我的知识库
        </h1>
        <div class="header-actions">
          <button class="back-chat-btn" @click="goToChat">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
            </svg>
            <span>返回聊天</span>
          </button>
          <button class="create-btn" @click="goToCreate">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M12 5v14M5 12h14"/>
            </svg>
            <span>创建知识库</span>
          </button>
        </div>
      </div>

      <!-- 知识库列表 -->
      <div class="kb-list">
        <div v-if="loading" class="loading-state">
          <div class="spinner"></div>
          <p>加载中...</p>
        </div>

        <div v-else-if="knowledgeBases.length === 0" class="empty-state">
          <div class="empty-icon">📂</div>
          <h3>暂无知识库</h3>
          <p>创建您的第一个知识库，开始管理文档</p>
          <button class="create-empty-btn" @click="goToCreate">创建知识库</button>
        </div>

        <div v-else class="kb-grid">
          <div
            v-for="kb in knowledgeBases"
            :key="kb.id"
            class="kb-card"
            @click="viewKnowledgeBase(kb.id)"
          >
            <div class="kb-card-header">
              <h3 class="kb-name">{{ kb.name }}</h3>
              <div class="kb-actions">
                <button
                  class="action-btn edit-btn"
                  @click.stop="editKnowledgeBase(kb)"
                  title="编辑"
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                  </svg>
                </button>
                <button
                  class="action-btn delete-btn"
                  @click.stop="deleteKB(kb)"
                  title="删除"
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                  </svg>
                </button>
              </div>
            </div>
            
            <p v-if="kb.description" class="kb-description">{{ kb.description }}</p>
            <p v-else class="kb-description placeholder">暂无描述</p>
            
            <div class="kb-meta">
              <div class="meta-item">
                <span class="meta-label">创建时间：</span>
                <span class="meta-value">{{ formatDate(kb.created_at) }}</span>
              </div>
              <div class="meta-item">
                <span class="meta-label">更新时间：</span>
                <span class="meta-value">{{ formatDate(kb.updated_at) }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 编辑知识库模态框 -->
      <div v-if="showEditModal" class="modal-overlay" @click="showEditModal = false">
        <div class="modal-content" @click.stop>
          <div class="modal-header">
            <h2>编辑知识库</h2>
            <button class="close-btn" @click="showEditModal = false">×</button>
          </div>
          <div class="modal-body">
            <div class="form-group">
              <label>知识库名称</label>
              <input
                v-model="editForm.name"
                type="text"
                class="form-input"
                placeholder="请输入知识库名称"
              />
            </div>
            <div class="form-group">
              <label>知识库描述</label>
              <textarea
                v-model="editForm.description"
                class="form-textarea"
                rows="3"
                placeholder="请输入知识库描述（可选）"
              ></textarea>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn-cancel" @click="showEditModal = false">取消</button>
            <button class="btn-save" @click="saveEdit" :disabled="!editForm.name.trim()">保存</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { listKnowledgeBases, deleteKnowledgeBase, type KnowledgeBase } from '@/services/api'

const router = useRouter()

const knowledgeBases = ref<KnowledgeBase[]>([])
const loading = ref(false)
const showEditModal = ref(false)
const editForm = ref({
  id: '',
  name: '',
  description: ''
})

// 加载知识库列表
const loadKnowledgeBases = async () => {
  try {
    loading.value = true
    const response = await listKnowledgeBases()
    if (response.success && response.knowledge_bases) {
      knowledgeBases.value = response.knowledge_bases
    } else {
      console.error('加载知识库列表失败:', response.error)
    }
  } catch (error) {
    console.error('加载知识库列表失败:', error)
  } finally {
    loading.value = false
  }
}

// 删除知识库
const deleteKB = async (kb: KnowledgeBase) => {
  if (!confirm(`确定要删除知识库"${kb.name}"吗？此操作不可恢复。`)) {
    return
  }

  try {
    const response = await deleteKnowledgeBase(kb.id)
    if (response.success) {
      await loadKnowledgeBases()
    } else {
      alert(`删除失败: ${response.error}`)
    }
  } catch (error: any) {
    alert(`删除失败: ${error.message || error}`)
  }
}

// 编辑知识库
const editKnowledgeBase = (kb: KnowledgeBase) => {
  editForm.value = {
    id: kb.id,
    name: kb.name,
    description: kb.description || ''
  }
  showEditModal.value = true
}

// 保存编辑（注意：目前后端没有更新接口，这里先留空，后续可以添加）
const saveEdit = async () => {
  // TODO: 实现更新知识库API
  alert('更新功能待实现')
  showEditModal.value = false
}

// 查看知识库
const viewKnowledgeBase = (kbId: string) => {
  router.push(`/chunker?kb_id=${kbId}`)
}

// 跳转到创建页面
const goToCreate = () => {
  router.push('/chunker')
}

// 返回聊天界面
const goToChat = () => {
  router.push('/')
}

// 格式化日期
const formatDate = (dateString: string) => {
  const date = new Date(dateString)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

onMounted(() => {
  loadKnowledgeBases()
})
</script>

<style scoped>
.kb-manage-container {
  min-height: 100vh;
  background: #f5f5f5;
  padding: 2rem 0;
}

.container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 1rem;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 2rem;
}

.title {
  font-size: 2rem;
  font-weight: 700;
  color: #374151;
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.icon {
  font-size: 2.5rem;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.back-chat-btn {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.6rem 1.25rem;
  background: #f3f4f6;
  color: #374151;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  font-size: 0.95rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.back-chat-btn:hover {
  background: #e5e7eb;
}

.create-btn {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 1.5rem;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 1rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.create-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
}

.loading-state {
  text-align: center;
  padding: 4rem 0;
}

.spinner {
  width: 40px;
  height: 40px;
  border: 4px solid #e5e7eb;
  border-top: 4px solid #667eea;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin: 0 auto 1rem;
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

.empty-state {
  text-align: center;
  padding: 4rem 0;
}

.empty-icon {
  font-size: 4rem;
  margin-bottom: 1rem;
}

.empty-state h3 {
  color: #374151;
  margin-bottom: 0.5rem;
}

.empty-state p {
  color: #6b7280;
  margin-bottom: 1.5rem;
}

.create-empty-btn {
  padding: 0.75rem 1.5rem;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 1rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.create-empty-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
}

.kb-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 1.5rem;
}

.kb-card {
  background: white;
  border-radius: 12px;
  padding: 1.5rem;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  cursor: pointer;
  transition: all 0.2s;
}

.kb-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
}

.kb-card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 1rem;
}

.kb-name {
  font-size: 1.25rem;
  font-weight: 600;
  color: #374151;
  margin: 0;
  flex: 1;
}

.kb-actions {
  display: flex;
  gap: 0.5rem;
}

.action-btn {
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s;
  background: #f3f4f6;
  color: #6b7280;
}

.action-btn:hover {
  background: #e5e7eb;
}

.edit-btn:hover {
  background: #dbeafe;
  color: #2563eb;
}

.delete-btn:hover {
  background: #fee2e2;
  color: #dc2626;
}

.kb-description {
  color: #6b7280;
  font-size: 0.875rem;
  margin-bottom: 1rem;
  min-height: 2.5rem;
}

.kb-description.placeholder {
  color: #9ca3af;
  font-style: italic;
}

.kb-meta {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding-top: 1rem;
  border-top: 1px solid #e5e7eb;
}

.meta-item {
  font-size: 0.75rem;
  color: #9ca3af;
}

.meta-label {
  font-weight: 500;
}

.meta-value {
  margin-left: 0.25rem;
}

/* 模态框样式 */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-content {
  background: white;
  border-radius: 12px;
  width: 90%;
  max-width: 500px;
  max-height: 90vh;
  overflow-y: auto;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1.5rem;
  border-bottom: 1px solid #e5e7eb;
}

.modal-header h2 {
  margin: 0;
  color: #374151;
  font-size: 1.5rem;
}

.close-btn {
  width: 32px;
  height: 32px;
  border: none;
  background: none;
  font-size: 1.5rem;
  color: #6b7280;
  cursor: pointer;
  border-radius: 6px;
  transition: all 0.2s;
}

.close-btn:hover {
  background: #f3f4f6;
  color: #374151;
}

.modal-body {
  padding: 1.5rem;
}

.form-group {
  margin-bottom: 1.5rem;
}

.form-group label {
  display: block;
  margin-bottom: 0.5rem;
  color: #374151;
  font-weight: 500;
  font-size: 0.875rem;
}

.form-input,
.form-textarea {
  width: 100%;
  padding: 0.75rem;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  font-size: 1rem;
  transition: all 0.2s;
  box-sizing: border-box;
}

.form-input:focus,
.form-textarea:focus {
  outline: none;
  border-color: #667eea;
  box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
}

.form-textarea {
  resize: vertical;
  font-family: inherit;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 1rem;
  padding: 1.5rem;
  border-top: 1px solid #e5e7eb;
}

.btn-cancel,
.btn-save {
  padding: 0.625rem 1.25rem;
  border: none;
  border-radius: 6px;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-cancel {
  background: #f3f4f6;
  color: #374151;
}

.btn-cancel:hover {
  background: #e5e7eb;
}

.btn-save {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

.btn-save:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(102, 126, 234, 0.3);
}

.btn-save:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

@media (max-width: 768px) {
  .header {
    flex-direction: column;
    align-items: flex-start;
    gap: 1rem;
  }

  .kb-grid {
    grid-template-columns: 1fr;
  }
}
</style>

