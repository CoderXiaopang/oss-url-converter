"""
Flask 主应用 - OSS 文件上传与 URL 转换服务
"""
import os
import json
import uuid
import threading
from functools import wraps
from flask import Flask, render_template, request, jsonify, Response, session, redirect, url_for
from werkzeug.utils import secure_filename
from oss_client import oss_client

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 最大 100MB
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'oss-converter-secret-key-change-me')

# 认证密码（从环境变量获取）
AUTH_PASSWORD = os.environ.get('AUTH_PASSWORD', 'admin123')

# 任务存储（内存中）
tasks = {}
tasks_lock = threading.Lock()


def get_task(task_id: str) -> dict:
    """获取任务"""
    with tasks_lock:
        return tasks.get(task_id, {})


def update_task(task_id: str, **kwargs) -> None:
    """更新任务"""
    with tasks_lock:
        if task_id not in tasks:
            tasks[task_id] = {'urls': [], 'total': 0, 'completed': 0, 'converted_text': ''}
        tasks[task_id].update(kwargs)


def create_task_id() -> str:
    """创建新任务 ID"""
    return str(uuid.uuid4())


def login_required(f):
    """登录验证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'code': 401, 'msg': '请先登录'}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


@app.errorhandler(413)
def request_entity_too_large(error):
    """文件太大错误处理"""
    return jsonify({'code': 400, 'msg': '文件太大，最大支持 100MB'}), 413


@app.errorhandler(500)
def internal_error(error):
    """内部错误处理"""
    return jsonify({'code': 500, 'msg': '服务器内部错误'}), 500


@app.route('/login', methods=['GET', 'POST'])
def login():
    """登录页面"""
    if session.get('logged_in'):
        return redirect(url_for('index'))
    
    error = None
    if request.method == 'POST':
        password = request.form.get('password', '')
        if password == AUTH_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            error = '密码错误，请重试'
    
    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    """登出"""
    session.pop('logged_in', None)
    return redirect(url_for('login'))


@app.route('/')
@login_required
def index():
    """首页"""
    return render_template('index.html')


@app.route('/upload_file', methods=['POST'])
@login_required
def upload_file():
    """
    文件上传接口
    接收文件并上传到 OSS，返回访问地址
    """
    if 'file' not in request.files:
        return jsonify({'code': 400, 'msg': '没有选择文件'}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({'code': 400, 'msg': '没有选择文件'}), 400

    # 获取安全的文件名
    filename = secure_filename(file.filename)
    if not filename:
        # 如果文件名被清空（例如中文文件名），使用原始文件名
        filename = file.filename

    # 上传到 OSS
    result = oss_client.upload_from_stream(file.stream, filename)

    if result['success']:
        return jsonify({
            'code': 200,
            'data': {
                'url': result['url'],
                'filename': filename,
                'object_key': result['object_key']
            }
        })
    else:
        return jsonify({'code': 500, 'msg': result.get('error', '上传失败')}), 500


@app.route('/convert_url', methods=['POST'])
@login_required
def convert_url():
    """
    URL 转换启动接口
    接收文本，启动异步转换任务，返回 task_id
    """
    data = request.get_json()

    if not data or 'text' not in data:
        return jsonify({'code': 400, 'msg': '请提供要转换的文本'}), 400

    text = data['text']

    if not text.strip():
        return jsonify({'code': 400, 'msg': '文本不能为空'}), 400

    # 提取 URL
    urls = oss_client.extract_urls(text)
    total = len(urls)

    if total == 0:
        return jsonify({
            'code': 200,
            'data': {
                'task_id': '',
                'total': 0,
                'urls': [],
                'converted_text': text
            }
        })

    # 创建任务
    task_id = create_task_id()
    update_task(task_id, urls=urls, total=total, converted_text=text)

    # 在后台启动转换任务
    def run_conversion():
        converted_text = text
        url_mapping = {}

        for result in oss_client.convert_urls_streaming(text):
            original_url = result['original']
            oss_url = result.get('converted', '')
            status = result['status']
            status_text = {
                'success': '转换成功',
                'failed': '转换失败',
                'skipped': '已是 OSS 地址'
            }.get(status, status)

            # 更新 URL 映射
            if status == 'success':
                url_mapping[original_url] = oss_url
                converted_text = converted_text.replace(original_url, oss_url)

            # 更新任务状态
            with tasks_lock:
                task = tasks.get(task_id, {})
                # 更新或添加该 URL 的状态
                found = False
                for url_info in task.get('urls', []):
                    if url_info.get('original_url') == original_url:
                        url_info['oss_url'] = oss_url
                        url_info['status'] = status
                        url_info['status_text'] = status_text
                        found = True
                        break
                if not found:
                    task['urls'] = task.get('urls', [])
                    task['urls'].append({
                        'original_url': original_url,
                        'oss_url': oss_url,
                        'status': status,
                        'status_text': status_text
                    })
                task['completed'] = sum(1 for u in task.get('urls', []) if u['status'] in ['success', 'failed', 'skipped'])
                task['converted_text'] = converted_text

    thread = threading.Thread(target=run_conversion)
    thread.start()

    return jsonify({
        'code': 200,
        'data': {
            'task_id': task_id,
            'total': total,
            'urls': urls,
            'converted_text': text
        }
    })


@app.route('/progress/<task_id>', methods=['GET'])
@login_required
def get_progress(task_id: str):
    """
    获取转换进度
    """
    task = get_task(task_id)

    if not task:
        return jsonify({'code': 404, 'msg': '任务不存在'}), 404

    return jsonify({
        'code': 200,
        'data': {
            'task_id': task_id,
            'total': task.get('total', 0),
            'completed': task.get('completed', 0),
            'converted_text': task.get('converted_text', ''),
            'urls': task.get('urls', [])
        }
    })


if __name__ == '__main__':
    # 开发模式运行
    app.run(host='0.0.0.0', port=5001, debug=True)
