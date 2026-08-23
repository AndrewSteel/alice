FROM python:3.12-alpine
WORKDIR /app
RUN pip install --no-cache-dir flask==3.1.0 gunicorn==23.0.0 pycryptodome==3.21.0 pypdf==5.1.0
COPY app.py .
EXPOSE 8007
CMD ["gunicorn", "--bind", "0.0.0.0:8007", "--workers", "2", "--timeout", "60", "app:app"]
