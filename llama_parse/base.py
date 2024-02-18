import os
import asyncio
import httpx
import mimetypes
import time
from enum import Enum
from typing import List, Optional

from llama_index.core.bridge.pydantic import Field, validator
from llama_index.core.constants import DEFAULT_BASE_URL
from llama_index.core.readers.base import BasePydanticReader
from llama_index.core.schema import Document


class ResultType(str, Enum):
    """The result type for the parser."""

    TXT = "text"
    MD = "markdown"


class LlamaParse(BasePydanticReader):
    """A smart-parser for files."""

    api_key: str = Field(default="", description="The API key for the LlamaParse API.")
    base_url: str = Field(
        default=DEFAULT_BASE_URL,
        description="The base URL of the Llama Parsing API.",
    )
    result_type: ResultType = Field(
        default=ResultType.TXT, description="The result type for the parser."
    )
    check_interval: int = Field(
        default=1,
        description="The interval in seconds to check if the parsing is done.",
    )
    max_timeout: int = Field(
        default=2000,
        description="The maximum timeout in seconds to wait for the parsing to finish.",
    )
    verbose: bool = Field(
        default=True, description="Whether to print the progress of the parsing."
    )

    @validator("api_key", pre=True, always=True)
    def validate_api_key(cls, v: str) -> str:
        """Validate the API key."""
        if not v:
            import os
            api_key = os.getenv("LLAMA_CLOUD_API_KEY", None)
            if api_key is None:
                raise ValueError("The API key is required.")
            return api_key
        
        return v
    
    @validator("base_url", pre=True, always=True)
    def validate_base_url(cls, v: str) -> str:
        """Validate the base URL."""
        url = os.getenv("LLAMA_CLOUD_BASE_URL", None)
        return url or v or DEFAULT_BASE_URL

    def load_data(self, file_path: str, extra_info: Optional[dict] = None) -> List[Document]:
        """Load data from the input path."""
        return asyncio.run(self.aload_data(file_path, extra_info))

    async def aload_data(self, file_path: str, extra_info: Optional[dict] = None) -> List[Document]:
        """Load data from the input path."""
        file_path = str(file_path)
        if not file_path.endswith(".pdf"):
            raise Exception("Currently, only PDF files are supported.")

        extra_info = extra_info or {}
        extra_info["file_path"] = file_path

        headers = {"Authorization": f"Bearer {self.api_key}"}

        # load data, set the mime type
        with open(file_path, "rb") as f:
            mime_type = mimetypes.guess_type(file_path)[0]
            files = {"file": (f.name, f, mime_type)}

            # send the request, start job
            url = f"{self.base_url}/api/parsing/upload"
            async with httpx.AsyncClient(timeout=self.max_timeout) as client:
                response = await client.post(url, files=files, headers=headers)
                if not response.is_success:
                    raise Exception(f"Failed to parse the PDF file: {response.text}")

        # check the status of the job, return when done
        job_id = response.json()["id"]
        if self.verbose:
            print("Started parsing the file under job_id %s" % job_id)
        
        result_url = f"{self.base_url}/api/parsing/job/{job_id}/result/{self.result_type.value}"

        start = time.time()
        tries = 0
        while True:
            await asyncio.sleep(self.check_interval)
            async with httpx.AsyncClient(timeout=self.max_timeout) as client:    
                result = await client.get(result_url, headers=headers)

                if result.status_code == 404:
                    end = time.time()
                    if end - start > self.max_timeout:
                        raise Exception(
                            f"Timeout while parsing the PDF file: {response.text}"
                        )
                    if self.verbose and tries % 10 == 0:
                        print(".", end="", flush=True)
                    continue

                if result.status_code == 400:
                    detail = result.json().get("detail", "Unknown error")
                    raise Exception(f"Failed to parse the PDF file: {detail}")

                return [
                    Document(
                        text=result.json()[self.result_type.value],
                        metadata=extra_info,
                    )
                ]
            tries += 1
