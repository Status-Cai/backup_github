# GitHub Repository Backup Tool / GitHub 仓库备份工具

## English Description

A Python-based tool for automatically monitoring and backing up GitHub repository releases.

### Features

- Monitor specified GitHub repositories for new releases
- Automatically download source code of new versions
- Support download progress bar and retry mechanism
- Proxy support for network access
- Detailed logging system
- Error handling and automatic retries

### Requirements

- Python 3.7+
- Required packages listed in `requirements.txt`

### Installation

1. Clone this repository
2. Install dependencies:
```bash
pip install -r requirements.txt
```
3. Configure your GitHub token in `config.py` or set it as an environment variable
4. Add your target repositories to `config.py`

### Usage

Simply run:
```bash
python backup.py
```

The script will:
1. Check for new releases of specified repositories
2. Download new versions if available
3. Save all files to the `downloads` directory

### Configuration

Edit `config.py` to customize:
- GitHub token
- Repository list
- Proxy settings
- Logging preferences
- Retry parameters

## 中文说明

这是一个基于 Python 的 GitHub 仓库发布版本自动监控和备份工具。

### 功能特点

- 监控指定的 GitHub 仓库的最新发布版本
- 自动下载新版本的源代码
- 支持下载进度条和重试机制
- 支持网络代理配置
- 详细的日志记录系统
- 错误处理和自动重试

### 环境要求

- Python 3.7+
- 所需包已列在 `requirements.txt` 中

### 安装方法

1. 克隆此仓库
2. 安装依赖：
```bash
pip install -r requirements.txt
```
3. 在 `config.py` 中配置你的 GitHub token 或设置为环境变量
4. 在 `config.py` 中添加目标仓库

### 使用方法

直接运行：
```bash
python backup.py
```

脚本将会：
1. 检查指定仓库的新版本
2. 如有新版本则自动下载
3. 所有文件保存在 `downloads` 目录下

### 配置说明

编辑 `config.py` 可以自定义：
- GitHub 访问令牌
- 仓库列表
- 代理设置
- 日志配置
- 重试参数
