# =============================================================================
# Async RAG query (SQS + DynamoDB resultado + dispatcher en API GW)
# =============================================================================

variable "enable_async_rag_query" {
  description = "Cuando está activo: cola rag-query-documents, tabla rag_result_query_table, dispatcher en /query,/query/status,/query/result y worker disparado por SQS."
  type        = bool
  default     = false
}
