FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
COPY templates templates
RUN useradd --system support && mkdir /data && chown support /data
USER support
ENV DATABASE_PATH=/data/support.sqlite3
EXPOSE 8000
CMD ["waitress-serve", "--listen=0.0.0.0:8000", "--call", "app:create_app"]
