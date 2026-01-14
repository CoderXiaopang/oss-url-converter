# OSS URL Converter

基于 Flask 的 OSS 文件上传与 URL 转换服务。

## 功能特性

- **文件上传**：支持任意文件上传至 S3 兼容存储（如 Alist），返回预签名下载链接
- **URL 批量转换**：自动识别文本中的所有 URL，下载资源并上传至 OSS，批量替换为新地址
- **实时进度**：异步处理，支持实时查询转换进度
- **登录保护**：密码认证，防止未授权访问

## 快速开始

### Docker 部署（推荐）

1. 复制环境变量模板并配置：

```bash
cp .env.example .env
```

2. 编辑 `.env` 文件，填写你的 OSS 配置：

```env
ALIST_ENDPOINT=https://your-s3-endpoint.com
ALIST_ACCESS_KEY=your-access-key
ALIST_SECRET_KEY=your-secret-key
ALIST_BUCKET=your-bucket-name
URL_EXPIRES=3600

# 设置访问密码
AUTH_PASSWORD=your-secure-password
SECRET_KEY=your-random-secret-key
```

3. 启动服务：

```bash
docker compose up -d
```

4. 访问 http://localhost:4006

### 本地开发

```bash
# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 设置环境变量
export ALIST_ENDPOINT=...
export ALIST_ACCESS_KEY=...
export ALIST_SECRET_KEY=...
export ALIST_BUCKET=...

# 运行
python app.py
```

服务将运行在 http://localhost:5001

## API 接口

### 文件上传

```
POST /upload_file
Content-Type: multipart/form-data

参数: file (文件)

响应:
{
  "code": 200,
  "data": {
    "url": "https://...",
    "filename": "example.jpg",
    "object_key": "uploads/..."
  }
}
```

### URL 转换

```
POST /convert_url
Content-Type: application/json

参数: {"text": "包含 URL 的文本..."}

响应:
{
  "code": 200,
  "data": {
    "task_id": "uuid",
    "total": 5,
    "urls": [...],
    "converted_text": "..."
  }
}
```

### 查询进度

```
GET /progress/<task_id>

响应:
{
  "code": 200,
  "data": {
    "task_id": "uuid",
    "total": 5,
    "completed": 3,
    "converted_text": "...",
    "urls": [...]
  }
}
```

## 技术栈

- Python 3.12+
- Flask 2.3+
- boto3 (S3 兼容存储)
- Docker

## License

MIT
