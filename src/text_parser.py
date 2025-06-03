import google.generativeai as genai
import json
import re
import logging
from . import config # For API Key

# Configure logging
logger = logging.getLogger(__name__)

def format_extracted_amount(amount_str):
    """
    Cleans and converts an amount string to a float.
    Removes currency symbols, commas, and handles potential conversion errors.
    """
    if isinstance(amount_str, (int, float)):
        return float(amount_str) # Already numeric
    if isinstance(amount_str, str):
        # Remove common currency symbols (₹, $, €, £, Rs.), commas, and whitespace
        cleaned_str = re.sub(r"[₹$€£Rs\.,\s]", "", amount_str).strip()
        # Some statements might use a hyphen for credit balances, handle if necessary
        # For now, assuming positive amounts or amounts Gemini can interpret directly.
        try:
            return float(cleaned_str)
        except ValueError:
            # Fallback for strings that don't look like typical numbers but might be (e.g. "5000" vs "5,000.00")
            # Try removing only non-numeric/non-decimal point characters if initial aggressive cleaning failed
            # This is a bit more experimental
            less_cleaned_str = re.sub(r"[^\d\.]", "", amount_str).strip()
            if less_cleaned_str:
                try:
                    return float(less_cleaned_str)
                except ValueError:
                    pass # Still failed
            logger.warning(f"Could not convert amount string '{amount_str}' to float. Original cleaned: '{cleaned_str}'. Returning as is.")
            return amount_str # Return original problematic string if all conversions fail
    return amount_str # Return original if not string or numeric

def extract_financial_details(text_content: str) -> dict:
    """
    Extracts financial details from text using the Gemini API.
    """
    logger.info("Attempting to extract financial details from text content.")
    if not text_content or not text_content.strip():
        logger.info("Text content is empty or whitespace only. Skipping Gemini extraction.")
        return {}
    if not config.GEMINI_API_KEY:
        logger.error("Gemini API key not configured. Skipping Gemini extraction.")
        return {}

    genai.configure(api_key=config.GEMINI_API_KEY)
    # Using gemini-1.5-flash-latest for a balance of speed and capability
    model = genai.GenerativeModel('gemini-1.5-flash-latest')
    logger.debug("Gemini API configured and model loaded.")

    # Truncate text_content to avoid overly long prompts, adjust limit as needed based on typical statement length and model context window
    # A very long statement might still hit token limits for the prompt itself, not just the response.
    # Common statements are usually within a few thousand to 10k characters.
    max_prompt_text_length = 15000 # Characters, not tokens. Gemini's tokenization is different.
    truncated_text_content = text_content[:max_prompt_text_length]
    if len(text_content) > max_prompt_text_length:
        logger.info(f"Text content was truncated to {max_prompt_text_length} characters for the Gemini prompt from original {len(text_content)} characters.")


    prompt = f"""
    You are an expert financial data extractor. Your task is to meticulously analyze the provided credit card statement text and extract specific financial details.
    Return these details ONLY in a valid JSON object format. Do not include any explanatory text before or after the JSON object.

    The fields to extract are:
    - "total_amount_due": The total outstanding amount that needs to be paid. This should be a numeric value (float).
    - "minimum_amount_due": The minimum payment required. This should be a numeric value (float).
    - "due_date": The payment deadline. Format this as "DD-MM-YYYY" if possible from the input (e.g., if input is "14-Mar-2025" or "14/03/2025", output "14-03-2025"). If the format is ambiguous or different, provide it as seen.
    - "statement_date": The date the statement was generated. Format this as "DD-MM-YYYY" if possible. If the format is ambiguous or different, provide it as seen.
    - "card_last_4_digits": The last four digits of the credit card number, if visible in the statement text. This should be a string.
    - "bank_name": The name of the bank issuing the statement (e.g., "HDFC Bank", "ICICI Bank", "SBI Card"). Infer this from the text if possible.

    Guidelines for extraction:
    1.  Accuracy is paramount. If a field is not present in the text or cannot be confidently determined, set its value to `null` in the JSON or omit the key entirely.
    2.  Amounts: Ensure extracted amounts are clean numeric values (e.g., 6225.00, not "Rs. 6,225.00" or "6,225").
    3.  Dates: Prioritize "DD-MM-YYYY". If the year is not present for a due date (e.g., "14 Mar"), try to infer it if the statement date has a year, assuming it's the same year or the next if the month has passed. If inference is complex, provide as seen.
    4.  JSON Format: The entire output must be a single, valid JSON object.

    Statement Text:
    ---
    {truncated_text_content}
    ---
    Valid JSON Output ONLY:
    """

    logger.info("Sending request to Gemini API for text parsing...")
    response = None # Initialize response to None
    try:
        # GenerationConfig can be used for temperature, top_p, etc. if needed
        # generation_config = genai.types.GenerationConfig(temperature=0.1)
        response = model.generate_content(prompt) #, generation_config=generation_config)
        
        # Debug: Print the raw response from Gemini to see exactly what it sends
        # logger.debug(f"Gemini Raw Response Text:\n---\n{response.text}\n---")

        # Attempt to clean and parse the JSON from Gemini's response
        # Gemini sometimes wraps JSON in ```json ... ``` or provides other text.
        cleaned_response_text = response.text.strip()
        if cleaned_response_text.startswith("```json"):
            cleaned_response_text = cleaned_response_text[len("```json"):] # Remove ```json prefix
        elif cleaned_response_text.startswith("```"): # Handle if just ``` is used without json
             cleaned_response_text = cleaned_response_text[len("```"):]
        
        if cleaned_response_text.endswith("```"):
            cleaned_response_text = cleaned_response_text[:-len("```")] # Remove ``` suffix
        
        cleaned_response_text = cleaned_response_text.strip() # Final strip

        # If the response is empty after stripping, it's not valid JSON.
        if not cleaned_response_text:
            logger.error("Gemini response was empty after stripping markdown/whitespace.")
            if hasattr(response, 'prompt_feedback') and response.prompt_feedback:
                logger.error(f"Gemini Prompt Feedback: {response.prompt_feedback}")
            return {}

        details = json.loads(cleaned_response_text)
        logger.info("Successfully parsed JSON response from Gemini.")
        
        # Format amounts after successful JSON parsing
        if "total_amount_due" in details and details["total_amount_due"] is not None:
            details["total_amount_due"] = format_extracted_amount(details["total_amount_due"])
        if "minimum_amount_due" in details and details["minimum_amount_due"] is not None:
            details["minimum_amount_due"] = format_extracted_amount(details["minimum_amount_due"])

        logger.info(f"Details extracted by Gemini: {details}")
        return details
        
    except json.JSONDecodeError as e:
        problematic_response = "N/A"
        if response and hasattr(response, 'text'): # Check if response is not None
            problematic_response = response.text
        logger.error(f"Gemini response was not valid JSON or JSON parsing failed: {e}", exc_info=True)
        logger.error(f"Gemini problematic response fragment (up to 500 chars):\n---\n{problematic_response[:500]}\n---")
        if response and hasattr(response, 'prompt_feedback') and response.prompt_feedback: # Check if response is not None
            logger.error(f"Gemini Prompt Feedback: {response.prompt_feedback}")
        return {}
    except Exception as e:
        # This catches other errors, e.g., related to API calls, quota issues, etc.
        logger.error(f"An error occurred while calling Gemini API or processing its response: {e}", exc_info=True)
        if response and hasattr(response, 'prompt_feedback') and response.prompt_feedback: # Check if response is not None
            logger.error(f"Gemini Prompt Feedback: {response.prompt_feedback}")
        # For more detailed trace for non-API errors during this block:
        # import traceback
        # logger.error(traceback.format_exc())
        return {}