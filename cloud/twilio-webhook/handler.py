import urllib.parse
import json
import datetime

def handler(event, context):
    """
    Minimal Lambda handler for Twilio SMS webhooks.
    For now:
      - Parses x-www-form-urlencoded from Twilio
      - Logs the data
      - Returns clean 200 OK response
    """
    # --- Safety: ensure body exists
    raw_body = event.get("body", "") or ""
    
    # --- Parse Twilio form data
    parsed = urllib.parse.parse_qs(raw_body)

    # Convert parsed values from list -> single value
    parsed_simple = {k: v[0] for k, v in parsed.items()}

    # Temporary log (visible in CloudWatch)
    print("Incoming Twilio payload:", json.dumps(parsed_simple))

    # --- Build minimal response for API Gateway → Twilio
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "text/plain"},
        "body": "OK"
    }
