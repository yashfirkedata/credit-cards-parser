import imaplib
import email
from email.header import decode_header
from bs4 import BeautifulSoup
import re # For stripping subject prefixes and other regex needs
import datetime # For potential date constraints in IMAP query
import logging

# Assuming these are in the same directory or correctly pathed
from . import config
from . import password_utils
from . import pdf_utils
from . import text_parser # This now uses Gemini

# Configure logging
# Using a specific logger for this module
logger = logging.getLogger(__name__)

# You should have get_decoded_header() and strip_subject_prefixes() in this file as well.
# For completeness, I'll re-include strip_subject_prefixes if it's not already assumed present from prior "changed code" instruction.

def get_decoded_header(header_value):
    """Decodes email header values."""
    if not header_value:
        return ""
    decoded_parts = []
    for part, charset in decode_header(header_value):
        if isinstance(part, bytes):
            decoded_parts.append(part.decode(charset or 'utf-8', errors='ignore'))
        else:
            decoded_parts.append(part)
    return "".join(decoded_parts)

def strip_subject_prefixes(subject: str) -> str:
    """Strips common prefixes like Fwd:, Re: from email subjects."""
    if not subject:
        return ""
    # logger.debug(f"Original subject for prefix stripping: {subject}") # Optional: for very detailed debugging
    normalized_subject = subject.lower() # Work with lowercase for prefix matching
    for prefix in config.SUBJECT_PREFIXES_TO_STRIP: # Assumes SUBJECT_PREFIXES_TO_STRIP is in config.py
        if normalized_subject.startswith(prefix):
            # Strip prefix and any leading spaces after it
            normalized_subject = normalized_subject[len(prefix):].lstrip()
            # logger.debug(f"Stripped prefix '{prefix}', new subject: {normalized_subject}") # Optional
    return normalized_subject


def process_emails(user_pii: dict):
    """
    Connects to IMAP, fetches credit card emails, and processes them.
    Prioritizes email body for details; checks PDFs if body is insufficient.
    Uses Gemini for parsing text content.
    user_pii: dict containing full_name, dob, mobile_number, credit_card_number
    """
    logger.info(f"Starting email processing for user: {user_pii.get('full_name', 'Unknown User')}")
    all_extracted_data = []

    if not config.IMAP_USER or not config.IMAP_PASSWORD:
        logger.error("IMAP User/Password not configured. Aborting email processing.")
        return {"error": "IMAP User/Password not configured."}
    if not config.GEMINI_API_KEY:
        logger.warning("Gemini API Key not configured. Text parsing might fail or be limited.")
        # Depending on desired behavior, you could return an error or try to proceed without Gemini (if a fallback existed)
        # For now, text_parser.extract_financial_details will return {} if key is missing.

    try:
        logger.info(f"Attempting to connect to IMAP host: {config.IMAP_HOST} on port {config.IMAP_PORT}")
        mail = imaplib.IMAP4_SSL(config.IMAP_HOST, config.IMAP_PORT)
        mail.login(config.IMAP_USER, config.IMAP_PASSWORD)
        mail.select("inbox") # Select the inbox
        logger.info("Successfully connected to Gmail inbox and selected 'inbox'.")

        # --- Preliminary Email Listing (Debugging Step) ---
        logger.info("Attempting to list recent emails in inbox for debugging...")
        try:
            status_all, data_all = mail.search(None, 'ALL')
            if status_all == "OK" and data_all[0]:
                email_ids_all = data_all[0].split()
                logger.info(f"Found a total of {len(email_ids_all)} emails in the inbox.")
                
                # Log details for a limited number of recent emails - now changed to 3
                num_emails_to_log_debug = min(len(email_ids_all), 3) # Log up to 3 latest emails
                if num_emails_to_log_debug > 0:
                    logger.info(f"Logging Subject, From, Date for the latest {num_emails_to_log_debug} emails:")
                
                    for email_id_debug_bytes in reversed(email_ids_all[-num_emails_to_log_debug:]): # Iterates latest num_emails_to_log_debug
                        email_id_debug_str = email_id_debug_bytes.decode()
                        # Fetch only headers to be quick
                        status_fetch_debug, msg_data_debug = mail.fetch(email_id_debug_bytes, '(BODY[HEADER.FIELDS (SUBJECT FROM DATE)])')
                        if status_fetch_debug == "OK" and msg_data_debug and msg_data_debug[0] is not None:
                            header_bytes = None
                            for response_part_debug in msg_data_debug:
                                if isinstance(response_part_debug, tuple) and len(response_part_debug) == 2 and isinstance(response_part_debug[1], bytes):
                                    header_bytes = response_part_debug[1]
                                    break
                            
                            if header_bytes:
                                header_msg = email.message_from_bytes(header_bytes)
                                subject_debug = get_decoded_header(header_msg['subject'])
                                from_debug = get_decoded_header(header_msg['from'])
                                date_debug = get_decoded_header(header_msg['date'])
                                logger.info(f"  ID: {email_id_debug_str}, Date: [{date_debug}], From: [{from_debug}], Subject: [{subject_debug}]")
                            else:
                                logger.warning(f"  Could not extract header bytes for email ID: {email_id_debug_str}")
                        else:
                            logger.warning(f"  Failed to fetch headers for email ID: {email_id_debug_str}, Status: {status_fetch_debug}")
                elif len(email_ids_all) > 0 : # emails exist, but num_emails_to_log_debug ended up 0 (shouldn't happen with min(len,3) unless len is 0)
                     logger.info("Found emails in inbox, but configured to log 0 recent emails for debug.")
                # If email_ids_all is empty, the outer if status_all == "OK" and data_all[0] handles it.
            elif status_all == "OK": # but data_all[0] was empty
                logger.info("No emails found in the inbox during preliminary check.")
            else:
                logger.warning(f"Preliminary 'ALL' email search failed with status: {status_all}")
        except Exception as e_debug:
            logger.error(f"Error during preliminary email listing: {e_debug}", exc_info=True)
        logger.info("--- End of Preliminary Email Listing ---")
        # --- End of Debugging Step ---

        # Build search query - MODIFIED TO ONLY USE SUBJECT KEYWORDS FOR NOW
        subject_search_terms = []
        for keyword in config.CREDIT_CARD_SUBJECT_KEYWORDS:
            subject_search_terms.append(f'SUBJECT "{keyword}"')
        
        # sender_search_terms = [] # Temporarily disabling sender search for debugging
        # for sender_keyword in config.CREDIT_CARD_EMAIL_SENDERS:
        #     sender_search_terms.append(f'FROM "{sender_keyword}"')

        # all_search_terms = subject_search_terms + sender_search_terms
        all_search_terms = subject_search_terms # Using only subject terms

        if not all_search_terms:
            # Fallback if no specific keywords are configured
            query = '(OR SUBJECT "statement" SUBJECT "e-statement")' # Default fallback
            logger.warning("No search keywords configured. Using very basic fallback query.")
        else:
            query = f"(OR {' '.join(all_search_terms)})" # Combine all terms with OR

        # Optional: Add date constraints, e.g., SENTSINCE "01-Jan-2024"
        # Example: search emails from the last 90 days
        # from_date = (datetime.date.today() - datetime.timedelta(days=90)).strftime("%d-%b-%Y")
        # query = f'(SENTSINCE "{from_date}" {query})'
        # logger.info(f"Final IMAP search query (with date constraint if active): {query}")

        logger.info(f"Using IMAP search query: {query}")
        status, data = mail.search(None, query)
        # For debugging if no emails are found with specific query:
        # status, data = mail.search(None, 'ALL') # BE CAREFUL: fetches ALL emails in the selected mailbox

        if status != "OK":
            logger.error(f"IMAP search command failed with status: {status}. Query was: {query}")
            mail.logout()
            return {"error": f"IMAP search failed: {status}"}
        
        if not data[0]: # No email IDs returned
            logger.info("No emails found matching criteria.")
            mail.logout()
            return []

        email_ids = data[0].split()
        logger.info(f"Found {len(email_ids)} email(s) potentially matching criteria.")

        logger.info("Generating potential passwords for PDF decryption.")
        potential_passwords = password_utils.generate_potential_passwords(
            user_pii["full_name"],
            user_pii["dob"],
            user_pii["mobile_number"],
            user_pii["credit_card_number"]
        )
        # logger.debug(f"Generated {len(potential_passwords)} potential passwords.") # Avoid logging actual passwords

        # Process a limited number of recent emails to avoid excessive processing time/cost
        # Reversed to get latest first, and limit to, e.g., latest 10 relevant emails found
        emails_to_process_count = min(len(email_ids), config.MAX_EMAILS_TO_PROCESS_PER_RUN) # Using config for limit
        logger.info(f"Will attempt to process the latest {emails_to_process_count} matching emails out of {len(email_ids)} found.")

        for email_id in reversed(email_ids[-emails_to_process_count:]):
            email_id_str = email_id.decode()
            logger.info(f"Fetching email ID: {email_id_str}")
            current_email_data = {
                "id": email_id_str,
                "subject": "", "from": "", "date": "",
                "details": {}, "source": "unknown"
            }
            
            status, msg_data = mail.fetch(email_id, "(RFC822)") # RFC822 fetches full email
            if status != "OK":
                logger.warning(f"Error fetching email ID {email_id_str}: Status {status}. Skipping.")
                continue

            if not msg_data or msg_data[0] is None : # Handle cases where msg_data might be empty or [None]
                logger.warning(f"No data returned for email ID {email_id_str}. Skipping.")
                continue

            # Ensure response_part is a tuple containing the email data
            # msg_data typically looks like [(b'1 (RFC822 {size}\', email_bytes), b\')\']
            # We need the email_bytes part.
            email_content_bytes = None
            for response_part in msg_data:
                if isinstance(response_part, tuple) and len(response_part) == 2 and isinstance(response_part[1], bytes):
                    email_content_bytes = response_part[1]
                    break # Found the email content

            if not email_content_bytes:
                logger.warning(f"Could not extract email content bytes for email ID {email_id_str}. Skipping.")
                continue
                
            msg = email.message_from_bytes(email_content_bytes)
            
            original_subject = get_decoded_header(msg["subject"])
            current_email_data["subject"] = original_subject
            current_email_data["from"] = get_decoded_header(msg["from"]) # This is the immediate sender
            current_email_data["date"] = get_decoded_header(msg["date"])
            
            logger.info(f"Processing email: ID={email_id_str}, Subject='{original_subject}', From='{current_email_data['from']}'")

            body_details_extracted = {}
            essential_details_in_body = False
            email_body_full_text = "" # Collect all text parts for Gemini

            # 1. Extract Text from Email Body (Plain Text and HTML)
            logger.debug(f"Extracting text from body of email ID {email_id_str}")
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    # Default content_disposition to empty string if header is missing
                    content_disposition = str(part.get("Content-Disposition", "")).lower()

                    if "attachment" not in content_disposition: # Process non-attachment parts
                        charset = part.get_content_charset() or 'utf-8' # Default charset
                        payload = part.get_payload(decode=True) # Decode base64 or quoted-printable
                        try:
                            if payload: # Ensure payload is not None
                                part_text = payload.decode(charset, errors='replace') # Handle decoding errors
                                if content_type == "text/plain":
                                    email_body_full_text += part_text + "\n\n"
                                elif content_type == "text/html":
                                    soup = BeautifulSoup(part_text, "html.parser")
                                    # Extract text, ensure good separation for Gemini
                                    email_body_full_text += soup.get_text(separator="\n", strip=True) + "\n\n"
                        except (UnicodeDecodeError, AttributeError, TypeError) as e: # Added TypeError for safety
                            logger.warning(f"Could not decode/process part (Content-Type: {content_type}) for email ID {email_id_str}: {e}")
                            continue # Skip part if decoding fails
            else: # Not multipart (simple email)
                charset = msg.get_content_charset() or 'utf-8'
                payload = msg.get_payload(decode=True)
                try:
                    if payload:
                        part_text = payload.decode(charset, errors='replace')
                        email_body_full_text = part_text
                except (UnicodeDecodeError, AttributeError, TypeError) as e:
                        logger.warning(f"Could not decode non-multipart body for email ID {email_id_str}: {e}")
            
            # Send collected body text to Gemini (text_parser)
            if email_body_full_text.strip(): # Check if any text was collected
                logger.info(f"Attempting to extract details from email body (ID: {email_id_str}) using text_parser (Gemini)...")
                body_details_extracted = text_parser.extract_financial_details(email_body_full_text)
                if body_details_extracted:
                    logger.info(f"Gemini extracted details from email body (ID: {email_id_str}): {body_details_extracted}")
                    current_email_data["details"].update(body_details_extracted)
                    current_email_data["source"] = "email_body_gemini" # Indicate source
                    # Check for essential details based on what Gemini might return (non-null values)
                    if body_details_extracted.get("total_amount_due") is not None and \
                        body_details_extracted.get("minimum_amount_due") is not None:
                        essential_details_in_body = True
                        logger.info(f"Essential details (total & min due) found in email body (ID: {email_id_str}) by Gemini.")
                    else:
                        logger.info(f"Gemini extracted some details from body (ID: {email_id_str}), but essential ones (total/min due) might be missing or null.")
                else:
                    logger.info(f"Gemini found no financial details in email body (ID: {email_id_str}) or returned empty/error from text_parser.")
            else:
                logger.info(f"Email body (ID: {email_id_str}) is empty or could not be read to send to Gemini.")


            # 2. Check PDF Attachments if essential details not found or incomplete in body
            if not essential_details_in_body:
                logger.info(f"Essential details not in body or incomplete for email ID {email_id_str}. Checking PDF attachments...")
                if msg.is_multipart(): # Iterate parts again for attachments
                    for part in msg.walk():
                        content_disposition = str(part.get("Content-Disposition", "")).lower()
                        filename_header = part.get_filename() # Returns filename if present in Content-Disposition
                        
                        if ("attachment" in content_disposition or filename_header) and filename_header:
                            filename = get_decoded_header(filename_header)
                            if filename.lower().endswith(".pdf"):
                                logger.info(f"Found PDF attachment: {filename} in email ID {email_id_str}")
                                pdf_bytes = part.get_payload(decode=True)
                                if not pdf_bytes:
                                    logger.warning(f"Attachment '{filename}' (email ID {email_id_str}) has no content. Skipping.")
                                    continue
                                    
                                # pdf_utils.extract_text_from_pdf handles decryption
                                logger.info(f"Extracting text from PDF: {filename} (email ID {email_id_str})")
                                pdf_text_content = pdf_utils.extract_text_from_pdf(pdf_bytes, potential_passwords)
                                if pdf_text_content and pdf_text_content.strip():
                                    logger.info(f"Attempting to extract details from PDF '{filename}' (email ID {email_id_str}) using text_parser (Gemini)...")
                                    pdf_details = text_parser.extract_financial_details(pdf_text_content)
                                    if pdf_details:
                                        logger.info(f"Gemini extracted details from PDF '{filename}' (email ID {email_id_str}): {pdf_details}")
                                        # Card verification logic (check if Gemini returns card_last_4_digits)
                                        statement_card_last4 = str(pdf_details.get("card_last_4_digits", "")).strip()
                                        user_card_last4 = user_pii["credit_card_number"][-4:] if user_pii["credit_card_number"] and len(user_pii["credit_card_number"]) >=4 else None

                                        if user_card_last4 and statement_card_last4 and statement_card_last4 == user_card_last4:
                                            logger.info(f"PDF card ({statement_card_last4}) matches user card for PDF '{filename}'. Updating details from PDF.")
                                            current_email_data["details"].update(pdf_details) # PDF details take precedence
                                            current_email_data["source"] = f"pdf_{filename}_gemini"
                                        elif not user_card_last4 or not statement_card_last4 : # Card info missing for validation
                                            logger.info(f"Card number not fully available for PDF validation (PDF: '{statement_card_last4}', User: '{user_card_last4}') for PDF '{filename}'. Adding details from PDF cautiously.")
                                            current_email_data["details"].update(pdf_details)
                                            current_email_data["source"] = f"pdf_{filename}_gemini_card_unverified"
                                        else: # Mismatch
                                            logger.warning(f"Card in PDF '{filename}' ({statement_card_last4}) does NOT match user's card ({user_card_last4}). Skipping these PDF details.")
                                    else:
                                            logger.info(f"Gemini found no financial details in PDF: {filename} (email ID {email_id_str}) or returned empty/error from text_parser.")
                                else:
                                    logger.info(f"No text could be extracted from PDF: {filename} (email ID {email_id_str}) (possibly image-based or decryption failed).")
                                
                                # Check if essential details are now present after this PDF
                                if current_email_data["details"].get("total_amount_due") is not None and \
                                    current_email_data["details"].get("minimum_amount_due") is not None:
                                    logger.info(f"✅ Essential details now found after processing PDF: {filename}")
                                    # Optionally break from attachment loop if primary PDF found and processed
                                    break # Stop processing more PDFs for this email
            else:
                logger.info("✅ Skipping PDF check as essential details were already found in email body by Gemini.")
            
            # Only add to results if some financial details were actually extracted AND essential fields are present
            # This condition can be adjusted based on what constitutes a "useful" extraction.
            if current_email_data["details"] and \
               current_email_data["details"].get("total_amount_due") is not None and \
               current_email_data["details"].get("minimum_amount_due") is not None:
                all_extracted_data.append(current_email_data)
            elif current_email_data["details"]: # Some details found but not all essential ones
                 logger.info(f"⚠️ Email {current_email_data['id']} processed, but essential financial details (total/min due) seem incomplete. Details: {current_email_data['details']}")
                 # Decide whether to append such partial results or not. For now, not appending if essentials are missing.


        mail.logout()
        logger.info(f"✅ IMAP connection closed. Processed {len(all_extracted_data)} emails with relevant details.")
        return all_extracted_data

    except imaplib.IMAP4.error as e:
        logger.error(f"❌ IMAP Error: {e}")
        # In a real app, you might want to try to logout even on error if mail object exists
        # if 'mail' in locals() and mail.state == 'SELECTED':
        # try: mail.logout()
        # except: pass
        return {"error": f"IMAP Error: {str(e)}"}
    except Exception as e:
        import traceback
        logger.error(f"❌ An unexpected error occurred in email_processor: {e}\n{traceback.format_exc()}")
        return {"error": f"An unexpected error occurred: {str(e)}"}