import requests
import os
import shutil
import logging
import time
import zipfile
import io
import stat
import subprocess
from datetime import datetime
from tqdm import tqdm
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from typing import Optional, Dict, Any
from config import *

class GitHubBackupError(Exception):
    """自定义异常基类"""
    pass

class NetworkError(GitHubBackupError):
    """网络相关错误"""
    pass

class DownloadError(GitHubBackupError):
    """下载相关错误"""
    pass

class FileSystemError(GitHubBackupError):
    """文件系统相关错误"""
    pass

# 配置日志
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=LOG_FORMAT,
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class GitHubBackup:
    def __init__(self):
        self.session = self._create_session()
        self._ensure_download_dir()

    def _create_session(self) -> requests.Session:
        """创建并配置请求会话"""
        session = requests.Session()
        retry_strategy = Retry(
            total=MAX_RETRIES,
            backoff_factor=BACKOFF_FACTOR,
            status_forcelist=RETRY_STATUS_CODES
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        
        # 配置代理
        if HTTP_PROXY or HTTPS_PROXY:
            session.proxies = {
                'http': HTTP_PROXY,
                'https': HTTPS_PROXY
            }
        return session

    def _ensure_download_dir(self) -> None:
        """确保下载目录存在"""
        try:
            os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        except Exception as e:
            raise FileSystemError(f"创建下载目录失败: {str(e)}")

    def _get_headers(self) -> Dict[str, str]:
        """获取HTTP请求头"""
        return {
            'Authorization': f'token {GITHUB_TOKEN}',
            'User-Agent': USER_AGENT,
            'Accept': GITHUB_API_VERSION
        }

    def get_latest_release(self, repo: str) -> Optional[Dict[str, Any]]:
        """获取仓库最新的release版本和资源文件信息"""
        url = f"https://api.github.com/repos/{repo}/releases/latest"
        
        for attempt in range(MAX_DOWNLOAD_ATTEMPTS):
            try:
                response = self.session.get(url, headers=self._get_headers(), timeout=TIMEOUT)
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
            except requests.exceptions.RequestException as e:
                if attempt < MAX_DOWNLOAD_ATTEMPTS - 1:
                    wait_time = RETRY_DELAY * (attempt + 1)
                    logger.warning(f"获取release信息失败，{wait_time}秒后重试: {str(e)}")
                    time.sleep(wait_time)
                else:
                    raise NetworkError(f"获取仓库最新release版本失败 {repo}: {str(e)}")

    def remove_readonly(self, func, path, _):
        """清除文件的只读属性并重试删除"""
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except Exception as e:
            logger.error(f"删除文件失败 {path}: {str(e)}")

    def safe_remove_dir(self, dir_path):
        """安全地删除目录及其内容"""
        try:
            if os.path.exists(dir_path):
                # 首先尝试直接删除
                try:
                    shutil.rmtree(dir_path)
                except PermissionError:
                    # 如果失败，使用onerror处理器重试
                    shutil.rmtree(dir_path, onerror=self.remove_readonly)
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

    def download_file_with_progress(self, url, local_filename, headers):
        """带进度条的文件下载"""
        try:
            response = self.session.get(url, headers=headers, stream=True, timeout=TIMEOUT)
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

    def get_local_version(self, repo):
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

    def save_local_version(self, repo, version):
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

    def download_source_code(self, repo, folder):
        """直接下载仓库源代码ZIP文件"""
        # 获取最新release版本
        latest_tag = self.get_latest_release(repo)
        if latest_tag:
            tag_name = latest_tag['tag_name']
            # 将版本号中的斜杠替换为下划线，避免Windows路径问题
            safe_tag_name = tag_name.replace('/', '_')
            repo_name = repo.split('/')[-1]
            
            # 检查本地版本
            local_version = self.get_local_version(repo)
            if local_version == tag_name:
                logger.info(f"仓库 {repo} 已是最新版本 {tag_name}，无需下载")
                return True
                
            version_folder = os.path.join(folder, repo_name, safe_tag_name)
            
            # 如果版本文件夹已存在，删除它
            if os.path.exists(version_folder):
                logger.info(f"删除旧版本文件夹: {version_folder}")
                self.safe_remove_dir(version_folder)
            
            # 创建新的版本文件夹
            os.makedirs(version_folder, exist_ok=True)
            
            # 下载源代码
            download_url = f"https://codeload.github.com/{repo}/zip/refs/tags/{tag_name}"
            zip_path = os.path.join(version_folder, f"{repo_name}_{safe_tag_name}_source.zip")
            
            try:
                logger.info(f"开始下载 {repo} 的release版本 {tag_name}")
                headers = self._get_headers()
                if self.download_file_with_progress(download_url, zip_path, headers):
                    logger.info(f"成功下载源代码: {zip_path}")
                    
                    # 下载release资源文件
                    for asset in latest_tag['assets']:
                        asset_name = asset['name']
                        asset_url = asset['browser_download_url']
                        asset_path = os.path.join(version_folder, asset_name)
                        
                        if self.download_file_with_progress(asset_url, asset_path, headers):
                            logger.info(f"成功下载资源文件: {asset_name}")
                        else:
                            logger.error(f"下载资源文件失败: {asset_name}")
                    
                    # 保存新版本信息
                    self.save_local_version(repo, tag_name)
                    return True
                
            except Exception as e:
                logger.error(f"下载源代码失败 {repo}: {str(e)}")
                # 如果下载失败，清理版本文件夹
                self.safe_remove_dir(version_folder)
                return False
        else:
            logger.warning(f"未找到仓库的release版本: {repo}")
            return False

def monitor_repos():
    """监控仓库更新的主函数"""
    backup = GitHubBackup()
    
    for repo in REPOS:
        try:
            logger.info(f"开始处理仓库: {repo}")
            backup.download_source_code(repo, DOWNLOAD_DIR)
        except GitHubBackupError as e:
            logger.error(f"处理仓库 {repo} 时发生错误: {str(e)}")
            continue
        except Exception as e:
            logger.error(f"处理仓库 {repo} 时发生未知错误: {str(e)}")
            continue
        time.sleep(RETRY_DELAY)  # 避免请求过于频繁

if __name__ == "__main__":
    try:
        monitor_repos()
    except KeyboardInterrupt:
        logger.info("程序被用户中断")
    except Exception as e:
        logger.error(f"程序执行过程中发生未知错误: {str(e)}")
    finally:
        logger.info("程序结束运行")
