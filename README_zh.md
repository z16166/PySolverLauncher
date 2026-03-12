# PySolverLauncher

一个用于管理和自动更新 Windows 命令行求解器（如 `solver_fast.exe`）的 Python 脚本。

## 功能特性

- **动态可执行文件解析**：从 `cmd.txt` 自动读取并解析执行命令。
- **自动补全后缀**：自动为可执行文件名补全 `.exe` 后缀。
- **独立控制台窗口**：求解器在独立的控制台窗口中运行，日志清晰互不干扰。
- **自动检测更新**：后台定时（1-3 分钟随机）请求 API 检测新版本。
- **高效 SHA1 缓存**：通过文件时间戳和大小判断是否需要重新计算 SHA1，减少磁盘 IO。
- **安全停止逻辑**：更新时先发送控制事件请求安全退出，15 秒超时后才强制终止。
- **历史版本备份**：下载新版时若同名压缩包已存在，自动重命名备份旧版本。

## 快速开始

### 1. 配置环境
确保已安装 Python 3.x 以及 `requests` 库：
```bash
pip install -r requirements.txt
```

### 2. 配置启动指令 `cmd.txt`
在脚本同级目录下创建 `cmd.txt`，写入完整的求解器运行指令。
例如：
```text
solver_fast.exe --server ecdlp.protect.cx --worker-name "WhoCares" --gpu-limit 100 --resume
```
*注：即使只写 `solver_fast`，脚本也会自动识别为 `solver_fast.exe`。*

### 3. 运行程序
```bash
python launcher.py
```

## 更新机制

脚本会定期访问以下接口：
`https://HOST/api/download-info` （HOST 从 `cmd.txt` 的 `--server` 参数提取）

如果接口返回的 `sha1` 与本地文件不符，脚本将：
1. 下载新的压缩包。
2. 请求旧版求解器安全退出。
3. 解压并覆盖当前目录文件。
4. 重新启动求解器。

## 注意事项
- 脚本依赖 `cmd.txt` 进行初始化，请确保该文件存在且配置正确。
- 请勿将 `cmd.txt` 提交至公共仓库以防配置冲突或泄露。
