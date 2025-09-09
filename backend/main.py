# main.py (Refined for simpler logic)
from langfuse import Langfuse
from langfuse.decorators import langfuse_context, observe
import os
import logging
from typing import List, Dict, Optional, Any, AsyncGenerator
import asyncio
import json
from fastapi import FastAPI, Response
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
import uvicorn
from dotenv import load_dotenv

from models import LLMFinanceAnalyzer
from functions import MongoHybridSearch
from systemprompt import (
    get_rag_classification_prompt,
    get_subquery_prompt,
    get_normal_prompt,
    get_non_rag_prompt,
)

# --- Setup ---
load_dotenv(override=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

langfuse = Langfuse(
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    host=os.getenv("LANGFUSE_HOST")
)
langfuse_context.configure(environment='development')

# --- Constants ---
MAX_ASSISTANT_MSG_LENGTH_FOR_CLASSIFICATION = 300
STREAMING_CONTENT_TYPE = "text/plain; charset=utf-8"

# --- Pydantic Models ---
class ChatMessage(BaseModel):
    role: str = Field(..., description="Role of the speaker ('user' or 'assistant')")
    content: str = Field(..., description="Content of the message")

class ChatRequest(BaseModel):
    user_id: Optional[str] = Field("default_user", description="Identifier for the user session")
    history: List[ChatMessage] = Field([], description="Previous conversation history")
    message: str = Field(..., description="The latest message from the user")

class ChatResponse(BaseModel):
    reply: str = Field(..., description="The chatbot's full reply (for non-streaming responses)")
    stage: str = Field(..., description="Indicates the processing stage or type of response generated")
    current_rag_decision: Optional[str] = Field(None, description="RAG decision ('yes' or 'no') for the current message.")
    debug_info: Optional[Dict[str, Any]] = Field(None, description="Optional debug information")

# --- FastAPI Application Setup ---
app = FastAPI(
    title= "Rabbit reward Chatbot API",
    description="API for Rabbit reward Chatbot with a simplified RAG/Non-RAG workflow.",
    version="0.0.0"
)

# --- Global Instances ---
try:
    llm_analyzer = LLMFinanceAnalyzer()
    search_engine = MongoHybridSearch()
    logger.info("Successfully initialized LLMAnalyzer and MongoHybridSearch.")
except Exception as e:
    logger.critical(f"Fatal error during initialization: {e}", exc_info=True)
    # Depending on deployment, you might want the app to fail hard here.
    # raise RuntimeError(f"Failed to initialize core components: {e}")

# --- Helper Functions ---
def create_truncated_history_for_classification(
    full_conversation: List[Dict[str, str]], max_assistant_length: int
) -> List[Dict[str, str]]:
    """Creates a truncated copy of conversation history for efficient classification."""
    truncated_history = []
    for msg in full_conversation:
        processed_msg = msg.copy()
        if processed_msg.get("role") == "assistant" and len(processed_msg.get("content", "")) > max_assistant_length:
            processed_msg["content"] = processed_msg["content"][:max_assistant_length] + "..."
        truncated_history.append(processed_msg)
    return truncated_history

def generate_pseudo_conversation(conversation: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Generates a pseudo-conversation string from history for the subquery model."""
    pseudo_conversation = "".join(f"{msg.get('role', 'unknown')}: {msg.get('content', '')}\n" for msg in conversation)
    return [{'role': "user", "content": pseudo_conversation.strip()}]
def detect_thai_or_english(text: str) -> str:
    """
    Detects if a string is primarily Thai, English, or a mix of both.

    This works by checking for the presence of characters in the Unicode
    ranges specific to each language.
    """
    if not text or text.isspace():
        return "en"

    
    

    for char in text:
        # Check for Thai characters (including vowels, tone marks, etc.)
        # Thai Unicode block is U+0E00 to U+0E7F
        
        if '\u0e00' <= char <= '\u0e7f':
            return "th"
        
        

    
    return "en"


# --- API Endpoint ---
@app.post("/chat")
@observe()
async def handle_chat(request: ChatRequest) -> Response:
    """
    Handles incoming chat messages with a simplified workflow.
    - Classifies the request into 'RAG' or 'Non-RAG'.
    - Returns `StreamingResponse` for all RAG responses.
    - Returns `JSONResponse` for Non-RAG responses and all errors.
    """
    logger.info(f"Received chat request for user: {request.user_id}")
    full_conversation = [msg.dict() for msg in request.history] + [{"role": "user", "content": request.message}]
    truncated_conversation = create_truncated_history_for_classification(full_conversation, MAX_ASSISTANT_MSG_LENGTH_FOR_CLASSIFICATION)
    pseudo_conversation = generate_pseudo_conversation(truncated_conversation)
    
    stage = "Initiated"
    debug_info: Dict[str, Any] = {"classification": {}}

    def create_json_error_response(message: str, final_stage: str, rag_decision: Optional[str], status_code: int = 500) -> JSONResponse:
        logger.error(f"Returning error: {message} (Stage: {final_stage}, Status: {status_code})")
        response_data = ChatResponse(
            reply=message,
            stage=final_stage,
            current_rag_decision=rag_decision,
            debug_info={**debug_info, "error": message}
        )
        return JSONResponse(content=response_data.model_dump(exclude_none=True), status_code=status_code)

    try:
        # --- Simplified Single-Step Classification ---
        stage = "RAG Classification"
        rag_decision = await llm_analyzer.classify_rag_requirement(pseudo_conversation)
        debug_info["classification"]["rag_decision_result"] = rag_decision

        lang = detect_thai_or_english(full_conversation[-1].get("content"))
        print(f"lang detected:{lang}")
        if rag_decision not in ['yes', 'no']:
            logger.warning(f"RAG classification returned an unexpected value: '{rag_decision}'. Defaulting to 'no'.")
            rag_decision = 'yes'

        logger.info(f"Final Classification: RAG Required = {rag_decision}")

        # --- Pipeline Execution ---
        if rag_decision == 'yes':
            # --- RAG Pipeline (Always Streaming) ---
            stage = "RAG"
            logger.info("Executing RAG Pipeline - Streaming")

            # 1. Generate Subqueries
            query = await llm_analyzer.generate_subquery(pseudo_conversation)
            if query is None:
                return create_json_error_response("ขออภัยค่ะ ไม่สามารถวิเคราะห์คำถามเพื่อดึงข้อมูลได้", stage + " - Error: Subquery Failed", rag_decision, 400)

            # prethinking, subquery_fact, subquery_report = subquery_result
            # logger.info(f"Generated {len(subquery_fact)} fact subqueries and {len(subquery_report)} report subqueries.")
            # debug_info["subqueries"] = {"fact": subquery_fact, "report": subquery_report, "prethinking": prethinking}

            # 2. Search Documents
            retrieved_data = ""
            if query:
                try:
                    docs = await search_engine.search_documents(query) if query else []
                    # docs_report = await search_engine.search_documents(subquery_report, "report") if subquery_report else []
                    
                    # all_docs = [doc for doc_list in (docs_fact + docs_report) for doc in doc_list if doc]
                    # unique_docs = list(dict.fromkeys(docs)) # Simple deduplication
                    
                    # if not unique_docs:
                    #     logger.warning("RAG: Database search returned no unique documents.")
                    #     return create_json_error_response("ฉันไม่พบข้อมูลที่เกี่ยวข้องกับคำถามของคุณค่ะ", stage + " - No Documents Found", rag_decision, 404)

                    retrieved_data = "\n-------\n".join(docs)
                    logger.info(f"RAG: Retrieved {len(docs)} unique documents.")
                    debug_info["retrieved_data_snippet"] = retrieved_data[:500] + "..."

                except Exception as search_err:
                    logger.error(f"RAG: Error during document search: {search_err}", exc_info=True)
                    return create_json_error_response("ขออภัยค่ะ เกิดข้อผิดพลาดขณะค้นหาข้อมูล", stage + " - Error: Search Failed", rag_decision, 500)
            else:
                logger.info("RAG: No subqueries generated, proceeding without document search.")

            # 3. Generate Response (Streaming)
            stage = "RAG Generation (Streaming)"
            if len(full_conversation) >7:
                full_conversation = full_conversation[-7:]
            response_generator = llm_analyzer.generate_normal_response(retrieved_data, full_conversation, lang)

            async def stream_wrapper(gen: AsyncGenerator[str, None]):
                try:
                    async for chunk in gen:
                        yield chunk
                        await asyncio.sleep(0.05)
                    logger.info("Finished RAG stream transmission.")
                except Exception as e_stream:
                    logger.error(f"Error during stream transmission: {e_stream}", exc_info=True)
                    yield f"\n[STREAM_ERROR: {e_stream}]\n"

            headers = {"X-Final-Stage": stage, "X-RAG-Decision": rag_decision}
            return StreamingResponse(stream_wrapper(response_generator), media_type=STREAMING_CONTENT_TYPE, headers=headers)

        else: # rag_decision == 'no'
            # --- Non-RAG Pipeline (JSON Response) ---
            stage = "Non-RAG Generation"
            logger.info("Executing Non-RAG Pipeline")
            if len(full_conversation) >7:
                full_conversation = full_conversation[-9:]

            final_response = await llm_analyzer.generate_non_rag_response(full_conversation,lang)
            if final_response is None:
                return create_json_error_response("ขออภัยค่ะ เกิดข้อผิดพลาดในการประมวลผลคำถามของคุณ", stage + " - Error: Generation Failed", rag_decision, 500)

            stage += " - Completed"
            response_data = ChatResponse(
                reply=final_response,
                stage=stage,
                current_rag_decision=rag_decision,
                debug_info=debug_info
            )
            return JSONResponse(content=response_data.model_dump(exclude_none=True))

    except Exception as e:
        logger.critical(f"Unhandled exception in handle_chat: {e}", exc_info=True)
        return create_json_error_response("ขออภัยค่ะ เกิดข้อผิดพลาดที่ไม่คาดคิด", stage + " - Error: Unhandled", None, 500)

# --- Run Application ---
if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    logger.info(f"Starting SCG Financial Chatbot API server at http://{host}:{port}")
    uvicorn.run("main:app", host=host, port=port, reload=True)