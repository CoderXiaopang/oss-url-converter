
import os
import sys
from app import app, db, User

def reset_admin_password(new_password, username='admin'):
    """重置管理员密码"""
    with app.app_context():
        user = User.query.filter_by(username=username).first()
        if not user:
            print(f"错误: 用户 '{username}' 不存在")
            return False
        
        user.set_password(new_password)
        db.session.commit()
        print(f"成功: 用户 '{username}' 的密码已重置")
        return True

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法: python reset_admin.py <新密码> [用户名]")
        print("示例: python reset_admin.py admin123")
        sys.exit(1)
    
    password = sys.argv[1]
    username = sys.argv[2] if len(sys.argv) > 2 else 'admin'
    
    reset_admin_password(password, username)
