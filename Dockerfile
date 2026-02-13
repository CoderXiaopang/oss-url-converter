FROM python:3.12-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 复制启动脚本
COPY docker-entrypoint.sh /app/
RUN chmod +x /app/docker-entrypoint.sh

# 暴露端口
EXPOSE 5001

# 入口点
ENTRYPOINT ["/app/docker-entrypoint.sh"]

# 使用 gunicorn 生产服务器运行
CMD ["python", "app.py"]
