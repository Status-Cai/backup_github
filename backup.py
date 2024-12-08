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

class SecurityError(GitHubBackupError):
    """安全相关错误"""
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
            # 规范化路径
            dir_path = os.path.abspath(dir_path)
            downloads_path = os.path.abspath(DOWNLOAD_DIR)
            
            # 安全检查：确保要删除的目录在 downloads 目录下
            if not dir_path.startswith(downloads_path):
                raise SecurityError(f"安全限制：不能删除 {DOWNLOAD_DIR} 目录之外的文件")
                
            if not os.path.exists(dir_path):
                logger.warning(f"要删除的目录不存在: {dir_path}")
                return
                
            # 检查目录是否可访问
            try:
                os.listdir(dir_path)
            except PermissionError:
                logger.error(f"没有权限访问目录: {dir_path}")
                return
                
            # 尝试删除
            try:
                shutil.rmtree(dir_path)
                logger.info(f"成功删除目录: {dir_path}")
                return
            except PermissionError:
                # 处理只读文件
                try:
                    shutil.rmtree(dir_path, onerror=self.remove_readonly)
                    logger.info(f"成功删除只读目录: {dir_path}")
                    return
                except Exception as e:
                    logger.error(f"删除只读目录失败: {str(e)}")
                    
            # 如果上述方法都失败，尝试使用系统命令
            try:
                if os.name == 'nt':  # Windows
                    result = subprocess.run(['cmd', '/c', 'rd', '/s', '/q', dir_path], 
                                         capture_output=True, 
                                         text=True, 
                                         check=False)
                    if result.returncode != 0:
                        logger.error(f"系统命令删除失败: {result.stderr}")
                else:  # Linux/Unix
                    result = subprocess.run(['rm', '-rf', dir_path], 
                                         capture_output=True, 
                                         text=True, 
                                         check=False)
                    if result.returncode != 0:
                        logger.error(f"系统命令删除失败: {result.stderr}")
            except Exception as e:
                logger.error(f"系统命令执行失败: {str(e)}")
                raise
                
        except Exception as e:
            logger.error(f"删除目录时发生错误 {dir_path}: {str(e)}")
            raise

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

    def clean_old_versions(self, repo):
        """清理旧版本的文件夹"""
        # 如果配置为不清理旧版本，直接返回
        if not CLEAN_OLD_VERSIONS:
            logger.info(f"CLEAN_OLD_VERSIONS 设置为 False，跳过清理旧版本")
            return

        try:
            repo_name = repo.split('/')[-1]
            repo_dir = os.path.join(DOWNLOAD_DIR, repo_name)
            
            # 如果仓库目录不存在，直接返回
            if not os.path.exists(repo_dir):
                logger.warning(f"仓库目录不存在: {repo_dir}")
                return
            
            # 读取当前版本
            current_version = self.get_local_version(repo)
            if not current_version:
                logger.warning(f"无法获取仓库 {repo} 的当前版本信息")
                return

            logger.info(f"开始检查 {repo} 的旧版本，当前版本: {current_version}")
            logger.info(f"配置保留最近 {KEEP_VERSIONS_COUNT} 个版本")

            # 获取所有版本目录
            version_dirs = []
            for item in os.listdir(repo_dir):
                item_path = os.path.join(repo_dir, item)
                if os.path.isdir(item_path):
                    # 记录目录创建时间和路径
                    try:
                        mtime = os.path.getmtime(item_path)
                        version_dirs.append((mtime, item, item_path))
                        logger.debug(f"找到版本目录: {item}, 修改时间: {datetime.fromtimestamp(mtime)}")
                    except Exception as e:
                        logger.error(f"获取目录信息失败 {item_path}: {str(e)}")

            # 如果目录数量小于等于保留数量，不需要删除
            if len(version_dirs) <= KEEP_VERSIONS_COUNT:
                logger.info(f"当前版本数 ({len(version_dirs)}) 小于等于保留数量 ({KEEP_VERSIONS_COUNT})，无需清理")
                return

            # 按修改时间排序，最新的在前面
            version_dirs.sort(reverse=True)
            logger.info(f"找到 {len(version_dirs)} 个版本目录，将删除最旧的 {len(version_dirs) - KEEP_VERSIONS_COUNT} 个版本")

            # 保留最新的版本
            keep_versions = version_dirs[:KEEP_VERSIONS_COUNT]
            delete_versions = version_dirs[KEEP_VERSIONS_COUNT:]

            # 记录要保留的版本
            for _, name, path in keep_versions:
                logger.info(f"保留版本目录: {name}")

            # 删除旧版本
            for _, name, dir_path in delete_versions:
                logger.info(f"正在删除旧版本目录: {name}")
                try:
                    self.safe_remove_dir(dir_path)
                    logger.info(f"成功删除旧版本目录: {name}")
                except Exception as e:
                    logger.error(f"删除旧版本目录失败 {dir_path}: {str(e)}")

            logger.info(f"完成 {repo} 的旧版本清理")

        except Exception as e:
            logger.error(f"清理旧版本时发生错误 {repo}: {str(e)}")

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
                # 即使是最新版本，也执行一次清理检查
                self.clean_old_versions(repo)
                return True
                
            version_folder = os.path.join(folder, repo_name, safe_tag_name)
            
            # 如果版本文件夹已存在，删除它
            if os.path.exists(version_folder):
                logger.info(f"发现已存在的版本文件夹: {version_folder}")
                try:
                    self.safe_remove_dir(version_folder)
                except Exception as e:
                    logger.error(f"删除旧版本失败，跳过下载: {str(e)}")
                    return False
            
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
                    
                    # 清理旧版本
                    self.clean_old_versions(repo)
                    
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
