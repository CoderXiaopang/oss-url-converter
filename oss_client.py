"""
OSS 客户端模块 - 封装文件上传和 URL 下载转换功能
"""
import os
import re
import uuid
import tempfile
import requests
import boto3
from concurrent.futures import ThreadPoolExecutor, as_completed
from botocore.client import Config
from botocore.exceptions import NoCredentialsError
from urllib.parse import urlparse, unquote


class OSSClient:
    """OSS 客户端，支持文件上传和 URL 转换"""

    def __init__(self):
        # ---------------- 配置区域 ----------------
        self.endpoint = os.environ.get('ALIST_ENDPOINT', 'http://nas2net.cn:4003')
        self.access_key = os.environ.get('ALIST_ACCESS_KEY', 'dlrNMURxGSkqg7ORBpuI')
        self.secret_key = os.environ.get('ALIST_SECRET_KEY', '2BHjYeGAr28VCv8aHtDb0dl9ANVKICnNKSM9KGDr')
        self.bucket_name = os.environ.get('ALIST_BUCKET', 'OSS_Buckets')
        self.url_expires = int(os.environ.get('URL_EXPIRES', 3600))  # URL 有效期（秒）
        # -----------------------------------------

        # 初始化 S3 客户端
        self.s3_client = boto3.client(
            's3',
            endpoint_url=self.endpoint,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            config=Config(s3={'addressing_style': 'path'}, signature_version='s3v4')
        )

    def upload_file(self, file_path: str, object_key: str = None) -> dict:
        """
        上传本地文件到 OSS
        
        :param file_path: 本地文件路径
        :param object_key: OSS 中的对象键，默认使用文件名
        :return: 包含 url 和 status 的字典
        """
        if not os.path.exists(file_path):
            return {'success': False, 'error': '文件不存在'}

        if object_key is None:
            # 生成唯一文件名避免冲突
            original_name = os.path.basename(file_path)
            name, ext = os.path.splitext(original_name)
            object_key = f"{name}_{uuid.uuid4().hex[:8]}{ext}"

        try:
            self.s3_client.upload_file(file_path, self.bucket_name, object_key)

            # 生成预签名 URL
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': object_key},
                ExpiresIn=self.url_expires
            )

            return {
                'success': True,
                'url': url,
                'object_key': object_key
            }

        except NoCredentialsError:
            return {'success': False, 'error': '密钥认证失败'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def upload_from_stream(self, file_stream, filename: str) -> dict:
        """
        从文件流上传到 OSS（用于 Flask 文件上传）
        
        :param file_stream: 文件流对象
        :param filename: 原始文件名
        :return: 包含 url 和 status 的字典
        """
        # 生成唯一文件名
        name, ext = os.path.splitext(filename)
        object_key = f"{name}_{uuid.uuid4().hex[:8]}{ext}"

        try:
            self.s3_client.upload_fileobj(file_stream, self.bucket_name, object_key)

            # 生成预签名 URL
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': object_key},
                ExpiresIn=self.url_expires
            )

            return {
                'success': True,
                'url': url,
                'object_key': object_key
            }

        except NoCredentialsError:
            return {'success': False, 'error': '密钥认证失败'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def download_and_upload(self, url: str) -> dict:
        """
        下载 URL 指向的文件并上传到 OSS
        
        :param url: 要下载的文件 URL
        :return: 包含新 OSS URL 的字典
        """
        try:
            # 下载文件
            response = requests.get(url, stream=True, timeout=30)
            response.raise_for_status()

            # 从 URL 或 Content-Disposition 中提取文件名
            filename = self._extract_filename(url, response.headers)

            # 创建临时文件
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as tmp_file:
                for chunk in response.iter_content(chunk_size=8192):
                    tmp_file.write(chunk)
                tmp_path = tmp_file.name

            try:
                # 上传到 OSS
                result = self.upload_file(tmp_path, None)
                return result
            finally:
                # 清理临时文件
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

        except requests.exceptions.RequestException as e:
            return {'success': False, 'error': f'下载失败: {str(e)}', 'original_url': url}
        except Exception as e:
            return {'success': False, 'error': str(e), 'original_url': url}

    def _extract_filename(self, url: str, headers: dict) -> str:
        """从 URL 或响应头中提取文件名"""
        # 尝试从 Content-Disposition 提取
        content_disposition = headers.get('Content-Disposition', '')
        if 'filename=' in content_disposition:
            filename = content_disposition.split('filename=')[-1].strip('"\'')
            if filename:
                return filename

        # 从 URL 路径提取
        parsed = urlparse(url)
        path = unquote(parsed.path)
        filename = os.path.basename(path)

        if filename and '.' in filename:
            return filename

        # 根据 Content-Type 猜测扩展名
        content_type = headers.get('Content-Type', '')
        ext_map = {
            'image/jpeg': '.jpg',
            'image/png': '.png',
            'image/gif': '.gif',
            'image/webp': '.webp',
            'application/pdf': '.pdf',
            'text/plain': '.txt',
            'text/html': '.html',
            'application/json': '.json',
        }
        ext = ext_map.get(content_type.split(';')[0], '.bin')
        return f"file_{uuid.uuid4().hex[:8]}{ext}"

    def extract_urls(self, text: str) -> list:
        """
        从文本中提取所有 URL
        
        :param text: 包含 URL 的文本
        :return: 去重后的 URL 列表
        """
        url_pattern = r'https?://[^\s<>"\')\]]+(?:\.[^\s<>"\')\]]+)*'
        urls = re.findall(url_pattern, text)
        # 去重并保持顺序
        seen = set()
        unique_urls = []
        for url in urls:
            if url not in seen:
                seen.add(url)
                unique_urls.append(url)
        return unique_urls

    def process_single_url(self, url: str) -> dict:
        """
        处理单个 URL：检查是否跳过，或下载并上传
        
        :param url: 要处理的 URL
        :return: 处理结果字典
        """
        # 跳过已经是 OSS 地址的 URL
        if self.endpoint in url:
            return {
                'original': url,
                'converted': url,
                'status': 'skipped',
                'message': '已是 OSS 地址'
            }

        result = self.download_and_upload(url)

        if result['success']:
            return {
                'original': url,
                'converted': result['url'],
                'status': 'success'
            }
        else:
            return {
                'original': url,
                'converted': url,
                'status': 'failed',
                'error': result.get('error', '未知错误')
            }

    def convert_urls_streaming(self, text: str, max_workers: int = 5):
        """
        并发转换文本中的所有 URL，使用生成器逐个返回结果
        
        :param text: 包含 URL 的文本
        :param max_workers: 最大并发数
        :yield: 每个 URL 的转换结果
        """
        unique_urls = self.extract_urls(text)
        total = len(unique_urls)

        if total == 0:
            return

        # 使用线程池并发处理
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            future_to_url = {
                executor.submit(self.process_single_url, url): url 
                for url in unique_urls
            }

            # 按完成顺序返回结果
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    result = future.result()
                    yield result
                except Exception as e:
                    yield {
                        'original': url,
                        'converted': url,
                        'status': 'failed',
                        'error': str(e)
                    }

    def convert_urls_in_text(self, text: str) -> dict:
        """
        将文本中的所有 URL 转换为 OSS 地址（同步版本，用于兼容）
        
        :param text: 包含 URL 的文本
        :return: 包含转换后文本和转换详情的字典
        """
        unique_urls = self.extract_urls(text)
        conversion_results = []
        converted_text = text

        for result in self.convert_urls_streaming(text):
            conversion_results.append(result)
            if result['status'] == 'success':
                converted_text = converted_text.replace(result['original'], result['converted'])

        return {
            'success': True,
            'original_text': text,
            'converted_text': converted_text,
            'conversions': conversion_results,
            'total_urls': len(unique_urls),
            'successful': sum(1 for r in conversion_results if r['status'] == 'success'),
            'failed': sum(1 for r in conversion_results if r['status'] == 'failed'),
            'skipped': sum(1 for r in conversion_results if r['status'] == 'skipped')
        }


# 创建全局客户端实例
oss_client = OSSClient()
