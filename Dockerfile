FROM python:3.13-alpine
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY app.py /app/app.py
COPY static /app/static
EXPOSE 8009
CMD ["python3", "/app/app.py"]
