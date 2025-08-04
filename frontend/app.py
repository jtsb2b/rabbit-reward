# app.py (Streamlit Frontend - Corrected Caption Centering)

import streamlit as st
import requests
import os
import re
import logging
import json
import traceback

# --- Streamlit Page Setup ---
st.set_page_config(page_title="Rabbit Reward Chatbot", layout="wide")

# --- Constants ---
BACKEND_URL = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000/chat")
USER_ID = "streamlit_user_01"
REQUEST_TIMEOUT = 180
CAPTION_FONT_SIZE_PX = 16

# --- Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- UI Title ---
st.title("🐰 Rabbit Reward Chatbot")
st.caption("Ask me anything about the Rabbit Rewards program!")

# --- Session State Initialization ---
if "messages" not in st.session_state:
    st.session_state.messages = []
if "last_debug_info" not in st.session_state:
    st.session_state.last_debug_info = None

# --- Helper Function for Rendering ---
def render_assistant_message(content: str):
    """
    Parses the assistant's message to render text and centered images with large captions.
    Looks for blocks like: <img-name>path/to/img.jpg</img-name><caption>A caption.</caption>
    """
    pattern = re.compile(r"<img-name>(.*?)</img-name><caption>(.*?)</caption>", re.DOTALL)
    
    last_end = 0
    found_block = False

    for match in pattern.finditer(content):
        found_block = True
        pre_text = content[last_end:match.start()]
        if pre_text.strip():
            st.markdown(pre_text.strip())

        image_path = match.group(1).strip().replace(".jpg", ".png")  # Ensure .png extension
        caption_text = match.group(2).strip()

        # Use columns to center the image and caption block
        col1, col2, col3 = st.columns([1, 2, 1])

        with col2:
            if os.path.exists(image_path):
                st.image(image_path, caption = caption_text)
                # --- CHANGE HERE: Use <center> tag for robust centering ---
                # st.markdown(
                #     f'<center><p style="font-size: {CAPTION_FONT_SIZE_PX}px;">{caption_text}</p></center>',
                #     unsafe_allow_html=True
                # )
            else:
                st.error(f"⚠️ Image not found at path: `{image_path}`")
                # --- CHANGE HERE: Also center the error caption ---
                # st.markdown(
                #     f'<center><p style="font-size: {CAPTION_FONT_SIZE_PX}px;">(Image not found) {caption_text}</p></center>',
                #     unsafe_allow_html=True
                # )

        last_end = match.end()

    remaining_text = content[last_end:]
    if remaining_text.strip():
        st.markdown(remaining_text.strip())

    # if not found_block:
    #     st.markdown(content)


# --- Sidebar ---
with st.sidebar:
    st.title("⚙️ Controls & Info")
    if st.button("🧹 Clear Chat History"):
        st.session_state.messages = []
        st.session_state.last_debug_info = None
        logger.info("Chat history cleared.")
        st.rerun()

    st.title("🐞 Debug Info")
    if st.session_state.last_debug_info:
        with st.expander("Show/Hide Last Debug Info", expanded=False):
            st.json(st.session_state.last_debug_info)
    else:
        st.markdown("`No debug info available.`")


# --- Display Chat History ---
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        content = str(message.get("content", ""))
        if message["role"] == "assistant":
            render_assistant_message(content)
        else:
            st.markdown(content)


# --- Chat Input and Processing ---
if prompt := st.chat_input("Ask about Rabbit Rewards..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    history_for_api = [
        {"role": msg["role"], "content": str(msg.get("content", ""))}
        for msg in st.session_state.messages[:-1]
    ]
    payload = {
        "user_id": USER_ID,
        "history": history_for_api,
        "message": prompt,
    }
    logger.info("Sending payload to backend.")

    with st.chat_message("assistant"):
        response_placeholder = st.empty()
        response_placeholder.markdown("Thinking... 🤔")

        assistant_reply_content = ""
        final_debug_info = {}

        try:
            with requests.post(BACKEND_URL, json=payload, timeout=REQUEST_TIMEOUT, stream=True) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()

                if "text/plain" in content_type:
                    final_debug_info = {
                        "response_type": "streaming",
                        "rag_decision_from_header": response.headers.get("X-RAG-Decision"),
                        "final_stage_from_header": response.headers.get("X-Final-Stage"),
                    }
                    buffer = ""
                    for chunk in response.iter_content(chunk_size=512, decode_unicode=True):
                        if chunk:
                            buffer += chunk
                            response_placeholder.markdown(buffer + "▌")
                    assistant_reply_content = buffer

                elif "application/json" in content_type:
                    api_response_json = response.json()
                    assistant_reply_content = api_response_json.get("reply", "Error: No reply in JSON.")
                    final_debug_info = api_response_json.get("debug_info", {})
                    final_debug_info["response_type"] = "json"
                
                else:
                    raise ValueError(f"Unexpected Content-Type from server: {content_type}")

        except requests.exceptions.RequestException as e:
            error_detail = str(e)
            if e.response:
                try: error_detail = e.response.json()
                except json.JSONDecodeError: error_detail = e.response.text
            assistant_reply_content = f"Error communicating with backend.\n```\n{error_detail}\n```"
            final_debug_info = {"error": "RequestException", "details": str(error_detail)}
        
        except Exception as e:
             assistant_reply_content = f"An unexpected error occurred: {e}"
             final_debug_info = {"error": "Frontend Error", "details": traceback.format_exc()}
        
        finally:
            st.session_state.last_debug_info = final_debug_info
            st.session_state.messages.append({"role": "assistant", "content": assistant_reply_content})
            st.rerun()