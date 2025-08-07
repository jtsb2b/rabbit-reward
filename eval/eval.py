import os
import pandas as pd
import requests
import json
import time
import logging
import ast  # Use Abstract Syntax Tree for safer string evaluation
from openai import OpenAI
from dotenv import load_dotenv
import re
# --- Configuration ---
load_dotenv(override=True)

API_BASE_URL = os.getenv("API_URL", "http://127.0.0.1:8000")
CHAT_ENDPOINT = f"{API_BASE_URL}/chat"
CSV_FILE_PATH = "/Users/jullajakkarnjanaekarin/Documents/rabbit-reward/eval/eval-rabbit.csv"  # Path to your evaluation CSV

# LLM-as-Judge Configuration
# You can use OpenAI, Gemini, or any OpenAI-compatible API endpoint
LLM_JUDGE_API_KEY = os.getenv("OPENAI_API_KEY") # e.g., your GEMINI_API_KEY or OPENAI_API_KEY
# LLM_JUDGE_BASE_URL = os.getenv("LLM_JUDGE_BASE_URL") # e.g., "https://generativelanguage.googleapis.com/v1beta/openai/"
LLM_JUDGE_MODEL = os.getenv("LLM_JUDGE_MODEL", "gpt-4o")

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- LLM Client for Judge ---
if not LLM_JUDGE_API_KEY:
    logger.warning("LLM_JUDGE_API_KEY not found. LLM-as-judge scoring will be disabled.")
    llm_client = None
else:
    llm_client = OpenAI(api_key=LLM_JUDGE_API_KEY)

# --- Helper Functions ---

def parse_history(history_str: str) -> list:
    """
    Safely parses the history string from the CSV by splitting on "ChatMessage"
    and extracting role and content with regex.
    """
    if pd.isna(history_str) or not history_str.strip() or history_str == "[]":
        return []

    try:
        history = []
        # Clean the string by removing the outer list brackets
        cleaned_str = history_str.strip()[1:-1]
        
        # Split the string into individual message components.
        # We split by the text that separates the ChatMessage objects.
        # A regex split is robust against variations in whitespace.
        message_chunks = re.split(r"\),\s*ChatMessage\(", cleaned_str)

        for chunk in message_chunks:
            # Clean up the start of the first chunk and end of the last chunk
            chunk = chunk.removeprefix("ChatMessage(").removesuffix(")")
            
            # Use re.search with re.DOTALL to handle multiline content strings
            role_match = re.search(r"role='(.*?)'", chunk, re.DOTALL)
            content_match = re.search(r"content='(.*?)'", chunk, re.DOTALL)

            if role_match and content_match:
                # group(1) captures the text inside the parentheses (.*?)
                role = role_match.group(1)
                content = content_match.group(1)
                history.append({"role": role, "content": content})
            else:
                logger.warning(f"Could not parse a history chunk: '{chunk[:100]}...'")

        return history
    except Exception as e:
        logger.error(f"Critical error parsing history string: '{history_str}'. Error: {e}")
        return []


def get_llm_judge_score(client: OpenAI, user_input: str, reference_output: str, api_output: str) -> (int, str):
    """Uses an LLM to judge the API's output against a reference."""
    if not client:
        return -1, "LLM client not initialized."
    if pd.isna(reference_output) or not str(reference_output).strip():
        return -1, "Reference (gold) answer is missing."
    if pd.isna(api_output) or not str(api_output).strip():
        return 0, "API output is missing or empty."

    prompt = f"""You are an impartial AI assistant evaluating a chatbot's response for the "Rabbit Rewards" program in Thailand.

**User's Question:**
{user_input}

**Reference (Gold Standard) Answer:**
{reference_output}

**Chatbot's Actual Response:**
{api_output}

**Evaluation Task:**
Please evaluate the Chatbot's Actual Response based on the User's Question and the Reference Answer. Consider accuracy, relevance, completeness, and helpfulness. The Reference Answer is the ideal response.

**Scoring Scale (1-5):**
1: **Very Poor.** Irrelevant, nonsensical, or contains major factual errors.
2: **Poor.** Has significant issues with relevance, accuracy, or completeness.
3: **Fair.** Partially correct or relevant but has noticeable flaws or omissions.
4: **Good.** Mostly correct, relevant, and helpful, with only minor issues.
5: **Excellent.** Highly accurate, relevant, complete, and helpful, closely matching the reference.

**Output Format:**
Provide your response as a JSON object with two keys: "score" (int) and "justification" (string).
Example: {{"score": 5, "justification": "The response is accurate and fully answers the user's question, matching the gold standard."}}
"""
    try:
        response = client.chat.completions.create(
            model=LLM_JUDGE_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        content = response.choices[0].message.content
        if content:
            judge_result = json.loads(content)
            score = int(judge_result.get("score", -1))
            justification = judge_result.get("justification", "No justification provided.")
            return score, justification
        return -1, "Empty response from LLM judge."
    except Exception as e:
        logger.error(f"Error calling LLM judge: {e}")
        return -1, f"LLM judge API call error: {e}"


# --- Main Evaluation Logic ---
def run_evaluation():
    logger.info(f"Starting evaluation using data from: {CSV_FILE_PATH}")
    logger.info(f"API Endpoint: {CHAT_ENDPOINT}")
    logger.info(f"LLM Judge Model: {LLM_JUDGE_MODEL if llm_client else 'Disabled'}")

    try:
        eval_df = pd.read_csv(CSV_FILE_PATH)
    except FileNotFoundError:
        logger.error(f"Evaluation CSV file not found at: {CSV_FILE_PATH}")
        return

    results = []
    total_cases = len(eval_df)
    classification_correct_count = 0

    for index, row in eval_df.iterrows():
        logger.info(f"--- Processing Test Case {index + 1}/{total_cases} ---")

        # Adjust column names to match your CSV
        history_str = row.get('history', '')
        user_input = row.get('user_input', '')
        ref_classification = str(row.get('ref_classification', '')).strip().lower()
        ref_output = row.get('ref_output', '')
        # print(history_str)
        # print(user_input)
        # print(ref_classification)
        # print(ref_output)
        if pd.isna(user_input):
            logger.warning(f"Skipping row {index + 1} due to missing 'Input'.")
            continue

        parsed_history = parse_history(history_str)

        payload = {
            "user_id": f"eval_user_{index + 1}",
            "history": parsed_history,
            "message": str(user_input),
        }

        api_output_content = None
        api_classification_decision = None
        api_error = None
        
        try:
            response = requests.post(CHAT_ENDPOINT, json=payload, timeout=120, stream=True)
            response.raise_for_status()

            content_type = response.headers.get("Content-Type", "").lower()

            if "text/plain" in content_type: # Streaming RAG response
                api_classification_decision = response.headers.get("X-RAG-Decision", "N/A")
                api_output_content = "".join([chunk for chunk in response.iter_content(decode_unicode=True)])
            elif "application/json" in content_type: # Non-RAG or error response
                json_response = response.json()
                api_output_content = json_response.get("reply")
                api_classification_decision = json_response.get("current_rag_decision")
            else:
                api_error = f"Unexpected Content-Type: {content_type}"

        except requests.exceptions.RequestException as e:
            api_error = f"API request failed: {e}"
        except Exception as e:
            api_error = f"An unexpected error occurred: {e}"

        if api_error:
            logger.error(api_error)

        # --- Classification Evaluation ---
        classification_match = (api_classification_decision == ref_classification)
        if classification_match:
            classification_correct_count += 1
        logger.info(f"Classification: Ref='{ref_classification}', API='{api_classification_decision}', Match={classification_match}")
        
        # --- LLM-as-Judge Evaluation ---
        llm_score, llm_justification = get_llm_judge_score(
            llm_client, user_input, ref_output, api_output_content
        )
        logger.info(f"LLM Judge: Score={llm_score}, Justification='{llm_justification}'")

        results.append({
            'test_case_id': index + 1,
            'user_input': user_input,
            'history': history_str,
            'ref_classification': ref_classification,
            'api_classification': api_classification_decision,
            'classification_match': classification_match,
            'ref_output': ref_output,
            'api_output': api_output_content,
            'llm_score': llm_score,
            'llm_justification': llm_justification,
            'api_error': api_error
        })

    # --- Aggregate and Print Results ---
    logger.info("\n--- Evaluation Summary ---")
    if total_cases > 0:
        accuracy = (classification_correct_count / total_cases) * 100
        logger.info(f"Classification Accuracy: {accuracy:.2f}% ({classification_correct_count}/{total_cases} correct)")

        scored_cases = [r for r in results if r['llm_score'] >= 1]
        if scored_cases:
            avg_score = sum(r['llm_score'] for r in scored_cases) / len(scored_cases)
            logger.info(f"Average LLM-as-Judge Score: {avg_score:.2f} (from {len(scored_cases)} cases)")
        else:
            logger.info("Average LLM-as-Judge Score: N/A (no cases were scored)")

    # --- Save detailed results ---
    results_df = pd.DataFrame(results)
    output_csv_path = "/Users/jullajakkarnjanaekarin/Documents/rabbit-reward/eval/evaluation_results.csv"
    results_df.to_csv(output_csv_path, index=False, encoding='utf-8-sig')
    logger.info(f"Detailed results saved to: {output_csv_path}")

if __name__ == "__main__":
    run_evaluation()