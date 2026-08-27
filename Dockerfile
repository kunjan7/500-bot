# For Koyeb / HuggingFace Spaces / any Docker host — 100% free no-card option
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Playwright browsers already in base image
ENV HANDLE=kunjan1387
ENV MAX_DRAFTS=1000
ENV HOLD_SEC=20
ENV EXPLORE=1
CMD ["python", "spin_freq.py"]
