FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY asienta ./asienta
RUN pip install --no-cache-dir ".[claude,excel]"
VOLUME /data
WORKDIR /data
EXPOSE 8760
# first run: a commented config.ini and an example ledger in /data
CMD ["sh", "-c", "[ -f config.ini ] || asienta init . ; exec asienta --host 0.0.0.0"]
