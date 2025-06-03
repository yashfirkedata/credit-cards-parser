import io
import PyPDF2
import logging

logger = logging.getLogger(__name__)

def extract_text_from_pdf(pdf_bytes: bytes, potential_passwords: list[str]) -> str | None:
    """
    Tries to open an encrypted PDF with a list of potential passwords and extract text.
    """
    pdf_file = io.BytesIO(pdf_bytes)
    logger.info("Attempting to extract text from PDF.")
    try:
        reader = PyPDF2.PdfReader(pdf_file)
        if reader.is_encrypted:
            logger.info("PDF is encrypted. Attempting decryption with provided passwords.")
            for i, password in enumerate(potential_passwords):
                # Log only a masked version or count of passwords for security if needed
                # logger.debug(f"Attempting PDF decryption with password #{i+1}")
                try:
                    if reader.decrypt(password):
                        text = ""
                        for page_num, page in enumerate(reader.pages):
                            page_text = page.extract_text()
                            if page_text:
                                text += page_text
                            else:
                                logger.debug(f"No text extracted from page {page_num + 1} of decrypted PDF.")
                        logger.info(f"PDF decrypted successfully with password #{i+1}.") # Avoid logging the actual password
                        return text
                    # else:
                        # logger.debug(f"Attempted password #{i+1} - failed (decrypt returned 0)")
                except Exception as e:
                    logger.debug(f"Attempt with password #{i+1} failed: {e}")
                    pass # PyPDF2 can raise various errors on wrong password
            logger.warning("Failed to decrypt PDF with all potential passwords.")
            return None
        else:
            text = ""
            for page_num, page in enumerate(reader.pages):
                page_text = page.extract_text()
                if page_text:
                    text += page_text
                else:
                    logger.debug(f"No text extracted from page {page_num + 1} of unencrypted PDF.")
            logger.info("PDF is not encrypted. Extracted text.")
            return text
    except PyPDF2.errors.PdfReadError as e:
        logger.error(f"Error reading PDF: {e}. It might be corrupted or not a PDF.", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred while processing PDF: {e}", exc_info=True)
        return None