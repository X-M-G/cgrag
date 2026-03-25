import os
import json
import tempfile
import shutil
import base64
import time
from django.http import JsonResponse, HttpResponse, Http404, StreamingHttpResponse
from django.http import JsonResponse, HttpResponse, Http404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.forms.models import model_to_dict
import logging
import traceback
from utils.Tools.excel_validator import EnterpriseUserValidator
from utils.Tools.history import get_session_last_n_dialogue_pairs
from .models import User, KnowledgeBase, ChatSession, ChatMessage

from utils.chunk.document_processor import (
    process_qa_chunker, process_law_chunker, process_basic_chunker,
    process_semantic_chunker, process_policy_chunker, process_table_chunker,
    process_multimodal_chunker, process_text_embedding, generate_jsonl_content
)
# 导入分块器和编码器
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

logger = logging.getLogger(__name__)

try:
    from utils.chunk.MultimodalEncoder import MultimodalEncoder
    ENCODER_AVAILABLE = True
except ImportError:
    ENCODER_AVAILABLE = False
    logger.warning("MultimodalEncoder 未导入，编码功能将不可用")



from utils.chunk.QAspilter import run as qa_run
from utils.chunk.LawSpilter import LawSpilter
from utils.chunk.optimized_semantic_spilter import split_text_to_chunks, split_docx_to_chunks, split_pdf_to_chunks
from utils.chunk.PolicyAnnouncementSpilter import PolicyAnnouncementSpilter
from utils.chunk.TableSpilter import TableSpilter
from utils.chunk.MultimodalSpilter import MultimodalSpilter
from utils.chunk.BasicSpilter import BasicSpilter

# 导入doc文件处理库
try:
    from docx import Document as DocxDocument
    import win32com.client
    DOC_SUPPORT = True
except ImportError:
    DOC_SUPPORT = False


@csrf_exempt
@require_http_methods(["POST"])
def chunk_document(request):
    """
    文档分块API接口
    
    请求参数:
    - file: 上传的文件
    - chunker_type: 分块器类型 (qa, law, semantic, policy, table)
    - chunker_params: 分块器参数 (可选)
    """
    try:
        # 调试信息
        logger.info(f"请求方法: {request.method}")
        logger.info(f"请求头: {dict(request.headers)}")
        logger.info(f"FILES keys: {list(request.FILES.keys())}")
        logger.info(f"POST keys: {list(request.POST.keys())}")
        
        # 获取上传的文件
        if 'file' not in request.FILES:
            logger.error("没有找到文件字段")
            return JsonResponse({'error': '没有上传文件'}, status=400)
        
        file = request.FILES['file']
        chunker_type = request.POST.get('chunker_type', 'semantic')
        
        logger.info(f"文件名称: {file.name}, 文件大小: {file.size}, 分块器类型: {chunker_type}")
        
        # 验证文件类型（multimodal支持更多格式）
        allowed_extensions = ['.txt', '.pdf', '.docx', '.doc', '.xlsx', '.xls']
        if chunker_type == 'multimodal':
            # 多模态分块器支持更多格式
            allowed_extensions.extend(['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.mp4', '.avi', '.mov'])
        
        file_ext = os.path.splitext(file.name)[1].lower()
        if file_ext not in allowed_extensions:
            return JsonResponse({
                'error': f'不支持的文件类型: {file_ext}',
                'supported_types': allowed_extensions
            }, status=400)
        
        # 保存临时文件
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as temp_file:
            for chunk in file.chunks():
                temp_file.write(chunk)
            temp_file_path = temp_file.name
        
        try:
            # 获取知识库ID（如果提供）
            knowledge_base_id = request.POST.get('knowledge_base_id', None)
            
            # 根据分块器类型处理文档
            if chunker_type == 'by_length':
                chunk_size = int(request.POST.get('chunk_size', 1000))
                chunk_overlap = int(request.POST.get('chunk_overlap', 200))
                result = process_basic_chunker(temp_file_path, file.name, 'by_length', chunk_size, chunk_overlap)
            elif chunker_type == 'by_punctuation':
                chunk_size = int(request.POST.get('chunk_size', 1000))
                chunk_overlap = int(request.POST.get('chunk_overlap', 200))
                result = process_basic_chunker(temp_file_path, file.name, 'by_punctuation', chunk_size, chunk_overlap)
            elif chunker_type == 'recursive':
                chunk_size = int(request.POST.get('chunk_size', 1000))
                chunk_overlap = int(request.POST.get('chunk_overlap', 200))
                result = process_basic_chunker(temp_file_path, file.name, 'recursive', chunk_size, chunk_overlap)
            elif chunker_type == 'by_page':
                result = process_basic_chunker(temp_file_path, file.name, 'by_page')
            elif chunker_type == 'qa':
                result = process_qa_chunker(temp_file_path, file.name)
            elif chunker_type == 'law':
                result = process_law_chunker(temp_file_path, file.name)
            elif chunker_type == 'semantic':
                # 获取语义分块器参数
                min_chars = int(request.POST.get('min_chars', 400))
                max_chars = int(request.POST.get('max_chars', 800))
                window_size = int(request.POST.get('window_size', 4))
                result = process_semantic_chunker(temp_file_path, file.name, min_chars, max_chars, window_size)
            elif chunker_type == 'policy':
                result = process_policy_chunker(temp_file_path, file.name)
            elif chunker_type == 'table':
                result = process_table_chunker(temp_file_path, file.name)
            elif chunker_type == 'multimodal':
                # 获取多模态分块器参数
                text_chunk_size = int(request.POST.get('text_chunk_size', 1000))
                text_chunk_overlap = int(request.POST.get('text_chunk_overlap', 200))
                min_chars = int(request.POST.get('min_chars', 400))
                max_chars = int(request.POST.get('max_chars', 800))
                window_size = int(request.POST.get('window_size', 4))
                # 默认启用编码
                result = process_multimodal_chunker(
                    temp_file_path, 
                    file.name, 
                    enable_encoding=True, 
                    request=request,
                    knowledge_base_id=knowledge_base_id,
                    text_chunk_size=text_chunk_size,
                    text_chunk_overlap=text_chunk_overlap,
                    min_chars=min_chars,
                    max_chars=max_chars,
                    window_size=window_size
                )
            else:
                return JsonResponse({'error': f'不支持的分块器类型: {chunker_type}'}, status=400)
            
            # 对纯文本数据进行向量化（多模态数据已在process_multimodal_chunker中处理）
            if chunker_type != 'multimodal' and chunker_type in ['by_length', 'by_punctuation', 'recursive', 'by_page', 'semantic', 'qa', 'law', 'policy', 'table']:
                try:
                    # 默认启用向量化存储
                    encoding_stats = process_text_embedding(
                        chunks=result['chunks'],
                        chunker_type=chunker_type,
                        file_name=file.name,
                        knowledge_base_id=knowledge_base_id,
                        request=request
                    )
                    if encoding_stats:
                        result['statistics']['encoding'] = encoding_stats
                except Exception as e:
                    logger.warning(f"文本向量化失败: {e}")
                    # 向量化失败不影响分块结果返回
            
            # 生成JSONL格式的结果
            jsonl_content = generate_jsonl_content(result['chunks'])
            
            return JsonResponse({
                'success': True,
                'chunker_type': chunker_type,
                'file_name': file.name,
                'chunks': result['chunks'],
                'jsonl_content': jsonl_content,
                'metadata': result.get('metadata', {}),
                'statistics': result.get('statistics', {})
            })
            
        finally:
            # 清理临时文件
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
                
    except Exception as e:
        logger.error(f"分块处理失败: {str(e)}")
        return JsonResponse({'error': f'处理失败: {str(e)}'}, status=500)



@require_http_methods(["GET"])
def get_chunker_info(request):
    """获取分块器信息"""
    chunkers_info = {
        # 基础切分方式
        'by_length': {
            'name': '按长度切分',
            'description': '按固定字符长度切分文本，简单快速',
            'supported_formats': ['.txt', '.pdf', '.docx'],
            'features': ['固定长度', '可设置重叠', '处理快速'],
            'category': 'basic',
            'params': {
                'chunk_size': {'type': 'number', 'default': 1000, 'min': 100, 'max': 5000, 'label': '块大小（字符）'},
                'chunk_overlap': {'type': 'number', 'default': 200, 'min': 0, 'max': 500, 'label': '重叠大小（字符）'}
            }
        },
        'by_punctuation': {
            'name': '按标点符号切分',
            'description': '在标点符号处切分，保持句子完整性',
            'supported_formats': ['.txt', '.pdf', '.docx'],
            'features': ['句子完整', '标点识别', '上下文保留'],
            'category': 'basic',
            'params': {
                'chunk_size': {'type': 'number', 'default': 1000, 'min': 100, 'max': 5000, 'label': '目标块大小（字符）'},
                'chunk_overlap': {'type': 'number', 'default': 200, 'min': 0, 'max': 500, 'label': '重叠大小（字符）'}
            }
        },
        'recursive': {
            'name': '智能递归切分',
            'description': '按分隔符优先级递归切分，智能选择最佳分割点',
            'supported_formats': ['.txt', '.pdf', '.docx'],
            'features': ['递归切分', '智能分隔', '结构保持'],
            'category': 'basic',
            'params': {
                'chunk_size': {'type': 'number', 'default': 1000, 'min': 100, 'max': 5000, 'label': '目标块大小（字符）'},
                'chunk_overlap': {'type': 'number', 'default': 200, 'min': 0, 'max': 500, 'label': '重叠大小（字符）'}
            }
        },
        'by_page': {
            'name': '按页切分',
            'description': '按文档页面切分，保留页面结构',
            'supported_formats': ['.pdf', '.docx'],
            'features': ['页面保持', '结构完整', '简单直观'],
            'category': 'basic',
            'params': {}
        },
        # 进阶切分方式
        'semantic': {
            'name': '语义分块器',
            'description': '基于语义相似度的智能分块',
            'supported_formats': ['.txt', '.pdf', '.docx'],
            'features': ['语义分析', '智能边界', '上下文保持'],
            'category': 'advanced',
            'params': {
                'min_chars': {'type': 'number', 'default': 400, 'min': 100, 'max': 2000, 'label': '最小字符数'},
                'max_chars': {'type': 'number', 'default': 800, 'min': 200, 'max': 3000, 'label': '最大字符数'},
                'window_size': {'type': 'number', 'default': 4, 'min': 2, 'max': 10, 'label': '窗口大小'}
            }
        },
        'multimodal': {
            'name': '多模态分块器',
            'description': '支持文本、图片、视频等多种模态的分块处理',
            'supported_formats': ['.txt', '.pdf', '.docx', '.jpg', '.png', '.jpeg', '.gif', '.mp4', '.avi', '.mov'],
            'features': ['多模态支持', '图片提取', '视频处理', '文本分块'],
            'category': 'advanced',
            'params': {
                'text_chunk_size': {'type': 'number', 'default': 1000, 'min': 500, 'max': 3000, 'label': '文本块大小'},
                'text_chunk_overlap': {'type': 'number', 'default': 200, 'min': 0, 'max': 500, 'label': '文本块重叠'},
                'min_chars': {'type': 'number', 'default': 400, 'min': 100, 'max': 2000, 'label': '最小字符数'},
                'max_chars': {'type': 'number', 'default': 800, 'min': 200, 'max': 3000, 'label': '最大字符数'},
                'window_size': {'type': 'number', 'default': 4, 'min': 2, 'max': 10, 'label': '窗口大小'}
            }
        },
        # 专用切分方式
        'qa': {
            'name': '问答分块器',
            'description': '专门处理问答类文档，提取Q/A对',
            'supported_formats': ['.txt', '.pdf', '.docx'],
            'features': ['Q/A提取', '语义保持', '重叠处理'],
            'category': 'specialized'
        },
        'law': {
            'name': '法律法规分块器',
            'description': '按"条"进行分块，适用于法律法规文档',
            'supported_formats': ['.txt', '.pdf', '.docx'],
            'features': ['条文识别', '章节保持', '元数据提取'],
            'category': 'specialized'
        },
        'policy': {
            'name': '政策公告分块器',
            'description': '基于一级标题分块，适用于政策公告',
            'supported_formats': ['.txt', '.pdf', '.docx'],
            'features': ['标题识别', '表格处理', '时间提取'],
            'category': 'specialized'
        },
        'table': {
            'name': '表格分块器',
            'description': '专门处理表格数据，按行分块',
            'supported_formats': ['.pdf', '.docx', '.xlsx', '.xls'],
            'features': ['表头保持', '行分块', '数据清洗'],
            'category': 'specialized'
        }
    }
    
    return JsonResponse({
        'success': True,
        'chunkers': chunkers_info
    })


@require_http_methods(["GET"])
def health_check(request):
    """健康检查接口"""
    return JsonResponse({
        'status': 'healthy',
        'message': '分块器API服务正常运行'
    })


@require_http_methods(["GET"])
def serve_extracted_image(request, file_path):
    """提供提取的图片文件访问"""
    try:
        from django.conf import settings
        
        # 构建完整路径
        full_path = os.path.join(settings.EXTRACTED_IMAGES_DIR, file_path)
        
        # 安全检查：确保路径在允许的目录内
        full_path = os.path.normpath(full_path)
        allowed_dir = os.path.normpath(settings.EXTRACTED_IMAGES_DIR)
        if not full_path.startswith(allowed_dir):
            raise Http404("文件路径不安全")
        
        if not os.path.exists(full_path):
            raise Http404("图片文件不存在")
        
        # 读取文件
        with open(full_path, 'rb') as f:
            image_data = f.read()
        
        # 确定Content-Type
        ext = os.path.splitext(full_path)[1].lower()
        content_types = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.bmp': 'image/bmp',
            '.webp': 'image/webp'
        }
        content_type = content_types.get(ext, 'image/jpeg')
        
        response = HttpResponse(image_data, content_type=content_type)
        response['Cache-Control'] = 'public, max-age=3600'  # 缓存1小时
        return response
        
    except Http404:
        raise
    except Exception as e:
        logger.error(f"提供图片文件失败: {e}")
        raise Http404("无法提供图片文件")


# ==================== 用户认证相关API ====================

@csrf_exempt
@require_http_methods(["POST"])
def register(request):
    """用户注册（支持个人用户和企业用户）"""
    try:
        data = json.loads(request.body)
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        email = data.get('email', '').strip()
        age = data.get('age')
        gender = data.get('gender', '').strip()
        user_type = data.get('user_type', 'personal').strip()  # 新增：用户类型
        employee_id = data.get('employee_id', '').strip()  # 新增：工号

        # 验证必填字段 用户名 密码  年龄
        if not username or not password or not age:
            return JsonResponse({
                'success': False,
                'error': '用户名、密码、年龄为必填项'
            }, status=400)

        # 企业用户特殊验证
        if user_type == 'enterprise':
            if not employee_id:
                return JsonResponse({
                    'success': False,
                    'error': '企业用户必须提供工号'
                }, status=400)

            # 验证企业用户信息
            validator = EnterpriseUserValidator()
            validation_result = validator.validate_enterprise_user(
                name=username,
                employee_id=employee_id
            )

            if not validation_result['valid']:
                return JsonResponse({
                    'success': False,
                    'error': validation_result['message']
                }, status=400)

            # 验证通过，可以使用 validation_result['user_info'] 获取更多信息
            logger.info(f"企业用户验证通过: {username} ({employee_id})")

        # 个人用户需要邮箱
        if user_type == 'personal' and not email:
            return JsonResponse({
                'success': False,
                'error': '个人用户邮箱为必填项'
            }, status=400)

        # 检查用户名是否已存在
        if User.objects.filter(username=username).exists():
            return JsonResponse({
                'success': False,
                'error': '用户名已存在'
            }, status=400)

        # 检查邮箱是否已存在（如果提供）
        if email and User.objects.filter(email=email).exists():
            return JsonResponse({
                'success': False,
                'error': '邮箱已被注册'
            }, status=400)

        # 检查工号是否已被注册（企业用户）
        if user_type == 'enterprise' and User.objects.filter(employee_id=employee_id).exists():
            return JsonResponse({
                'success': False,
                'error': '该工号已被注册'
            }, status=400)

        # 创建用户
        user = User.objects.create_user(
            username=username,
            email=email if email else f"{employee_id}@company.com",  # 企业用户默认邮箱
            password=password,
            user_type=user_type,
            employee_id=employee_id if user_type == 'enterprise' else None,
            age=age if age else None,
            gender=gender if gender in ['M', 'F', 'O'] else None
        )

        # 自动登录
        login(request, user)
        from .models import UserPersona
        from utils.Tools.get_age_group import get_age_group
        age_group = get_age_group(age)
        role = 'enterprise' if user_type == 'enterprise' else 'local'
        UserPersona.objects.create(
            user=user,
            age_group=age_group,
            role=role
        )

        return JsonResponse({
            'success': True,
            'message': '注册成功',
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'user_type': user.user_type,
                'employee_id': user.employee_id,
                'age': user.age,
                'gender': user.gender,
            }
        })

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': '无效的JSON数据'
        }, status=400)
    except Exception as e:
        logger.error(f"注册失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return JsonResponse({
            'success': False,
            'error': f'注册失败: {str(e)}'
        }, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def user_login(request):
    """用户登录"""
    try:
        data = json.loads(request.body)
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        
        if not username or not password:
            return JsonResponse({
                'success': False,
                'error': '用户名和密码不能为空'
            }, status=400)
        
        # 认证用户
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            login(request, user)
            return JsonResponse({
                'success': True,
                'message': '登录成功',
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                    'user_type': user.user_type,
                    'employee_id': user.employee_id,
                    'age': user.age,
                    'gender': user.gender,
                }
            })
        else:
            return JsonResponse({
                'success': False,
                'error': '用户名或密码错误'
            }, status=401)
    
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': '无效的JSON数据'
        }, status=400)
    except Exception as e:
        logger.error(f"登录失败: {e}")
        return JsonResponse({
            'success': False,
            'error': f'登录失败: {str(e)}'
        }, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def user_logout(request):
    """用户登出（CSRF豁免，便于前后端分离场景）"""
    try:
        logout(request)
        # 同时清理会话ID Cookie（可选，Django logout 已处理）
        resp = JsonResponse({'success': True, 'message': '登出成功'})
        resp.delete_cookie(settings.SESSION_COOKIE_NAME)
        return resp
    except Exception as e:
        logger.error(f"登出失败: {e}")
        return JsonResponse({'success': False, 'error': '登出失败'}, status=500)


@csrf_exempt
@login_required
@require_http_methods(["POST", "PATCH"])
def update_user_profile(request):
    """更新当前登录用户的个人信息"""
    try:
        user = request.user
        data = json.loads(request.body)

        # 允许更新的字段
        if 'email' in data:
            new_email = data['email'].strip()
            if new_email and new_email != user.email:
                # 检查新邮箱是否已被其他用户注册
                if User.objects.filter(email=new_email).exclude(pk=user.pk).exists():
                    return JsonResponse({
                        'success': False,
                        'error': '该邮箱已被其他用户注册'
                    }, status=400)
                user.email = new_email

        if 'age' in data:
            user.age = data['age']

        if 'gender' in data:
            gender = data['gender'].strip()
            if gender in ['M', 'F', 'O']:
                user.gender = gender

        # 保存更改
        user.save()

        return JsonResponse({
            'success': True,
            'message': '用户信息更新成功',
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'user_type': user.user_type,
                'employee_id': user.employee_id,
                'age': user.age,
                'gender': user.gender,
            }
        })

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': '无效的JSON数据'
        }, status=400)
    except Exception as e:
        logger.error(f"更新用户信息失败: {e}")
        return JsonResponse({
            'success': False,
            'error': f'更新失败: {str(e)}'
        }, status=500)


@require_http_methods(["GET"])
def get_current_user(request):
    """获取当前登录用户信息"""
    if request.user.is_authenticated:
        return JsonResponse({
            'success': True,
            'user': {
                'id': request.user.id,
                'username': request.user.username,
                'email': request.user.email,
                'user_type': request.user.user_type,
                'employee_id': request.user.employee_id,
                'age': request.user.age,
                'gender': request.user.gender,
            }
        })
    else:
        return JsonResponse({
            'success': False,
            'error': '未登录'
        }, status=401)


# ==================== 知识库管理相关API ====================

@csrf_exempt
@require_http_methods(["POST"])
def create_knowledge_base(request):
    """创建知识库"""
    if not request.user.is_authenticated:
        return JsonResponse({
            'success': False,
            'error': '请先登录'
        }, status=401)
    
    try:
        data = json.loads(request.body)
        name = data.get('name', '').strip()
        description = data.get('description', '').strip()
        
        if not name:
            return JsonResponse({
                'success': False,
                'error': '知识库名称不能为空'
            }, status=400)
        
        # 创建知识库
        kb = KnowledgeBase.objects.create(
            user=request.user,
            name=name,
            description=description if description else None
        )
        
        return JsonResponse({
            'success': True,
            'message': '知识库创建成功',
            'knowledge_base': {
                'id': str(kb.id),
                'name': kb.name,
                'description': kb.description,
                'collection_name': kb.collection_name,
                'created_at': kb.created_at.isoformat(),
            }
        })
    
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': '无效的JSON数据'
        }, status=400)
    except Exception as e:
        logger.error(f"创建知识库失败: {e}")
        return JsonResponse({
            'success': False,
            'error': f'创建知识库失败: {str(e)}'
        }, status=500)


@require_http_methods(["GET"])
def list_knowledge_bases(request):
    """获取用户的知识库列表"""
    if not request.user.is_authenticated:
        return JsonResponse({
            'success': False,
            'error': '请先登录'
        }, status=401)
    
    try:
        knowledge_bases = KnowledgeBase.objects.filter(user=request.user)
        
        kb_list = [{
            'id': str(kb.id),
            'name': kb.name,
            'description': kb.description,
            'collection_name': kb.collection_name,
            'created_at': kb.created_at.isoformat(),
            'updated_at': kb.updated_at.isoformat(),
        } for kb in knowledge_bases]
        
        return JsonResponse({
            'success': True,
            'knowledge_bases': kb_list,
            'total': len(kb_list)
        })
    
    except Exception as e:
        logger.error(f"获取知识库列表失败: {e}")
        return JsonResponse({
            'success': False,
            'error': f'获取知识库列表失败: {str(e)}'
        }, status=500)


@require_http_methods(["GET"])
def get_knowledge_base(request, kb_id):
    """获取知识库详情"""
    if not request.user.is_authenticated:
        return JsonResponse({
            'success': False,
            'error': '请先登录'
        }, status=401)
    
    try:
        kb = KnowledgeBase.objects.get(id=kb_id, user=request.user)
        
        return JsonResponse({
            'success': True,
            'knowledge_base': {
                'id': str(kb.id),
                'name': kb.name,
                'description': kb.description,
                'collection_name': kb.collection_name,
                'created_at': kb.created_at.isoformat(),
                'updated_at': kb.updated_at.isoformat(),
            }
        })
    
    except KnowledgeBase.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': '知识库不存在或无权限访问'
        }, status=404)
    except Exception as e:
        logger.error(f"获取知识库详情失败: {e}")
        return JsonResponse({
            'success': False,
            'error': f'获取知识库详情失败: {str(e)}'
        }, status=500)


@csrf_exempt
@require_http_methods(["DELETE"])
def delete_knowledge_base(request, kb_id):
    """删除知识库"""
    if not request.user.is_authenticated:
        return JsonResponse({
            'success': False,
            'error': '请先登录'
        }, status=401)
    
    try:
        kb = KnowledgeBase.objects.get(id=kb_id, user=request.user)
        collection_name = kb.collection_name
        kb.delete()
        
        # TODO: 可选 - 删除Chroma中的集合数据
        # 这里可以添加删除Chroma集合的逻辑
        
        return JsonResponse({
            'success': True,
            'message': '知识库删除成功',
            'deleted_collection': collection_name
        })
    
    except KnowledgeBase.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': '知识库不存在或无权限访问'
        }, status=404)
    except Exception as e:
        logger.error(f"删除知识库失败: {e}")
        return JsonResponse({
            'success': False,
            'error': f'删除知识库失败: {str(e)}'
        }, status=500)


# 导入RAG服务
from .rag_service import RAGService

# ==================== 聊天记录相关API ====================

@csrf_exempt
@require_http_methods(["POST"])
def create_chat_session(request):
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'error': '请先登录'}, status=401)
    try:
        data = json.loads(request.body)
        title = (data.get('title') or '').strip()
        knowledge_base_id = data.get('knowledge_base_id')
        kb = None
        if knowledge_base_id:
            try:
                kb = KnowledgeBase.objects.get(id=knowledge_base_id, user=request.user)
            except KnowledgeBase.DoesNotExist:
                return JsonResponse({'success': False, 'error': '知识库不存在或无权限访问'}, status=404)
        if not title:
            title = '新对话'
        session = ChatSession.objects.create(user=request.user, title=title, knowledge_base=kb)
        return JsonResponse({'success': True, 'session': {
            'id': str(session.id),
            'title': session.title,
            'knowledge_base_id': str(kb.id) if kb else None,
            'created_at': session.created_at.isoformat(),
            'updated_at': session.updated_at.isoformat(),
        }})
    except Exception as e:
        logger.error(f"创建会话失败: {e}")
        return JsonResponse({'success': False, 'error': f'创建会话失败: {e}'}, status=500)


@require_http_methods(["GET"])
def list_chat_sessions(request):
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'error': '请先登录'}, status=401)
    sessions = ChatSession.objects.filter(user=request.user).order_by('-updated_at')
    data = [{
        'id': str(s.id),
        'title': s.title,
        'knowledge_base_id': str(s.knowledge_base.id) if s.knowledge_base else None,
        'created_at': s.created_at.isoformat(),
        'updated_at': s.updated_at.isoformat(),
    } for s in sessions]
    return JsonResponse({'success': True, 'sessions': data, 'total': len(data)})


@require_http_methods(["GET"])
def list_chat_messages(request, session_id):
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'error': '请先登录'}, status=401)
    try:
        session = ChatSession.objects.get(id=session_id, user=request.user)
    except ChatSession.DoesNotExist:
        return JsonResponse({'success': False, 'error': '会话不存在或无权限访问'}, status=404)
    messages = session.messages.all().order_by('created_at')
    data = [{
        'id': m.id,
        'role': m.role,
        'content': m.content,
        'sources': m.sources,
        'images': m.images,
        'created_at': m.created_at.isoformat(),
    } for m in messages]
    return JsonResponse({'success': True, 'messages': data})


@csrf_exempt
@require_http_methods(["DELETE"])
def delete_chat_session(request, session_id):
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'error': '请先登录'}, status=401)
    try:
        session = ChatSession.objects.get(id=session_id, user=request.user)
        session.delete()
        return JsonResponse({'success': True, 'message': '会话已删除'})
    except ChatSession.DoesNotExist:
        return JsonResponse({'success': False, 'error': '会话不存在或无权限访问'}, status=404)
    except Exception as e:
        logger.error(f"删除会话失败: {e}")
        return JsonResponse({'success': False, 'error': f'删除会话失败: {e}'}, status=500)

@csrf_exempt
@require_http_methods(["POST", "PATCH"])
def rename_chat_session(request, session_id):
    """重命名聊天会话"""
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'error': '请先登录'}, status=401)
    try:
        session = ChatSession.objects.get(id=session_id, user=request.user)
    except ChatSession.DoesNotExist:
        return JsonResponse({'success': False, 'error': '会话不存在或无权限访问'}, status=404)
    try:
        data = json.loads(request.body or '{}')
        title = (data.get('title') or '').strip()
        if not title:
            return JsonResponse({'success': False, 'error': '标题不能为空'}, status=400)
        # 简单清洗并限制长度
        title = title.replace('\n', ' ').replace('\r', ' ').strip()[:50]
        session.title = title
        session.save(update_fields=['title', 'updated_at'])
        return JsonResponse({'success': True, 'session': {
            'id': str(session.id),
            'title': session.title,
            'knowledge_base_id': str(session.knowledge_base.id) if session.knowledge_base else None,
            'created_at': session.created_at.isoformat(),
            'updated_at': session.updated_at.isoformat(),
        }})
    except Exception as e:
        logger.error(f"重命名会话失败: {e}")
        return JsonResponse({'success': False, 'error': f'重命名失败: {e}'}, status=500)

# ==================== 多模态问答相关API ====================




@csrf_exempt
@require_http_methods(["POST"]) 
def hybrid_qa(request):
    """
    混合检索融合 + 用户画像 的问答接口
    请求参数:
    - question: 文本问题
    - knowledge_base_id: 单个或多个知识库ID（字符串或字符串数组）
    - session_id: 会话ID（可选）
    - top_k: 返回文档数量（默认5）
    - is_strict: 是否严格仅基于知识库回答（默认False）
    - age, is_employee, frequency: 用户画像
    - history: 对话历史 [{role, content}]（可选）
    """

    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'error': '请先登录'}, status=401)
    try:
        data = json.loads(request.body or '{}')
        question = (data.get('question') or '').strip()
        top_k = int(data.get('top_k', 5))
        is_strict = bool(data.get('is_strict', False))
        debug = bool(data.get('debug', False))
        # age = data.get('age')
        # is_employee = data.get('is_employee', None)
        # frequency = data.get('frequency')
        # history = data.get('history') or []
        session_id = data.get('session_id')
        kb_ids = data.get('knowledge_base_id')
        if not question:
            return JsonResponse({'success': False, 'error': '问题不能为空'}, status=400)

        # API Key
        api_key = getattr(settings, 'DASHSCOPE_API_KEY', None)
        if not api_key:
            return JsonResponse({'success': False, 'error': '未配置 DASHSCOPE_API_KEY'}, status=500)

        # 解析知识库集合
        collection_names = []
        kb_instance = None
        if isinstance(kb_ids, list):
            kb_id_list = kb_ids
        elif isinstance(kb_ids, str) and kb_ids:
            kb_id_list = [kb_ids]
        else:
            kb_id_list = []

        if kb_id_list:
            for kid in kb_id_list:
                try:
                    kb = KnowledgeBase.objects.get(id=kid, user=request.user)
                    collection_names.append(kb.collection_name)
                    if not kb_instance:
                        kb_instance = kb
                except KnowledgeBase.DoesNotExist:
                    return JsonResponse({'success': False, 'error': f'知识库不存在或无权限访问: {kid}'}, status=404)
        else:
            # 默认使用当前用户全部知识库
            user_kbs = KnowledgeBase.objects.filter(user=request.user)
            collection_names = [kb.collection_name for kb in user_kbs]
            if not collection_names:
                return JsonResponse({'success': False, 'error': '您还没有创建任何知识库'}, status=400)

        # 会话
        if session_id:
            try:
                chat_session = ChatSession.objects.get(id=session_id, user=request.user)
            except ChatSession.DoesNotExist:
                return JsonResponse({'success': False, 'error': '会话不存在或无权限访问'}, status=404)
        else:
            title = question[:20] + ('...' if len(question) > 20 else '')
            chat_session = ChatSession.objects.create(user=request.user, title=title, knowledge_base=kb_instance)

        # 保存用户消息
        ChatMessage.objects.create(session=chat_session, role='user', content=question)

        # 记录活跃并获取画像
        from utils.Tools.persona import record_user_activity
        record_user_activity(request.user)

        persona = request.user.persona
        age_group = persona.age_group
        role = persona.role
        frequency = persona.frequency

        # 构造当前 session 的历史对话
        history = get_session_last_n_dialogue_pairs(
            user=request.user,
            session_id=chat_session.id,
            max_pairs=10,
        )

        # 调用 RAGService
        from .rag_service import RAGService
        rag = RAGService(api_key=api_key, model_name="qwen3-omni-flash", chroma_db_path=getattr(settings, 'CHROMA_DB_PATH', './chroma_db'))
        result = rag.smart_answer_hybrid(
            question=question,
            collection_names=collection_names,
            top_k=top_k,
            debug=debug,
            # 用户画像
            history=history,
            age_group=age_group,
            role=role,
            frequency=frequency,
        )

        assistant_answer = result.get('answer', '')
        # 保存助手消息（附带来源）
        sources = [
            {
                'content': d.get('content', ''),
                'file_name': (d.get('metadata') or {}).get('file_name') or (d.get('metadata') or {}).get('source') or (d.get('metadata') or {}).get('source_file') or '未知',
                'score_fused': (d.get('metadata') or {}).get('_s_fused') or (d.get('metadata') or {}).get('_rrf_score'),
                'score_ce': (d.get('metadata') or {}).get('_s_ce_norm'),
            }
            for d in result.get('docs', [])
        ]
        images = result.get('images', [])
        ChatMessage.objects.create(
            session=chat_session,
            role='assistant',
            content=assistant_answer,
            sources=sources or None,
            images=images or None
        )

        # 新建会话则生成标题
        try:
            if not session_id and (chat_session.title == question[:20] + ('...' if len(question) > 20 else '')):
                rag_title = RAGService(api_key=api_key, model_name="qwen3-omni-flash", chroma_db_path=getattr(settings, 'CHROMA_DB_PATH', './chroma_db'))
                new_title = rag_title.generate_title(question, assistant_answer)
                if new_title:
                    chat_session.title = new_title[:50]
                    chat_session.save(update_fields=['title', 'updated_at'])
        except Exception:
            pass

        return JsonResponse({
            'success': True,
            'answer': assistant_answer,
            'sources': sources,
            'images': images,
            'session_id': str(chat_session.id),
            'metadata': {
                'collections': collection_names,
                'used_template': result.get('used_template'),
                'top_k': top_k,
                'strict': is_strict,
                **({'debug': result.get('debug')} if debug else {}),
            }
        })
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': '无效的JSON数据'}, status=400)
    except Exception as e:
        logger.error(f"混合检索问答失败: {e}")
        logger.error(traceback.format_exc())
        logger.error(traceback.format_exc())
        return JsonResponse({'success': False, 'error': f'问答失败: {e}'}, status=500)


