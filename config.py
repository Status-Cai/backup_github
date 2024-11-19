import os

# GitHub配置,yourtoken填写GitHubtoken
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN', 'yourtoken')

# 监控的仓库列表
REPOS = [
    "chen08209/FlClash",
    "libnyanpasu/clash-nyanpasu",
    "MetaCubeX/mihomo"
]

# 下载配置
DOWNLOAD_DIR = 'downloads'
MAX_RETRIES = 3
TIMEOUT = 30

# 代理配置
HTTP_PROXY = 'http://127.0.0.1:7890'  # 根据你的代理设置修改
HTTPS_PROXY = 'http://127.0.0.1:7890'  # 根据你的代理设置修改
