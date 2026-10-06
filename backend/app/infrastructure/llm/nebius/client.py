from typing import Any

import httpx


class NebiusHTTPError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"Nebius request failed with status {status_code}")
        self.status_code = status_code


class NebiusTransportError(Exception):
    pass


class NebiusClient:
    def __init__(self, base_url: str, api_key: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    async def create_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
        except httpx.TimeoutException as error:
            raise NebiusTransportError("Nebius request timed out") from error
        except httpx.RequestError as error:
            raise NebiusTransportError("Nebius request failed") from error

        if response.status_code >= 400:
            raise NebiusHTTPError(response.status_code)
        return response.json()
