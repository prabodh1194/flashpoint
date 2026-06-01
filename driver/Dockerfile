FROM eclipse-temurin:17-jre-jammy

ARG SPARK_VERSION=4.0.2
ARG HADOOP_VERSION=3

ENV SPARK_HOME=/opt/spark
ENV PATH="${SPARK_HOME}/bin:${PATH}"
ENV SPARK_VERSION=${SPARK_VERSION}

# Install Spark
RUN apt-get update && apt-get install -y --no-install-recommends curl procps iproute2 coreutils && \
    curl -fsSL "https://dlcdn.apache.org/spark/spark-${SPARK_VERSION}/spark-${SPARK_VERSION}-bin-hadoop${HADOOP_VERSION}.tgz" \
      | tar -xz -C /opt && \
    mv "/opt/spark-${SPARK_VERSION}-bin-hadoop${HADOOP_VERSION}" "${SPARK_HOME}" && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Pre-register a fixed hostname so InetAddress.getLocalHost() resolves
# even in Lambda containers where the UUID hostname has no DNS entry.
RUN echo "127.0.0.1 spark-driver" >> /etc/hosts
ENV HOSTNAME=spark-driver

COPY entrypoint.sh /opt/entrypoint.sh
COPY executor-entrypoint.sh /opt/executor-entrypoint.sh
RUN chmod +x /opt/entrypoint.sh /opt/executor-entrypoint.sh

# Spark Connect gRPC | Standalone master | driver RPC | block manager
EXPOSE 15002 7077 7078 7337

ENTRYPOINT ["/opt/entrypoint.sh"]
