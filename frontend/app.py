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
# imogi from picture
BOT_AVATAR_EMOJI = "asset/rabbit-logo.png"
USER_AVATAR_EMOJI = "🧑‍💻"

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
# --- Helper Function for Rendering ---
def render_assistant_message(content: str):
    """
    Parses the assistant's message to render text and centered images.
    Handles images both with and without captions.
    - With caption: <img-name>path.jpg</img-name><caption>A caption.</caption>
    - Without caption: <img-name>path.jpg</img-name>
    """
    # This single regex finds an image tag and OPTIONALLY a caption tag that follows it.
    # The (?:...)? makes the caption group non-capturing and optional.
    content = content.replace(".jpg",".png")  # Ensure all images are in PNG format for consistency
    pattern = re.compile(r"<img-name>(.*?)</img-name>(?:<caption>(.*?)</caption>)?", re.DOTALL)
    
    last_end = 0
    found_block = False

    for match in pattern.finditer(content):
        found_block = True
        # Render any text that appeared before this image/caption block
        pre_text = content[last_end:match.start()]
        if pre_text.strip():
            st.markdown(pre_text.strip())

        # Group 1 will always be the image path
        image_path = match.group(1).strip()
        # image_path = os.path.join("./app",image_path) # Assuming images are stored in an 'images' directory
        print(image_path)
        # Group 2 is the caption. It will be None if the <caption> tag was not present.
        caption_text = match.group(2)
        
        # Safely handle the caption text
        if caption_text:
            caption_text = caption_text.strip()
        else:
            caption_text = "" # Default to an empty string if no caption

        # Use columns to center the image and its optional caption
        col1, col2, col3 = st.columns([1, 2, 1])

        with col2:
            if os.path.exists(image_path):
                # st.image handles an empty caption string gracefully
                st.image(image_path, caption=caption_text)
            else:
                st.error(f"⚠️ Image not found at path: `{image_path}`")
                # Still show the caption text if it exists, even if the image is missing
                if caption_text:
                    st.caption(f"(Image not found) {caption_text}")
        
        # Update the position for the next part of the string
        last_end = match.end()

    # Render any remaining text after the last block
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
    avatar = USER_AVATAR_EMOJI if message["role"] == "user" else BOT_AVATAR_EMOJI
    with st.chat_message(message["role"], avatar=avatar):
        content = str(message.get("content", ""))
        if message["role"] == "assistant":
            render_assistant_message(content)
        else:
            st.markdown(content)


# --- Chat Input and Processing ---
if prompt := st.chat_input("Ask about Rabbit Rewards..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    lang = detect_thai_or_english(prompt)
    if lang == 'th':
        think_message = "รอสักครู่นะคะ กำลังหาคำตอบให้ค่าาา🥕..."
    else:
        think_message = "Please wait a moment, I’m looking for the answer 🥕..."
    with st.chat_message("user", avatar=USER_AVATAR_EMOJI):
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

    with st.chat_message("assistant", avatar=BOT_AVATAR_EMOJI):
        response_placeholder = st.empty()
        response_placeholder.markdown(think_message)

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