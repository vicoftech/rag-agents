# Dockerfile para despliegue en Amazon Bedrock AgentCore
FROM python:3.12-slim

# Establecer directorio de trabajo
WORKDIR /app

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements e instalar dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código de la aplicación
COPY . .

# Variables de entorno por defecto
ENV AWS_REGION=us-east-1
ENV PYTHONUNBUFFERED=1

# Puerto para el servidor MCP
EXPOSE 8080

# Comando por defecto - AgentCore handler
CMD ["python", "agentcore_handler.py"]

