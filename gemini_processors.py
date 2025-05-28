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
    """
    Summarizes text using the Gemini API, aiming for a length
    approximately 1/5th of the input text's estimated token count,
    with an upper limit for the summary.
    """
    if not text:
        return "Error: No text provided for summarization."

    try:
        # Estimate input tokens (1 token ~ 4 characters, a common heuristic)
        # For more accuracy, you can use model.count_tokens(text) if you make an extra call
        # or if the 'text' is small enough to not worry about the overhead.
        # However, making count_tokens call here for every summarization might add latency/cost.
        # Using heuristic for now.
        estimated_input_tokens = len(text) / 4 
        
        # Calculate target summary tokens: 1/5th of input, capped at 7000
        target_summary_tokens = min(estimated_input_tokens / 5, 7000)
        
        # Convert target tokens to an approximate word count for a more natural prompt
        # (e.g., 1 token ~ 0.75 words, so 100 tokens ~ 75 words)
        target_summary_words = int(target_summary_tokens * 0.75)
        
        # Ensure a minimum word count for the prompt, e.g., if 1/5th is too small
        if target_summary_words < 50: # If 1/5th is very small, ask for at least a brief summary
            summary_length_instruction = "Provide a brief, concise summary."
        else:
            summary_length_instruction = f"Provide a detailed summary that is approximately {target_summary_words} words long. Do not exceed this length significantly."

        model = genai.GenerativeModel('gemini-1.5-flash') # Or 'gemini-pro'
        
        prompt = f"""Please summarize the following text.
Focus on the key points and main ideas.
{summary_length_instruction}

Text to Summarize:
---
{text}
---

Summary:
"""
        # Note: Controlling exact output length with LLMs via prompt is an instruction,
        # not a hard constraint. The model will try to adhere to it.
        # For hard limits, you would typically truncate the response, but that can cut off sentences.
        # The 'gemini-1.5-flash' model has an output token limit of 8192.
        # Our 7000 token target for summary (approx 5250 words) is well within this.

        logger.info(f"Sending text (length: {len(text)}, est. tokens: {estimated_input_tokens:.0f}) to Gemini for summarization. Target words: ~{target_summary_words}")
        
        response = model.generate_content(prompt)
        
        if response.prompt_feedback.block_reason:
            reason = response.prompt_feedback.block_reason
            logger.warning(f"Gemini summarization blocked due to safety concerns: {reason}")
            return f"Error: Gemini API blocked the request due to safety concerns ({reason})."

        # Check if parts are empty or if text is not directly available
        if not response.parts:
            logger.warning("Gemini response has no parts.")
            return "Error: Gemini summarization returned an empty response (no parts)."
        
        try:
            summary = response.text # This is the recommended way to get text
        except ValueError: # Handles cases where response.text might raise an error if content is blocked/empty
            logger.warning("Gemini response.text could not be accessed. Checking parts directly.")
            # Fallback to iterating parts if .text fails (though usually .text is robust)
            summary_parts = [part.text for part in response.parts if hasattr(part, 'text')]
            if not summary_parts:
                 return "Error: Gemini summarization returned no usable text content."
            summary = "".join(summary_parts)


        logger.info("Gemini summarization successful.")
        return summary.strip()
        
    except Exception as e:
        logger.error(f"Gemini API error during summarization: {e}", exc_info=True)
        # Attempt to check response.prompt_feedback even in exceptions if response object might exist
        # This part might be tricky depending on when the exception occurs.
        # For now, we'll rely on the explicit check after generate_content.
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