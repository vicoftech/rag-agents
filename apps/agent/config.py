"""
Configuración centralizada para el Agente RAG con Bedrock AgentCore
"""
import os
from dotenv import load_dotenv

load_dotenv()

# AWS Configuration
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID_DEV', '')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY_DEV', '')

# Database Configuration
DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "postgres"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "postgres"),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
}

# LLM Models
AGENT_MODEL_ID = os.getenv("AGENT_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")
EMBEDDINGS_MODEL = os.getenv("EMBEDDINGS_MODEL", "cohere.embed-v4:0")

# RAG Configuration
MAX_EMBED_TEXT_LENGTH = 20000
DEFAULT_TOP_K = 50
EMBEDDING_DIMENSIONS = 1536

# Agent Configuration
AGENT_NAME = os.getenv("AGENT_NAME", "RAG Knowledge Agent")
AGENT_DESCRIPTION = """
Agente inteligente que busca información en bases de conocimiento usando RAG (Retrieval Augmented Generation).
Puede responder preguntas basándose en documentos indexados por tenant y agente.
"""

# Lambda Configuration
LAMBDA_EMBEDDINGS = os.getenv("LAMBDA_EMBEDDINGS", "rag_lmbd_embeddings")
LAMBDA_QUERY = os.getenv("LAMBDA_QUERY", "rag_lmbd_query")

# MCP Server Configuration
MCP_HOST = os.getenv("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.getenv("MCP_PORT", "8080"))

