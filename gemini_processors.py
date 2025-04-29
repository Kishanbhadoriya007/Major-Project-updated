# Major-Project/gemini_processors.py
import os
import google.generativeai as genai
import logging
from dotenv import load_dotenv

# Load environment variables (especially GOOGLE_API_KEY)
load_dotenv()

logger = logging.getLogger(__name__)

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

def summarize_text_gemini(text: str, max_length: int = 300, min_length: int = 50) -> str:
    """Summarizes text using the Gemini API."""
    if not text:
        return "Error: No text provided for summarization."

    model = genai.GenerativeModel('gemini-1.5-flash') # Or 'gemini-pro'
    prompt = f"""Please summarize the following text. Aim for a length between {min_length} and {max_length} words.
Focus on the key points and main ideas.

Text to Summarize:
---
{text}
---

Summary:
"""
    try:
        logger.info(f"Sending text (length: {len(text)}) to Gemini for summarization...")
        response = model.generate_content(prompt)
        summary = response.text
        logger.info("Gemini summarization successful.")
        return summary.strip()
    except Exception as e:
        logger.error(f"Gemini API error during summarization: {e}", exc_info=True)
        # Provide more specific feedback if possible (check e.g., for safety blocks)
        if hasattr(response, 'prompt_feedback') and response.prompt_feedback.block_reason:
             reason = response.prompt_feedback.block_reason
             return f"Error: Gemini API blocked the request due to safety concerns ({reason})."
        return f"Error: Failed to generate summary using Gemini API. Details: {e}"

def translate_text_gemini(text: str, target_lang: str) -> str:
    """Translates text using the Gemini API (assumes English source)."""
    if not text:
        return "Error: No text provided for translation."
    if not target_lang:
        return "Error: Target language not specified."

    model = genai.GenerativeModel('gemini-1.5-flash') # Or 'gemini-pro'
    # Ensure target_lang is descriptive (e.g., "French", "Spanish")
    language_map = {
        'fr': 'French', 'es': 'Spanish', 'de': 'German', 'it': 'Italian',
        'pt': 'Portuguese', 'ru': 'Russian', 'ja': 'Japanese', 'zh': 'Chinese',
        'ar': 'Arabic'
        # Add more as needed
    }
    target_language_name = language_map.get(target_lang.lower(), target_lang) # Use full name if available

    prompt = f"""Translate the following English text into {target_language_name}.
Provide only the translation, without any introductory phrases like "Here is the translation:".

English Text:
---
{text}
---

{target_language_name} Translation:
"""
    try:
        logger.info(f"Sending text (length: {len(text)}) to Gemini for translation to {target_language_name}...")
        response = model.generate_content(prompt)
        translation = response.text
        logger.info("Gemini translation successful.")
        return translation.strip()
    except Exception as e:
        logger.error(f"Gemini API error during translation: {e}", exc_info=True)
        if hasattr(response, 'prompt_feedback') and response.prompt_feedback.block_reason:
             reason = response.prompt_feedback.block_reason
             return f"Error: Gemini API blocked the request due to safety concerns ({reason})."
        return f"Error: Failed to generate translation using Gemini API. Details: {e}"