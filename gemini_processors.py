# Major-Project/gemini_processors.py
import os
import google.generativeai as genai
import logging
from dotenv import load_dotenv

# Load environment variables (especially GOOGLE_API_KEY)
load_dotenv()

logger = logging.getLogger(__name__)

# configure_gemini function remains the same...
def configure_gemini():
    """Configures the Gemini API key."""
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        logger.error("GOOGLE_API_KEY environment variable not set.")
        raise ValueError("Missing Google API Key. Please set the GOOGLE_API_KEY environment variable.")
    try:
        genai.configure(api_key=api_key)
        logger.info("Gemini API configured successfully.")
    except Exception as e:
        logger.error(f"Failed to configure Gemini API: {e}", exc_info=True)
        raise ConnectionError(f"Failed to configure Gemini API: {e}")

# Updated summarize function
def summarize_text_gemini(text: str) -> str:
    """Summarizes text briefly using the Gemini API."""
    if not text:
        return "Error: No text provided for summarization."

    model = genai.GenerativeModel('gemini-1.5-flash') # Or 'gemini-pro'
    prompt = f"""Please provide a brief summary of the following text.
Focus on the key points and main ideas.

Text to Summarize:
---
{text}
---

Brief Summary:
"""
    response = None # Initialize response to handle potential errors before assignment
    try:
        logger.info(f"Sending text (length: {len(text)}) to Gemini for brief summarization...")
        response = model.generate_content(prompt)
        # Check for safety blocking *after* the call
        if response.prompt_feedback.block_reason:
             reason = response.prompt_feedback.block_reason
             logger.warning(f"Gemini summarization blocked due to safety concerns: {reason}")
             return f"Error: Gemini API blocked the request due to safety concerns ({reason})."

        summary = response.text
        logger.info("Gemini summarization successful.")
        return summary.strip()
    except Exception as e:
        logger.error(f"Gemini API error during summarization: {e}", exc_info=True)
        # Check response safety feedback even in exceptions if response object exists
        if response and hasattr(response, 'prompt_feedback') and response.prompt_feedback.block_reason:
             reason = response.prompt_feedback.block_reason
             return f"Error: Gemini API blocked the request due to safety concerns ({reason}). Details: {e}"
        return f"Error: Failed to generate summary using Gemini API. Details: {e}"

# Updated translate function
def translate_text_gemini(text: str, target_language_name: str) -> str:
    """Translates text using the Gemini API, relying on auto-detection for source."""
    if not text:
        return "Error: No text provided for translation."
    if not target_language_name:
        return "Error: Target language not specified."

    model = genai.GenerativeModel('gemini-1.5-flash') # Or 'gemini-pro'

    prompt = f"""Translate the following text into {target_language_name}.
Detect the source language automatically.
Provide only the translation, without any introductory phrases like "Here is the translation:".

Text to Translate:
---
{text}
---

{target_language_name} Translation:
"""
    response = None # Initialize response
    try:
        logger.info(f"Sending text (length: {len(text)}) to Gemini for translation to {target_language_name}...")
        response = model.generate_content(prompt)
        # Check for safety blocking *after* the call
        if response.prompt_feedback.block_reason:
             reason = response.prompt_feedback.block_reason
             logger.warning(f"Gemini translation blocked due to safety concerns: {reason}")
             return f"Error: Gemini API blocked the request due to safety concerns ({reason})."

        translation = response.text
        logger.info("Gemini translation successful.")
        return translation.strip()
    except Exception as e:
        logger.error(f"Gemini API error during translation: {e}", exc_info=True)
         # Check response safety feedback even in exceptions if response object exists
        if response and hasattr(response, 'prompt_feedback') and response.prompt_feedback.block_reason:
             reason = response.prompt_feedback.block_reason
             return f"Error: Gemini API blocked the request due to safety concerns ({reason}). Details: {e}"
        return f"Error: Failed to generate translation using Gemini API. Details: {e}"