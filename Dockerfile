FROM python:3.13-alpine
WORKDIR /app
COPY app.py /app/app.py
COPY static /app/static
EXPOSE 8009
CMD ["python3", "/app/app.py"]
