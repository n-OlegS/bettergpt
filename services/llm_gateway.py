import httpx
import json
import requests
import asyncio


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

    async def chat(self, prompt: str) -> str:
        # --- OLLAMA branch ------------------------------------------- #
        if self.api_url and "11434" in self.api_url:
            payload = {
                "model": self.model,               # "gemma2:latest"
                "messages": [{"role": "user", "content": prompt}],
                "stream": False                    # get one JSON blob back
            }

            r = await self._client.post(f"{self.api_url}/api/chat", json=payload, headers={"Connection": "close"})
            r.raise_for_status()

            data = r.json()
            return data["message"]["content"]

        # --- OPENAI branch (unchanged) ------------------------------- #
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False
        }

        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        r = await self._client.post(self.api_url, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]

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
