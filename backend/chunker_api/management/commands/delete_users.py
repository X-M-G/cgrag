import chromadb
import os
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db import transaction
from django.conf import settings

User = get_user_model()


class Command(BaseCommand):
    help = '干净地删除用户：同步清理数据库记录与本地 ChromaDB 持久化集合'

    def add_arguments(self, parser):
        parser.add_argument('--all', action='store_true', help='删除所有非超级用户')
        parser.add_argument('--id', type=int, help='删除指定 ID 的用户')

    def handle(self, *args, **options):
        # 1. 确定范围
        if options['all']:
            users_to_delete = User.objects.filter(is_superuser=False)
            confirm_msg = f"确定要删除所有普通用户（共 {users_to_delete.count()} 人）及其向量库数据吗？[yes/no]: "
        elif options['id']:
            users_to_delete = User.objects.filter(id=options['id'])
            confirm_msg = f"确定要删除用户 ID 为 {options['id']} 的数据吗？[yes/no]: "
        else:
            raise CommandError("请指定参数 --all 或 --id")

        if not users_to_delete.exists():
            self.stdout.write(self.style.WARNING("未找到匹配的用户。"))
            return

        confirm = input(confirm_msg)
        if confirm.lower() != 'yes':
            self.stdout.write(self.style.NOTICE("操作已取消。"))
            return

        # 2. 初始化本地持久化客户端
        try:
            # 根据你的目录结构，chroma_db 文件夹在项目根目录
            # BASE_DIR 通常在 settings 中定义为项目根目录
            chroma_path = os.path.join(settings.BASE_DIR, 'chroma_db')

            self.stdout.write(f"正在连接本地向量库: {chroma_path}")
            # 使用 PersistentClient 而不是 HttpClient
            chroma_client = chromadb.PersistentClient(path=chroma_path)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"无法连接到本地 ChromaDB: {e}"))
            return

        # 3. 执行删除
        success_count = 0
        for user in users_to_delete:
            username = user.username
            self.stdout.write(f"正在处理用户: {username}...")

            try:
                with transaction.atomic():
                    # 获取该用户关联的集合名称
                    kb_collections = list(user.knowledge_bases.values_list('collection_name', flat=True))

                    # 物理删除集合
                    for col_name in kb_collections:
                        try:
                            chroma_client.delete_collection(name=col_name)
                            self.stdout.write(self.style.SUCCESS(f"  - 已删除向量集合: {col_name}"))
                        except Exception:
                            self.stdout.write(self.style.WARNING(f"  - 集合 {col_name} 不存在，跳过"))

                    # 删除数据库记录
                    user.delete()
                    success_count += 1
                    self.stdout.write(self.style.SUCCESS(f"  - 用户 {username} 的所有数据库记录已清理"))

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"清理用户 {username} 失败: {e}"))

        self.stdout.write(self.style.SUCCESS(f"\n任务完成！成功删除 {success_count} 个用户。"))