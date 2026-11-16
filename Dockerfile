FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY tasks ./tasks
EXPOSE 8000
CMD ["datapatch", "serve", "--host", "0.0.0.0"]
