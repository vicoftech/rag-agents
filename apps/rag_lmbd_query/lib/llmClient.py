import boto3
import json
import time
import re




class LLMClient:
    def __init__(self,bedrock_client,main_model,fallback_model):
        self.client = bedrock_client
        self.main_model = main_model
        self.fallback_model = fallback_model

    def strip_reasoning(self,raw: str) -> str:
        """
        Elimina el primer (o todos) los bloques <reasoning>...</reasoning> del texto
        y devuelve el resto limpio.
        """
        if raw is None:
            return ""

        try:
            # Quitar todos los bloques <reasoning>...</reasoning> (modo DOTALL)
            cleaned = re.sub(r"<reasoning>.*?</reasoning>", "", raw, flags=re.DOTALL)

            # Normalizar espacios al inicio/final
            return cleaned.strip()

        except Exception as e:
            # En caso de error, devolvemos el raw original para no perder la info
            return raw.strip()

    def generate_raw(self, model, prompt):
        """
        Llamado directo al modelo de Bedrock Runtime.
        """

        payload = {
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "max_tokens": 2048,
            "temperature": 0.1,
            "top_p": 0.5
        }


        response = self.client.invoke_model(
            modelId=model,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(payload)
        )
        
        '''
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1024,
                "temperature": 0.3,
                "topP": 0.9,
                "messages": [
                    {"role": "user", "content": prompt}
                ]
            })
        '''

        result = json.loads(response["body"].read())
        return self.strip_reasoning(result["choices"][0]["message"]["content"])

    def generate(self, prompt, max_retries=2):
        """
        Wrapper con fallback:
        1) Intenta con modelo principal
        2) si falla → intenta con fallback
        """
        # ----- Intentar modelo principal -----
        for attempt in range(max_retries):
            try:
                return self.generate_raw(self.main_model, prompt)
            except Exception as e:
                if attempt == max_retries - 1:
                    break  # pasar a fallback
                time.sleep(0.5)

        # ----- Intentar fallback -----
        for attempt in range(max_retries):
            try:
                return self.generate_raw(self.fallback_model, prompt)
            except Exception:
                if attempt == max_retries - 1:
                    raise Exception("No fue posible generar respuesta con ninguno de los modelos.")
                time.sleep(0.5)
