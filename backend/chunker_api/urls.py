from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from . import views

urlpatterns = [
    # 分块相关
    path('chunk/', views.chunk_document, name='chunk_document'),
    path('chunkers/', views.get_chunker_info, name='get_chunker_info'),
    path('health/', views.health_check, name='health_check'),
    path('media/<path:file_path>', views.serve_extracted_image, name='serve_extracted_image'),
    
    # 用户认证相关
    path('auth/register/', views.register, name='register'),
    path('auth/login/', views.user_login, name='login'),
    path('auth/logout/', views.user_logout, name='logout'),
    path('auth/user/', views.get_current_user, name='get_current_user'),
    path('auth/user/update/', views.update_user_profile, name='update_user_profile'),
    
    # 知识库管理相关
    path('knowledge-bases/', views.list_knowledge_bases, name='list_knowledge_bases'),
    path('knowledge-bases/create/', views.create_knowledge_base, name='create_knowledge_base'),
    path('knowledge-bases/<str:kb_id>/', views.get_knowledge_base, name='get_knowledge_base'),
    path('knowledge-bases/<str:kb_id>/delete/', views.delete_knowledge_base, name='delete_knowledge_base'),
    
    # 聊天记录相关
    path('chat/sessions/', views.list_chat_sessions, name='list_chat_sessions'),
    path('chat/sessions/create/', views.create_chat_session, name='create_chat_session'),
    path('chat/sessions/<str:session_id>/messages/', views.list_chat_messages, name='list_chat_messages'),
    path('chat/sessions/<str:session_id>/delete/', views.delete_chat_session, name='delete_chat_session'),
    path('chat/sessions/<str:session_id>/rename/', views.rename_chat_session, name='rename_chat_session'),

    # 多模态问答相关
    path('qa/hybrid/', views.hybrid_qa, name='hybrid_qa'),
    # path('qa/ask/', views.multimodal_qa, name='multimodal_qa'),
]

# 开发环境下提供媒体文件访问
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
