from django.db import models
from django.contrib.auth.models import AbstractUser
import uuid


class User(AbstractUser):
    """扩展用户模型"""
    USER_TYPE_CHOICES = [
        ('personal', '个人用户'),
        ('enterprise', '企业用户'),
    ]

    user_type = models.CharField(
        max_length=20,
        choices=USER_TYPE_CHOICES,
        default='personal',
        verbose_name='用户类型'
    )
    employee_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name='工号'
    )

    email = models.EmailField(unique=True, verbose_name='邮箱')
    age = models.IntegerField(null=True, blank=True, verbose_name='年龄')
    GENDER_CHOICES = [
        ('M', '男'),
        ('F', '女'),
        ('O', '其他'),
    ]
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES, null=True, blank=True, verbose_name='性别')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        verbose_name = '用户'
        verbose_name_plural = '用户'
        db_table = 'users'

    def __str__(self):
        return self.username


## 用户画像

from django.db import models
from django.utils import timezone
from datetime import timedelta


class UserPersona(models.Model):
    """
    用户画像（单表）
    用于 RAG 推理
    """

    user = models.OneToOneField(
        'User',
        on_delete=models.CASCADE,
        related_name='persona'
    )

    # ===== 角色维度（核心） =====
    ROLE_CHOICES = [
        ('enterprise', '企业用户'),
        ('external', '外来用户'),
        ('local', '本地居民'),
    ]
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default='external',
        verbose_name='用户角色'
    )

    # ===== 年龄段 =====
    AGE_GROUP_CHOICES = [
        ('youth', '青年'),
        ('elder', '老年'),
    ]
    age_group = models.CharField(
        max_length=10,
        choices=AGE_GROUP_CHOICES,
        default='youth',
        verbose_name='年龄段'
    )

    # ===== 活跃度原始数据 =====
    total_questions = models.PositiveIntegerField(default=0)
    active_days = models.PositiveIntegerField(default=0)
    last_active_date = models.DateField(null=True, blank=True)

    # ===== 活跃度等级（系统计算） =====
    FREQUENCY_CHOICES = [
        ('new', '新用户'),
        ('normal', '普通用户'),
        ('high', '高频用户'),
    ]
    frequency = models.CharField(
        max_length=10,
        choices=FREQUENCY_CHOICES,
        default='new',
        verbose_name='活跃度'
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'user_personas'


class KnowledgeBase(models.Model):
    """知识库模型"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, verbose_name='ID')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='knowledge_bases', verbose_name='用户')
    name = models.CharField(max_length=200, verbose_name='知识库名称')
    description = models.TextField(blank=True, null=True, verbose_name='描述')
    collection_name = models.CharField(max_length=200, unique=True, verbose_name='Chroma集合名称')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        verbose_name = '知识库'
        verbose_name_plural = '知识库'
        db_table = 'knowledge_bases'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} - {self.name}"

    def save(self, *args, **kwargs):
        # 如果collection_name为空，生成一个唯一的名称
        if not self.collection_name:
            self.collection_name = f"kb_{self.user.username}_{self.id.hex[:8]}"
        super().save(*args, **kwargs)


class ChatSession(models.Model):
    """聊天会话"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, verbose_name='ID')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_sessions', verbose_name='用户')
    title = models.CharField(max_length=200, verbose_name='标题')
    knowledge_base = models.ForeignKey(KnowledgeBase, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='chat_sessions', verbose_name='知识库')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        verbose_name = '聊天会话'
        verbose_name_plural = '聊天会话'
        db_table = 'chat_sessions'
        ordering = ['-updated_at']

    def __str__(self):
        return f"{self.user.username} - {self.title}"


class ChatMessage(models.Model):
    """聊天消息"""
    ROLE_CHOICES = [
        ('user', '用户'),
        ('assistant', '助手'),
    ]
    id = models.BigAutoField(primary_key=True)
    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name='messages', verbose_name='会话')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, verbose_name='角色')
    content = models.TextField(verbose_name='内容')
    sources = models.JSONField(null=True, blank=True, verbose_name='参考资料')
    images = models.JSONField(null=True, blank=True, verbose_name='图片')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        verbose_name = '聊天消息'
        verbose_name_plural = '聊天消息'
        db_table = 'chat_messages'
        ordering = ['created_at']

    def __str__(self):
        return f"{self.session.title} - {self.role}"




