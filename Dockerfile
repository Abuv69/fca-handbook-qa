FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir ".[ui]"
COPY sql ./sql
COPY app ./app
COPY eval ./eval
COPY data/demo ./data/demo
EXPOSE 8000
CMD ["uvicorn", "fcaqa.api:app", "--host", "0.0.0.0", "--port", "8000"]
