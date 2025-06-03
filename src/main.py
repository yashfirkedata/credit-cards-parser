from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel, Field
from typing import Dict, Any
import datetime
import logging

from . import email_processor # Use . for relative import within package
from . import config # To ensure config is loaded

app = FastAPI(title="Credit Card Statement Processor")

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class UserDetails(BaseModel):
    full_name: str = Field(..., example="Amit Sharma")
    dob: str = Field(..., example="1990-07-15", description="Date of birth in YYYY-MM-DD format")
    mobile_number: str = Field(..., example="9876543210", description="10-digit mobile number")
    credit_card_number: str = Field(..., example="1234567812345678", description="Full credit card number or at least last 4 for password generation")

    # Validator for DOB format
    @classmethod
    def validate_dob(cls, value):
        try:
            datetime.datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            raise ValueError("Invalid DOB format. Expected YYYY-MM-DD")
        return value

@app.post("/process-statements/")
async def process_credit_card_statements(user_details: UserDetails):
    """
    Processes credit card statements for the given user.
    Connects to the configured Gmail account, searches for statement emails,
    attempts to decrypt PDF attachments using generated passwords, and extracts financial details.
    """
    logger.info(f"Received request to process statements for user: {user_details.full_name}")
    # Validate DOB format explicitly (though Pydantic handles it too if using date type)
    try:
        datetime.datetime.strptime(user_details.dob, "%Y-%m-%d")
    except ValueError:
        logger.error(f"Invalid DOB format for user {user_details.full_name}: {user_details.dob}")
        raise HTTPException(status_code=400, detail="Invalid DOB format. Expected YYYY-MM-DD.")

    if not config.IMAP_USER or not config.IMAP_PASSWORD:
        logger.error("IMAP credentials not configured.")
        raise HTTPException(status_code=500, detail="IMAP credentials not configured in .env file.")

    logger.info(f"Processing request for: {user_details.full_name}, DOB: {user_details.dob}")
    
    pii_data = {
        "full_name": user_details.full_name,
        "dob": user_details.dob,
        "mobile_number": user_details.mobile_number,
        "credit_card_number": user_details.credit_card_number
    }
    
    try:
        logger.info(f"Calling email_processor for user: {user_details.full_name}")
        extracted_info = email_processor.process_emails(pii_data)
        if isinstance(extracted_info, dict) and "error" in extracted_info:
             logger.error(f"Error from email_processor for user {user_details.full_name}: {extracted_info['error']}")
             raise HTTPException(status_code=500, detail=extracted_info["error"])
        if not extracted_info:
            logger.info(f"No relevant credit card statement details found or could be processed for user: {user_details.full_name}")
            return {"message": "No relevant credit card statement details found or could be processed."}
        logger.info(f"Successfully processed statements for user: {user_details.full_name}")
        return extracted_info
    except Exception as e:
        # Catch any other unexpected errors from email_processor
        logger.exception(f"Error during statement processing for user {user_details.full_name}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {str(e)}")

@app.get("/")
async def root():
    logger.info("Root endpoint accessed.")
    return {"message": "Credit Card Statement Processor API. Use the /docs endpoint for API documentation."}

# To run the app: uvicorn src.main:app --reload
# (Run from the project root directory)