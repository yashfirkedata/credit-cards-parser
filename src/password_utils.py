from datetime import datetime # Make sure this import is present
import logging

logger = logging.getLogger(__name__)

def generate_potential_passwords(full_name: str, dob_str: str, mobile_number: str, credit_card_number: str) -> list[str]:
    """
    Generates a list of potential passwords for PDF statements based on user details.
    Includes HDFC specific patterns.
    """
    logger.info("Starting generation of potential passwords.")
    passwords = set()

    if not full_name or not dob_str : # credit_card_number might not always be needed for all patterns
        logger.warning("Full name or DOB missing, password generation will be limited.")
        # Decide if to return early or proceed with available info

    name_parts = full_name.lower().split()
    first_name_lower = name_parts[0] if name_parts else ""
    
    # For "first four letters embossed on Credit Card" - assumption: first 4 of first name, uppercase
    # This might need to be an explicit input "name_on_card" for better accuracy.
    name_on_card_first_four_upper = first_name_lower[:4].upper() if first_name_lower else ""
    logger.debug(f"Name on card first four (assumed): {name_on_card_first_four_upper}")

    day, month, year_yy, year_yyyy, dob_ddmm = "", "", "", "", ""
    try:
        dob_date = datetime.strptime(dob_str, "%Y-%m-%d")
        day = dob_date.strftime("%d")
        month = dob_date.strftime("%m")
        year_yy = dob_date.strftime("%y")
        year_yyyy = dob_date.strftime("%Y")
        dob_ddmm = f"{day}{month}" # DDMM format for HDFC
        logger.debug(f"DOB components: day={day}, month={month}, year_yy={year_yy}, year_yyyy={year_yyyy}, dob_ddmm={dob_ddmm}")
    except ValueError:
        logger.warning(f"Invalid DOB format ('{dob_str}') for password generation.")


    last_four_card = ""
    # Ensure last_four_card is exactly 4 digits if that's a strict requirement for some patterns
    if credit_card_number and len(credit_card_number) >= 4:
        last_four_card = credit_card_number[-4:]
    elif credit_card_number: # card number is present but less than 4 digits
        last_four_card = credit_card_number 
    logger.debug(f"Last four digits of card: {last_four_card if last_four_card else 'N/A'}")


    # --- HDFC Specific Patterns (based on sample email) ---
    if name_on_card_first_four_upper and last_four_card: # last_four_card needs to be exactly 4 for HDFC
        if len(last_four_card) == 4:
             passwords.add(f"{name_on_card_first_four_upper}{last_four_card}")
    
    if name_on_card_first_four_upper and dob_ddmm: # dob_ddmm needs to be DDMM (4 chars)
        if len(dob_ddmm) == 4:
            passwords.add(f"{name_on_card_first_four_upper}{dob_ddmm}")
    
    # Example from forwarded message (though specific to Shubham) - illustrates a pattern
    # This specific one "SHUB2601" is too specific unless 'shubham' is the user
    # and '2601' is part of their DOB or card. But the PATTERN is: NAME_PART + DOB_PART
    # This is illustrative of how one might add very specific known passwords if available
    # if name_on_card_first_four_upper == "SHUB" and dob_ddmm == "2601":
    #      passwords.add("SHUB2601")


    # --- Generic Patterns (from previous version, can be expanded) ---
    first_four_of_name_lower = first_name_lower[:4]
    if first_four_of_name_lower:
        if day and month:
            passwords.add(f"{first_four_of_name_lower}{day}{month}")
            if year_yy:
                passwords.add(f"{first_four_of_name_lower}{day}{month}{year_yy}")
        # UPPERCASE name part
        if day and month:
             passwords.add(f"{first_four_of_name_lower.upper()}{day}{month}")


    if first_four_of_name_lower and last_four_card:
        passwords.add(f"{first_four_of_name_lower}{last_four_card}")
        passwords.add(f"{first_four_of_name_lower.upper()}{last_four_card}")

    if day and month and year_yy:
        passwords.add(f"{day}{month}{year_yy}")
    if day and month and year_yyyy:
        passwords.add(f"{day}{month}{year_yyyy}")
    
    # Remove empty strings if any were added due to missing PII parts
    passwords.discard("")

    # For security, avoid logging the actual passwords in production INFO level.
    # Log count and maybe a few examples at DEBUG level if necessary.
    logger.info(f"Generated {len(passwords)} unique potential passwords.")
    # Example: logger.debug(f"Example passwords: {list(passwords)[:3] if len(passwords) > 0 else 'None'}")
    return list(passwords)
