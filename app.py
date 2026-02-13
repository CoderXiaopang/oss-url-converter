"""
Flask 主应用 - OSS 文件上传与 URL 转换服务
"""
import os
import uuid
import threading
from functools import wraps
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, current_app
from werkzeug.utils import secure_filename
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from oss_client import oss_client
from models import db, User, UploadHistory

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 最大 100MB
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'oss-converter-secret-key')

# 数据库配置
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
os.makedirs(DATA_DIR, exist_ok=True)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(DATA_DIR, 'oss_converter.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 初始化数据库
db.init_app(app)

# 初始化 Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = '请先登录'


@login_manager.user_loader
def load_user(user_id):
    """加载用户"""
    return User.query.get(int(user_id))


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


def admin_required(f):
    """管理员权限验证装饰器"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            if request.is_json:
                return jsonify({'code': 401, 'msg': '请先登录'}), 401
            return redirect(url_for('login'))
        if not current_user.is_admin():
            if request.is_json:
                return jsonify({'code': 403, 'msg': '需要管理员权限'}), 403
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated


def init_db():
    """初始化数据库"""
    with app.app_context():
        db.create_all()
        # 创建默认管理员账号（如果不存在）
        create_default_admin()


def create_default_admin():
    """创建默认管理员账号"""
    if User.query.count() == 0:
        admin = User(
            username='admin',
            email=None,
            role='admin',
            status='active',
            created_at=datetime.utcnow()
        )
        admin.set_password('admin')
        db.session.add(admin)
        db.session.commit()
        print('已创建默认管理员账号: admin / admin')


@app.route('/register', methods=['GET'])
def register_page():
    """注册页面"""
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    return render_template('register.html')


@app.route('/api/register', methods=['POST'])
def api_register():
    """注册 API"""
    data = request.get_json()

    if not data:
        return jsonify({'code': 400, 'msg': '请求数据无效'}), 400

    username = data.get('username', '').strip()
    password = data.get('password', '')
    confirm_password = data.get('confirm_password', '')
    email = data.get('email', '').strip()

    # 验证
    if not username:
        return jsonify({'code': 400, 'msg': '用户名不能为空'}), 400
    if len(username) < 3 or len(username) > 32:
        return jsonify({'code': 400, 'msg': '用户名长度应在3-32位之间'}), 400
    if not password:
        return jsonify({'code': 400, 'msg': '密码不能为空'}), 400
    if len(password) < 6:
        return jsonify({'code': 400, 'msg': '密码长度至少6位'}), 400
    if password != confirm_password:
        return jsonify({'code': 400, 'msg': '两次密码输入不一致'}), 400
    if email and '@' not in email:
        return jsonify({'code': 400, 'msg': '邮箱格式不正确'}), 400

    # 检查用户名是否已存在
    if User.query.filter_by(username=username).first():
        return jsonify({'code': 400, 'msg': '用户名已存在'}), 400

    # 检查是否为第一个用户（不包括默认admin）
    is_first_user = User.query.count() == 1 and User.query.filter_by(username='admin').first() is not None

    # 创建用户
    user = User(
        username=username,
        email=email or None,
        role='admin' if is_first_user else 'user',
        status='active' if is_first_user else 'inactive',
        created_at=datetime.utcnow()
    )
    user.set_password(password)

    db.session.add(user)
    db.session.commit()

    # 第一个用户自动登录
    if is_first_user:
        login_user(user)

    return jsonify({
        'code': 200,
        'msg': '注册成功' + ('，您已成为管理员' if is_first_user else '，请等待管理员审核'),
        'data': {
            'is_first_user': is_first_user,
            'needs_activation': not is_first_user
        }
    })


@app.route('/login', methods=['GET', 'POST'])
def login():
    """登录页面"""
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    error = None
    if request.method == 'POST':
        # 处理 JSON 请求
        if request.is_json:
            data = request.get_json()
            username = data.get('username', '').strip()
            password = data.get('password', '')
        else:
            # 处理表单提交
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')

        if not username or not password:
            if request.is_json:
                return jsonify({'code': 400, 'msg': '用户名和密码不能为空'}), 400
            error = '用户名和密码不能为空'
        else:
            user = User.query.filter_by(username=username).first()

            if user and user.check_password(password):
                if not user.is_active_user():
                    if request.is_json:
                        return jsonify({'code': 403, 'msg': '账号未激活，请联系管理员'}), 403
                    error = '账号未激活，请联系管理员'
                else:
                    login_user(user)
                    # 更新最后登录时间
                    user.last_login = datetime.utcnow()
                    db.session.commit()
                    if request.is_json:
                        return jsonify({'code': 200, 'msg': '登录成功', 'data': user.to_dict()})
                    return redirect(url_for('index'))
            else:
                if request.is_json:
                    return jsonify({'code': 401, 'msg': '用户名或密码错误'}), 401
                error = '用户名或密码错误'

    return render_template('login.html', error=error)


@app.route('/api/current_user')
@login_required
def api_current_user():
    """获取当前用户信息"""
    return jsonify({
        'code': 200,
        'data': current_user.to_dict()
    })


@app.route('/logout')
def logout():
    """登出"""
    logout_user()
    return redirect(url_for('login'))


# ==================== 用户管理 API ====================

@app.route('/api/users', methods=['GET'])
@admin_required
def api_users():
    """获取用户列表"""
    users = User.query.order_by(User.created_at.desc()).all()
    return jsonify({
        'code': 200,
        'data': [user.to_dict() for user in users]
    })


@app.route('/api/users/<int:user_id>', methods=['PUT'])
@admin_required
def api_update_user(user_id):
    """更新用户信息"""
    user = User.query.get_or_404(user_id)

    # 不允许修改自己
    if user_id == current_user.id:
        return jsonify({'code': 403, 'msg': '不能修改自己的基本信息'}), 403

    data = request.get_json()

    if 'email' in data:
        user.email = data['email'] or None

    if 'role' in data and data['role'] in ['admin', 'user']:
        user.role = data['role']

    db.session.commit()

    return jsonify({
        'code': 200,
        'msg': '更新成功',
        'data': user.to_dict()
    })


@app.route('/api/users/<int:user_id>', methods=['DELETE'])
@admin_required
def api_delete_user(user_id):
    """删除用户"""
    user = User.query.get_or_404(user_id)

    # 不允许删除自己
    if user_id == current_user.id:
        return jsonify({'code': 403, 'msg': '不能删除自己'}), 403

    db.session.delete(user)
    db.session.commit()

    return jsonify({
        'code': 200,
        'msg': '删除成功'
    })


@app.route('/api/users/<int:user_id>/status', methods=['PUT'])
@admin_required
def api_toggle_user_status(user_id):
    """切换用户启用状态"""
    user = User.query.get_or_404(user_id)

    # 不允许禁用自己
    if user_id == current_user.id:
        return jsonify({'code': 403, 'msg': '不能禁用自己'}), 403

    user.status = 'active' if user.status == 'inactive' else 'inactive'
    db.session.commit()

    return jsonify({
        'code': 200,
        'msg': '状态更新成功',
        'data': user.to_dict()
    })


# ==================== 错误处理 ====================

@app.errorhandler(413)
def request_entity_too_large(error):
    """文件太大错误处理"""
    return jsonify({'code': 400, 'msg': '文件太大，最大支持 100MB'}), 413


@app.errorhandler(500)
def internal_error(error):
    """内部错误处理"""
    return jsonify({'code': 500, 'msg': '服务器内部错误'}), 500


# ==================== 页面路由 ====================

@app.route('/')
@login_required
def index():
    """首页"""
    return render_template('index.html')


# ==================== 文件上传 API ====================

@app.route('/upload_file', methods=['POST'])
@login_required
def upload_file():
    """
    文件上传接口
    支持多文件上传，返回多个 URL
    """
    files = request.files.getlist('files')

    if not files or all(f.filename == '' for f in files):
        return jsonify({'code': 400, 'msg': '没有选择文件'}), 400

    results = []
    for file in files:
        if file.filename == '':
            continue

        # 获取安全的文件名
        filename = secure_filename(file.filename)
        if not filename:
            filename = file.filename

        # 上传到 OSS
        result = oss_client.upload_from_stream(file.stream, filename)

        if result['success']:
            # 记录上传历史
            history = UploadHistory(
                user_id=current_user.id,
                filename=filename,
                oss_url=result['url'],
                object_key=result['object_key'],
                file_size=None,  # 文件大小需要从 file.stream 获取，但此时已读取
                uploaded_at=datetime.utcnow()
            )
            db.session.add(history)
            db.session.commit()

            results.append({
                'url': result['url'],
                'filename': filename,
                'object_key': result['object_key'],
                'success': True
            })
        else:
            results.append({
                'filename': filename,
                'error': result.get('error', '上传失败'),
                'success': False
            })

    return jsonify({
        'code': 200,
        'data': results
    })


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
    # 初始化数据库
    init_db()
    # 开发模式运行
    app.run(host='0.0.0.0', port=5001, debug=True)
