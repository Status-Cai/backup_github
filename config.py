import os

# GitHub配置
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN', 'YOURTOKEN')

# 监控的仓库列表
REPOS = [
    "bepass-org/warp-plus"
]

# 日志配置
LOG_FILE = 'github_monitor.log'
LOG_LEVEL = 'INFO'
LOG_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'

# 下载配置
DOWNLOAD_DIR = 'downloads'
MAX_RETRIES = 3
TIMEOUT = 30
CHUNK_SIZE = 8192  # 下载时的块大小

# HTTP配置
USER_AGENT = 'NAME'
GITHUB_API_VERSION = 'application/vnd.github.v3+json'

# 代理配置
HTTP_PROXY = None  # 'http://127.0.0.1:7890'
HTTPS_PROXY = None  # 'http://127.0.0.1:7890'

# 错误处理配置
MAX_DOWNLOAD_ATTEMPTS = 3  # 下载失败最大重试次数
RETRY_DELAY = 5  # 重试延迟（秒）
BACKOFF_FACTOR = 1  # 重试退避因子
RETRY_STATUS_CODES = [429, 500, 502, 503, 504]  # 需要重试的HTTP状态码
