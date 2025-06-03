import os
from dotenv import load_dotenv

load_dotenv()

IMAP_USER = os.getenv("IMAP_USER")
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD")
IMAP_HOST = os.getenv("IMAP_HOST", "imap.gmail.com")
IMAP_PORT = int(os.getenv("IMAP_PORT", 993))

# Gemini API Key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Keywords to identify credit card statement emails
# These are more general now, specific bank names can also be added
CREDIT_CARD_SUBJECT_KEYWORDS = [
    "credit card statement",
    "e-statement",
    "card statement",
    "monthly statement",
    "hdfc bank", # Added from example
    "diners club"  # Added from example
]
CREDIT_CARD_EMAIL_SENDERS = [
    "statement@examplebank.com",
    "noreply@creditcard.examplebank.com",
    "hdfcbank.com", # Domain for HDFC
    "hdfc bank" # Common display name part
    # Add more known senders or domains
]

# Email subject prefixes to strip before matching keywords
SUBJECT_PREFIXES_TO_STRIP = ["fwd:", "re:", "fw:"]