# models.py

import os
import ast
import re
import logging
import json
import asyncio
from typing import List, Dict, Any, Optional, Union, Tuple, AsyncGenerator
from dotenv import load_dotenv
from openai import AsyncOpenAI, RateLimitError, APIError
from sentence_transformers import SentenceTransformer
from langfuse.decorators import langfuse_context, observe

from systemprompt import (
    get_rag_classification_prompt,
    get_subquery_prompt,
    get_normal_prompt,
    get_non_rag_prompt,
)

load_dotenv(override=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
ConversationHistory = List[Dict[str, str]]

# --- Constants ---
CLASSIFICATION_MODEL = "jai-chat-1-3-2"
SUBQUERY_MODEL = "jai-chat-1-3-2"
NORMAL_RAG_MODEL = 'typhoon-gemma-12b'
NON_RAG_MODEL = "jai-chat-1-3-2"

# --- Embedding Setup (Global Scope) ---
BGE = SentenceTransformer("BAAI/bge-m3")

class Embedder:
    def __init__(self):
        """Initializes the Embedder with a local BGE model."""
        logger.info("Embedder initialized with BGE SentenceTransformer.")

    async def embed(self, text: Union[str, List[str]], input_type: str) -> Optional[List[List[float]]]:
        """
        Generate embeddings using a local BGE model asynchronously.
        The 'input_type' parameter is kept for signature consistency but is not used by this BGE implementation.
        """
        try:
            # BGE.encode is synchronous and CPU-bound, so run it in a thread to avoid blocking the event loop.
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(None, BGE.encode, text)
            return response.tolist()
        except Exception as e:
            logger.error(f"Error during BGE embedding: {e}", exc_info=True)
            return None

class LLMFinanceAnalyzer:
    def __init__(self):
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.typhoon_api_key = os.getenv("TYPHOON_API_KEY")
        self.typhoon_base_url = os.getenv("TYPHOON_BASE_URL")
        self.gemma_api_key = os.getenv("GEMMA_API_KEY")
        self.gemma_base_url = os.getenv("GEMMA_BASE_URL")
        self.jai_api_key = os.getenv("JAI_API_KEY")
        self.jai_base_url = os.getenv("JAI_BASE_URL")
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")

        if not self.jai_api_key or not self.jai_base_url:
            logger.error("JTS_API_KEY or JAI_BASE_URL not found for JAI client.")
            raise ValueError("JAI API credentials are not configured.")
        try:
            self.client_jai = AsyncOpenAI(base_url=self.jai_base_url, api_key=self.jai_api_key)
            logger.info("LLMFinanceAnalyzer initialized with JAI client.")
        except Exception as e:
            logger.error(f"Failed to initialize JAI client: {e}")
            raise
        
        self.client_gemini = None
        if self.gemini_api_key:
            try:
                self.client_gemini = AsyncOpenAI(api_key=self.gemini_api_key, base_url="https://generativelanguage.googleapis.com/v1beta/openai/")
                logger.info("LLMFinanceAnalyzer initialized with Gemini client.")
            except Exception as e:
                logger.error(f"Failed to initialize Gemini client: {e}")
        else:
            logger.warning("GEMINI_API_KEY not found, Gemini client not initialized.")

        self.client_openai = None
        if self.openai_api_key:
            try:
                self.client_openai = AsyncOpenAI(api_key=self.openai_api_key)
                logger.info("LLMFinanceAnalyzer initialized with OpenAI client.")
            except Exception as e:
                logger.error(f"Failed to initialize OpenAI client: {e}")
        else:
            logger.warning("OPENAI_API_KEY not found, OpenAI client not initialized.")

        self.client_typhoon = None
        if self.typhoon_api_key:
            try:
                self.client_typhoon = AsyncOpenAI(api_key=self.typhoon_api_key, base_url=self.typhoon_base_url)
                logger.info("LLMFinanceAnalyzer initialized with typhoon client.")
            except Exception as e:
                logger.error(f"Failed to initialize typhoon client: {e}")
        else:
            logger.warning("TYPHOON_API_KEY not found, typhoon client not initialized.")

        self.client_gemma = None
        if self.gemma_api_key:
            try:
                self.client_gemma = AsyncOpenAI(api_key=self.gemma_api_key, base_url=self.gemma_base_url)
                logger.info("LLMFinanceAnalyzer initialized with gemma client.")
            except Exception as e:
                logger.error(f"Failed to initialize gemma client: {e}")
        else:
            logger.warning("GEMMA_API_KEY not found, gemma client not initialized.")

    def _get_client_for_model(self, model_name: str) -> Optional[AsyncOpenAI]:
        """Selects the appropriate client based on the model name."""
        if model_name.startswith("gpt-"):
            return self.client_openai
        elif model_name.startswith("gemini-"):
            return self.client_gemini
        elif model_name.startswith("typhoon-"):
            return self.client_typhoon
        elif model_name.startswith("gemma3-"):
            return self.client_gemma
        else:
            return self.client_jai

    @observe()
    async def _call_llm(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int = 2048,
        seed: int = 66,
        max_retries: int = 2,
        stream: bool = False
    ) -> Union[Optional[str], AsyncGenerator[str, None]]:
        """Internal helper to call the appropriate LLM client with retries."""
        client = self._get_client_for_model(model)
        if not client:
            logger.error(f"No async client available for model {model}.")
            return None if not stream else (x for x in [])

        attempt = 0
        while attempt <= max_retries:
            try:
                if stream:
                    response_stream = await client.chat.completions.create(
                        model=model, messages=messages, stream=True
                    )
                    async def _async_stream_generator():
                        try:
                            async for chunk in response_stream:
                                delta_content = chunk.choices[0].delta.content.replace("•", "\n•")
                                
                                if delta_content:
                                    yield delta_content
                        except Exception as stream_err:
                            logger.error(f"Error during LLM stream ({model}): {stream_err}", exc_info=True)
                            yield f"\n[STREAM_ERROR: {stream_err}]\n"
                    return _async_stream_generator()
                else:
                    response = await client.chat.completions.create(
                        model=model, messages=messages,  stream=False
                    )
                    content = response.choices[0].message.content
                    return content.strip() if content else ""
            except (RateLimitError, APIError, Exception) as e:
                logger.warning(f"Error on attempt {attempt+1} for model {model}: {e}. Retrying...")
                attempt += 1
                if attempt > max_retries:
                    logger.error(f"Max retries exceeded for LLM call ({model}).")
                    if stream:
                        async def _error_gen(): yield f"\n[STREAM_ERROR: Max retries exceeded]\n"
                        return _error_gen()
                    return None
                await asyncio.sleep(3 * attempt)
        return None

    @observe()
    async def classify_rag_requirement(self, conversation: ConversationHistory) -> Optional[str]:
        """Classifies if the latest query requires RAG ('yes' or 'no') using full context."""
        if not conversation:
            return 'no'
        print(conversation)
        system_prompt = get_rag_classification_prompt()
        messages = [{"role": "user", "content": system_prompt+"/n"+conversation[0].get("content")}] 
        result = await self._call_llm(model=CLASSIFICATION_MODEL, messages=messages, temperature=0, max_tokens=10, stream=False)
        print(result)
        if isinstance(result, str):
            result_lower = result.lower().strip().rstrip('.')
            if 'yes' in result_lower: return 'yes'
            if 'no' in result_lower: return 'no'
            logger.error(f"RAG classification result '{result}' invalid. Defaulting to 'no'.")
        else:
            logger.error("RAG classification LLM call failed.")
            return 'yes'

    @observe()
    async def generate_subquery(self, conversation: ConversationHistory) -> Optional[str]:
        """Generates structured database query components based on the conversation without tool use."""
        if not conversation:
            logger.warning("generate_subquery called with empty conversation")
            return None

        client = self._get_client_for_model(SUBQUERY_MODEL)
        if not client:
            logger.error(f"Client for subquery model '{SUBQUERY_MODEL}' not available")
            return None

        system_prompt_content = get_subquery_prompt()
        messages = [{"role": "system", "content": system_prompt_content}] + conversation

        try:
            response = await client.chat.completions.create(
                model=SUBQUERY_MODEL,
                messages=messages,
                temperature=0,
            )
            final_content = response.choices[0].message.content
        except Exception as e:
            logger.error(f"API call error in generate_subquery: {e}", exc_info=True)
            return None

        if not final_content:
            logger.error("No content received from subquery model")
            return None

        return final_content

    @observe()
    async def generate_normal_response(self, data: str, conversation: ConversationHistory) -> AsyncGenerator[str, None]:
        """Generate a RAG response, yielding text chunks."""
        try:
            
            
            system_prompt = get_normal_prompt( data)
            messages = [{"role": "system", "content": system_prompt}] + conversation

            result_generator = await self._call_llm(
                model=NORMAL_RAG_MODEL, messages=messages, temperature=0.2, stream=True
            )
            
            if isinstance(result_generator, AsyncGenerator):
                async for chunk in result_generator:
                    yield chunk
            else:
                yield "[ERROR: Failed to initiate normal RAG stream.]"
        except Exception as e:
            logger.error(f"Error in generate_normal_response setup: {e}", exc_info=True)
            yield f"[ERROR: {e}]"

    @observe()
    async def generate_non_rag_response(self, conversation: ConversationHistory) -> Optional[str]:
        """Generate response for non-RAG questions."""
        messages = [{"role": "system", "content": get_non_rag_prompt()}] + conversation
        result = await self._call_llm(model=NON_RAG_MODEL, messages=messages, temperature=0, stream=False)
        
        if isinstance(result, str):
            return result
        
        logger.error("generate_non_rag_response call failed or returned non-string.")
        return None