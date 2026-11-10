FROM python:3.12-slim
COPY requirements-math.txt /tmp/requirements-math.txt
RUN pip install --no-cache-dir -r /tmp/requirements-math.txt && useradd -u 10001 -m math && mkdir /run/math && chown math:math /run/math
COPY math_executor /opt/math_executor
USER 10001:10001
WORKDIR /tmp
ENV PYTHONDONTWRITEBYTECODE=1
CMD ["python", "-I", "/opt/math_executor/server.py"]
