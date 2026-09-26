# Pinned to the reviewed Python 3.12 Debian image at deployment time.
ARG PYTHON_IMAGE=python@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
FROM ${PYTHON_IMAGE}
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pyproject.toml ./
COPY requirements.lock ./
COPY home_agent_tools ./home_agent_tools
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps . && useradd --uid 10001 --create-home hat && mkdir /data && chown hat:hat /data
USER 10001:10001
EXPOSE 4450
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import os,urllib.request; u=os.environ.get('HAT_PUBLIC_URL','http://localhost:4444'); r=urllib.request.Request('http://127.0.0.1:4450/health',headers={'Host':__import__('urllib.parse',fromlist=['urlsplit']).urlsplit(u).netloc}); urllib.request.urlopen(r,timeout=3)" || exit 1
CMD ["uvicorn", "home_agent_tools.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "4450", "--no-access-log", "--no-proxy-headers"]
