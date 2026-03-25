"""
Django settings for backend project.
"""

from pathlib import Path
import os
from dotenv import load_dotenv

# ----------------------------------------------------------------
# 1. 路径与环境变量配置
# ----------------------------------------------------------------
# BASE_DIR 指向 /backend 文件夹
BASE_DIR = Path(__file__).resolve().parent.parent

# ROOT_DIR 指向项目根目录 (G:\05_Project\cgrag_api)
ROOT_DIR = BASE_DIR.parent

# 加载根目录下的 .env 文件
env_path = ROOT_DIR / '.env'
load_dotenv(env_path)

# 从 .env 获取 IP 地址，默认为本地
SERVER_IP = os.getenv('SERVER_IP', '127.0.0.1')
DASHSCOPE_API_KEY = os.getenv('DASHSCOPE_API_KEY', '')

RAG_RERANKER_MODEL_NAME = os.getenv('RAG_RERANKER_MODEL_NAME', '')
os.environ['ANONYMIZED_TELEMETRY'] = 'False'
# ----------------------------------------------------------------
# 2. 基础安全设置
# ----------------------------------------------------------------
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'django-insecure--38wpx8ad4e)ninj^309@i-o5ic8wm@v313(1(*v1i#30mseir')

DEBUG = True  # 生产环境请改为 False

# 允许访问的主机列表：包含定义的 IP、localhost 和通配符
ALLOWED_HOSTS = [SERVER_IP, '127.0.0.1', 'localhost']

# ----------------------------------------------------------------
# 3. APP 与 中间件
# ----------------------------------------------------------------
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',  # 跨域支持
    'chunker_api',  # 您的业务 APP
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",       # 必须在最顶部
    "django.middleware.common.CommonMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = 'backend.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'backend.wsgi.application'

# ----------------------------------------------------------------
# 4. 数据库配置
# ----------------------------------------------------------------
# 默认使用 SQLite，如果需要切换 MySQL，请取消下面注释并配置 .env
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# ----------------------------------------------------------------
# 5. 跨域 (CORS) 与 CSRF 动态配置
# ----------------------------------------------------------------
CORS_ALLOW_CREDENTIALS = True

# 自动允许来自当前 IP 和前端端口的请求
CORS_ALLOWED_ORIGINS = [
    f"http://{SERVER_IP}",
    f"http://{SERVER_IP}:3000",   # Vite 开发服务器端口
    f"http://{SERVER_IP}:5173",   # Vite 默认端口
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://localhost:5173",
]

CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS

CORS_ALLOW_METHODS = ['DELETE', 'GET', 'OPTIONS', 'PATCH', 'POST', 'PUT']
CORS_ALLOW_HEADERS = [
    'accept', 'accept-encoding', 'authorization', 'content-type',
    'dnt', 'origin', 'user-agent', 'x-csrftoken', 'x-requested-with',
]

# ----------------------------------------------------------------
# 6. Session 与 Cookie 配置
# ----------------------------------------------------------------
SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_COOKIE_NAME = "sessionid"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14

# 开发环境下通常设为 Lax，若生产环境全站 HTTPS 可改为 None 并设置 SECURE=True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = False

# ----------------------------------------------------------------
# 7. 静态文件与媒体文件
# ----------------------------------------------------------------
STATIC_URL = 'static/'

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# 提取图片保存目录
EXTRACTED_IMAGES_DIR = os.path.join(MEDIA_ROOT, 'extracted_images')
os.makedirs(EXTRACTED_IMAGES_DIR, exist_ok=True)

# ----------------------------------------------------------------
# 8. 业务模型相关配置
# ----------------------------------------------------------------
AUTH_USER_MODEL = 'chunker_api.User'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# 文件上传限制
FILE_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024  # 50MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024  # 50MB

# 模型路径建议也放入 .env 或使用相对路径增加移植性
# RERANKER_MODEL_NAME = r'G:\05_Project\bge-reranker-large'
RERANKER_MODEL_NAME = os.getenv('RERANKER_MODEL_PATH', str(ROOT_DIR / 'models' / 'bge-reranker-large'))

CHROMA_DB_PATH = os.path.join(BASE_DIR, 'chroma_db')
MULTIMODAL_COLLECTION_NAME = 'multimodal_documents'
ENABLE_MULTIMODAL_ENCODING = os.getenv('ENABLE_MULTIMODAL_ENCODING', 'False').lower() == 'true'

# ----------------------------------------------------------------
# 9. 国际化
# ----------------------------------------------------------------
LANGUAGE_CODE = 'zh-hans' # 改为中文
TIME_ZONE = 'Asia/Shanghai' # 改为中国时区
USE_I18N = True
USE_TZ = True