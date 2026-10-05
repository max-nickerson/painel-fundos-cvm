FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# cache dos arquivos da CVM/ANBIMA (Spaces gratis: some quando o Space reinicia, e tudo bem)
ENV CVM_CACHE=/tmp/cvm_cache
EXPOSE 7860
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "7860"]
