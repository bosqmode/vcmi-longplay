FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt server.py ./

RUN pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /saves

EXPOSE 8000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]