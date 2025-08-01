import httpx
import json
import requests
import asyncio
import logging
import time
from datetime import datetime


class LLMGateway:
    """
    If api_url points at an Ollama host (e.g. http://localhost:11434),
    we use its /api/chat endpoint. Otherwise default to OpenAI.
    """
    def __init__(self, api_url: str | None = None, api_key: str | None = None,
                 model: str = "gpt-3.5-turbo"):
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        # self._client = httpx.AsyncClient(timeout=60.0)
        self._client = httpx.AsyncClient(
            timeout=30.0,
            trust_env=False,  # ignore any HTTP_PROXY
            http2=False,  # force HTTP/1.1
            headers={"Accept-Encoding": "identity"},
        )
        self._setup_logging()
        self._load_system_prompt()
    
    def _setup_logging(self):
        """Setup logging for AI requests and responses"""
        self.logger = logging.getLogger("llm_gateway")
        if not self.logger.handlers:
            handler = logging.FileHandler("logs/ai_requests.log")
            formatter = logging.Formatter(
                "%(asctime)s - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
    
    def _log_request_response(self, prompt: str, response: str, duration: float, status_code: int = None):
        """Log AI request and response with metadata"""
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "model": self.model,
            "prompt_length": len(prompt),
            "response_length": len(response),
            "duration_seconds": round(duration, 3),
            "status_code": status_code,
            "prompt": prompt[:500] + "..." if len(prompt) > 500 else prompt,
            "response": response[:500] + "..." if len(response) > 500 else response
        }
        self.logger.info(f"AI_REQUEST: {json.dumps(log_data, ensure_ascii=False)}")
    
    def _load_system_prompt(self):
        """Load system prompt from modelfile"""
        try:
            with open("../config/modelfile.txt", "r", encoding="utf-8") as f:
                content = f.read()
                # Extract content between SYSTEM """ markers
                start = content.find('SYSTEM """')
                if start != -1:
                    start += len('SYSTEM """')
                    end = content.find('"""', start)
                    if end != -1:
                        self.system_prompt = content[start:end].strip()
                    else:
                        self.system_prompt = None
                        raise ValueError

                else:
                    self.system_prompt = None
                    raise ValueError

        except FileNotFoundError:
            self.system_prompt = None
            raise ValueError



    async def chat(self, prompt: str) -> str:
        start_time = time.time()
        response_text = ""
        status_code = None
        
        try:
            # --- OLLAMA branch ------------------------------------------- #
            if self.api_url and "11434" in self.api_url:
                payload = {
                    "model": self.model,               # "gemma2:latest"
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False                    # get one JSON blob back
                }

                r = await self._client.post(f"{self.api_url}/api/chat", json=payload, headers={"Connection": "close"})
                status_code = r.status_code
                r.raise_for_status()

                data = r.json()
                response_text = data["message"]["content"]
                return response_text

            # --- OPENAI branch ------------------------------- #
            messages = []
            if self.system_prompt:
                messages.append({"role": "system", "content": self.system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False
            }

            headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
            r = await self._client.post(self.api_url, json=payload, headers=headers)
            status_code = r.status_code
            r.raise_for_status()
            data = r.json()
            response_text = data["choices"][0]["message"]["content"]
            return response_text
        
        finally:
            duration = time.time() - start_time
            self._log_request_response(prompt, response_text, duration, status_code)

    async def chat_bad(self, prompt: str) -> str:
        """
        Same signature, but uses `requests.post()` under the hood.
        Runs the blocking call inside `run_in_executor` so this coroutine
        still yields to the event-loop.
        """
        loop = asyncio.get_running_loop()

        # -------- helper to turn payload + url into a curl string --------
        def _curl(api, body, extra_hdrs=None):
            hdrs = " ".join(
                f"-H '{k}: {v}'" for k, v in (extra_hdrs or {}).items()
            )
            return (
                f"curl -s -X POST {api} "
                f"{hdrs} -H 'Content-Type: application/json' "
                f"-d '{json.dumps(body, ensure_ascii=False)}' | jq"
            )

        # --- OLLAMA branch --------------------------------------------- #
        if self.api_url and "11434" in self.api_url:
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            }
            api = f"{self.api_url.rstrip('/')}/api/chat"
            print("\n=== CURL to reproduce request ===")
            print(_curl(api, payload))
            print("=======================================================\n")

            def _post():
                r = requests.post(api, json=payload, timeout=120)  # 2-min cap
                r.raise_for_status()
                return r.json()["message"]["content"]

            return await loop.run_in_executor(None, _post)

        # --- OPENAI branch --------------------------------------------- #
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        print("\n=== CURL to reproduce request ===")
        print(_curl(self.api_url, payload, headers))
        print("=======================================================\n")

        def _post_openai():
            r = requests.post(self.api_url, json=payload, headers=headers, timeout=120)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]

        return await loop.run_in_executor(None, _post_openai)
