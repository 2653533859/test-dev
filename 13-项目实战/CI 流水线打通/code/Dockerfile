# 测试执行器镜像：把执行环境固化成带版本的制品，agent 只需要有 Docker。
# 设计说明见笔记《Docker 化测试执行环境》

FROM python:3.11-slim

# 时区必须显式设置：容器默认 UTC，会导致报告时间差 8 小时，
# 且「断言创建时间是今天」这类用例在北京时间早上 8 点前必挂（只在凌晨复现，极难排查）。
ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# allure 命令行依赖 JRE；curl 用于健康检查
RUN apt-get update && apt-get install -y --no-install-recommends \
        default-jre-headless curl unzip \
    && rm -rf /var/lib/apt/lists/*

ARG ALLURE_VERSION=2.29.0
RUN curl -sL -o /tmp/allure.zip \
        "https://github.com/allure-framework/allure2/releases/download/${ALLURE_VERSION}/allure-${ALLURE_VERSION}.zip" \
    && unzip -q /tmp/allure.zip -d /opt \
    && rm /tmp/allure.zip \
    && ln -s /opt/allure-${ALLURE_VERSION}/bin/allure /usr/local/bin/allure

WORKDIR /app

# 依赖单独一层：变化频率低的放前面，requirements.txt 没变就命中缓存，
# 构建从 2 分钟降到 10 秒。
COPY requirements.txt .
RUN pip install -r requirements.txt

# 与宿主机 Jenkins 用户同 UID，避免容器内生成的文件属主是 root，
# 导致 cleanWs() 删不掉、workspace 一直堆积。
RUN useradd -m -u 1000 qa && chown -R qa:qa /app
USER qa

CMD ["pytest", "--version"]
