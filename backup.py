import requests
import os
import shutil
import logging
import time
import zipfile
import io
from datetime import datetime
from tqdm import tqdm
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from config import GITHUB_TOKEN, REPOS, DOWNLOAD_DIR, MAX_RETRIES, TIMEOUT, HTTP_PROXY, HTTPS_PROXY

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('github_monitor.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 配置请求会话
session = requests.Session()
retry_strategy = Retry(
    total=MAX_RETRIES,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504]
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("https://", adapter)
session.mount("http://", adapter)

def remove_readonly(func, path, _):
    """清除文件的只读属性并重试删除"""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception as e:
        logger.error(f"删除文件失败 {path}: {str(e)}")

def safe_remove_dir(dir_path):
    """安全地删除目录及其内容"""
    try:
        if os.path.exists(dir_path):
            # 首先尝试直接删除
            try:
                shutil.rmtree(dir_path)
            except PermissionError:
                # 如果失败，使用onerror处理器重试
                shutil.rmtree(dir_path, onerror=remove_readonly)
            except Exception as e:
                logger.error(f"删除目录失败 {dir_path}: {str(e)}")
                # 如果还是失败，尝试使用系统命令强制删除
                try:
                    if os.name == 'nt':  # Windows
                        subprocess.run(['cmd', '/c', 'rd', '/s', '/q', dir_path], check=False)
                    else:  # Linux/Unix
                        subprocess.run(['rm', '-rf', dir_path], check=False)
                except Exception as e:
                    logger.error(f"强制删除目录失败 {dir_path}: {str(e)}")
    except Exception as e:
        logger.error(f"处理目录删除时发生错误 {dir_path}: {str(e)}")

def get_latest_release(repo):
    """获取仓库最新的release版本和资源文件信息"""
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'User-Agent': 'Status_Cai',
        'Accept': 'application/vnd.github.v3+json'
    }
    try:
        response = session.get(url, headers=headers, timeout=TIMEOUT)
        response.raise_for_status()
        data = response.json()
        tag_name = data.get('tag_name')
        if tag_name:
            logger.info(f"仓库 {repo} 的最新release版本是 {tag_name}")
            return {
                'tag_name': tag_name,
                'assets': data.get('assets', [])
            }
        return None
    except Exception as e:
        logger.warning(f"获取仓库最新release版本失败 {repo}: {str(e)}")
        return None

def download_file_with_progress(url, local_filename, headers):
    """带进度条的文件下载"""
    try:
        response = session.get(url, headers=headers, stream=True, timeout=TIMEOUT)
        response.raise_for_status()
        total_size = int(response.headers.get('content-length', 0))

        with open(local_filename, 'wb') as f:
            with tqdm(total=total_size, unit='iB', unit_scale=True, desc=os.path.basename(local_filename)) as pbar:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        size = f.write(chunk)
                        pbar.update(size)
        return True
    except Exception as e:
        logger.error(f"下载文件失败 {url}: {str(e)}")
        if os.path.exists(local_filename):
            os.remove(local_filename)
        return False

def download_release(asset_url, folder, filename):
    """下载发布文件"""
    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'User-Agent': 'Status_Cai',
        'Accept': 'application/octet-stream'
    }
    
    os.makedirs(folder, exist_ok=True)
    local_path = os.path.join(folder, filename)
    
    logger.info(f"开始下载 {filename}")
    if download_file_with_progress(asset_url, local_path, headers):
        logger.info(f"成功下载 {filename}")
        return True
    return False

def get_local_version(repo):
    """获取本地保存的版本号"""
    repo_name = repo.split('/')[-1]
    version_file = os.path.join(DOWNLOAD_DIR, repo_name, 'version.txt')
    try:
        if os.path.exists(version_file):
            with open(version_file, 'r') as f:
                return f.read().strip()
    except Exception as e:
        logger.error(f"读取本地版本信息失败 {repo}: {str(e)}")
    return None

def save_local_version(repo, version):
    """保存版本号到本地"""
    repo_name = repo.split('/')[-1]
    version_file = os.path.join(DOWNLOAD_DIR, repo_name, 'version.txt')
    try:
        os.makedirs(os.path.dirname(version_file), exist_ok=True)
        with open(version_file, 'w') as f:
            f.write(version)
        logger.info(f"保存版本信息 {repo}: {version}")
    except Exception as e:
        logger.error(f"保存版本信息失败 {repo}: {str(e)}")

def get_default_branch(repo):
    """获取仓库的默认分支名称"""
    url = f"https://api.github.com/repos/{repo}"
    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'User-Agent': 'Status_Cai',
        'Accept': 'application/vnd.github.v3+json'
    }
    try:
        response = session.get(url, headers=headers, timeout=TIMEOUT)
        response.raise_for_status()
        data = response.json()
        default_branch = data.get('default_branch', 'main')
        logger.info(f"仓库 {repo} 的默认分支是 {default_branch}")
        return default_branch
    except Exception as e:
        logger.error(f"获取仓库默认分支失败 {repo}: {str(e)}")
        # 如果获取失败，依次尝试main和master
        return None

def download_source_code(repo, folder):
    """直接下载仓库源代码ZIP文件"""
    # 设置请求头
    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'User-Agent': 'Status_Cai',
        'Accept': 'application/vnd.github.v3+json'
    }
    
    # 设置代理
    proxies = {}
    if HTTP_PROXY:
        proxies['http'] = HTTP_PROXY
    if HTTPS_PROXY:
        proxies['https'] = HTTPS_PROXY
    
    # 生成带时间戳的zip文件名
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    repo_name = repo.split('/')[-1]
    zip_path = os.path.join(folder, f"{repo_name}_{timestamp}_source.zip")
    
    # 首先尝试下载最新release版本
    latest_tag = get_latest_release(repo)
    if latest_tag:
        download_url = f"https://github.com/{repo}/archive/refs/tags/{latest_tag['tag_name']}.zip"
        try:
            # 下载源代码
            logger.info(f"开始下载 {repo} 的release版本 {latest_tag['tag_name']}")
            response = session.get(
                download_url,
                headers=headers,
                proxies=proxies,
                stream=True,
                timeout=TIMEOUT
            )
            response.raise_for_status()
            
            # 获取文件大小
            total_size = int(response.headers.get('content-length', 0))
            
            # 确保目标目录存在
            os.makedirs(folder, exist_ok=True)
            
            # 下载并保存文件
            with open(zip_path, 'wb') as f:
                with tqdm(total=total_size, unit='iB', unit_scale=True, desc=f"下载 {repo} (release {latest_tag['tag_name']})") as pbar:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            size = f.write(chunk)
                            pbar.update(size)
            
            logger.info(f"成功下载release版本 {latest_tag['tag_name']} 到 {zip_path}")
            return True
        except Exception as e:
            logger.warning(f"下载release版本失败 {repo}: {str(e)}")
            if os.path.exists(zip_path):
                os.remove(zip_path)
    
    # 如果没有release版本或下载失败，尝试从默认分支下载
    default_branch = get_default_branch(repo)
    branches_to_try = [default_branch] if default_branch else ['main', 'master']
    
    for branch in branches_to_try:
        download_url = f"https://github.com/{repo}/archive/refs/heads/{branch}.zip"
        
        try:
            # 先检查URL是否可访问
            head_response = session.head(
                download_url,
                headers=headers,
                proxies=proxies,
                timeout=TIMEOUT
            )
            if head_response.status_code != 200:
                logger.warning(f"分支 {branch} 不可用，尝试下一个分支")
                continue
            
            # 下载源代码
            logger.info(f"开始从分支 {branch} 下载 {repo} 的源代码")
            response = session.get(
                download_url,
                headers=headers,
                proxies=proxies,
                stream=True,
                timeout=TIMEOUT
            )
            response.raise_for_status()
            
            # 获取文件大小
            total_size = int(response.headers.get('content-length', 0))
            
            # 确保目标目录存在
            os.makedirs(folder, exist_ok=True)
            
            # 下载并保存文件
            with open(zip_path, 'wb') as f:
                with tqdm(total=total_size, unit='iB', unit_scale=True, desc=f"下载 {repo} ({branch}分支)") as pbar:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            size = f.write(chunk)
                            pbar.update(size)
            
            logger.info(f"成功从分支 {branch} 下载源代码到 {zip_path}")
            return True
            
        except requests.exceptions.RequestException as e:
            logger.warning(f"从分支 {branch} 下载失败 {repo}: {str(e)}")
            if os.path.exists(zip_path):
                os.remove(zip_path)
            continue
        except Exception as e:
            logger.error(f"处理分支 {branch} 时发生未知错误 {repo}: {str(e)}")
            if os.path.exists(zip_path):
                os.remove(zip_path)
            continue
    
    # 如果所有尝试都失败
    logger.error(f"所有下载尝试都失败 {repo}")
    return False

def monitor_repos():
    """监控仓库更新"""
    logger.info("开始监控仓库更新")
    for repo in REPOS:
        try:
            release = get_latest_release(repo)
            
            if not release:
                continue
            
            latest_version = release['tag_name']
            local_version = get_local_version(repo)
            
            # 检查是否需要更新
            if latest_version == local_version:
                logger.info(f"仓库 {repo} 已是最新版本 {latest_version}")
                continue
                
            logger.info(f"发现新版本 {repo}: {latest_version}")
            
            # 创建下载目录
            repo_folder = os.path.join(DOWNLOAD_DIR, repo.split('/')[-1])
            os.makedirs(repo_folder, exist_ok=True)
            
            # 下载源代码
            download_source_code(repo, repo_folder)
            
            # 下载发布的资源文件
            download_success = True
            for asset in release.get('assets', []):
                asset_name = asset['name']
                download_url = asset['browser_download_url']
                
                if download_release(download_url, repo_folder, asset_name):
                    logger.info(f"成功下载 {asset_name}")
                else:
                    logger.warning(f"下载 {asset_name} 失败")
                    download_success = False
            
            # 只有全部文件下载成功才更新版本号
            if download_success:
                save_local_version(repo, latest_version)
                
        except Exception as e:
            logger.error(f"处理仓库更新时发生错误 {repo}: {str(e)}")
            continue
            
    logger.info("仓库更新检查完成")

if __name__ == "__main__":
    try:
        monitor_repos()
    except KeyboardInterrupt:
        logger.info("程序被用户中断")
    except Exception as e:
        logger.error(f"程序执行出错: {str(e)}")
