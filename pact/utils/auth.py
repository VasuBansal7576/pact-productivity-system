"""Google OAuth 2.0 authentication utilities for Pact.

Handles OAuth Web Server flow for Calendar, Gmail, Docs, and Sheets APIs.
Generates consent URLs, exchanges auth codes, and refreshes tokens.
"""

import os
import json
import logging
from pathlib import Path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

# All required OAuth scopes
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
]

# Path to token storage
TOKEN_PATH = Path(__file__).parent.parent / "token.json"
CLIENT_SECRET_PATH = Path(__file__).parent.parent / "client_secret.json"


def get_credentials() -> Credentials:
    """Get valid OAuth credentials, refreshing or re-authenticating as needed.

    Returns:
        google.oauth2.credentials.Credentials: Valid credentials with all required scopes.
    """
    creds = None

    # Load existing token
    if TOKEN_PATH.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
        except Exception as e:
            logger.warning(f"Failed to load existing token: {e}")
            creds = None

    # Refresh token if expired
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            logger.info("Token refreshed successfully")
            _save_token(creds)
        except Exception as e:
            logger.warning(f"Token refresh failed: {e}")
            creds = None

    if not creds or not creds.valid:
        # Fall back to environment variables for headless/deployed settings
        client_id = os.environ.get("GOOGLE_CLIENT_ID")
        client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
        refresh_token = os.environ.get("GOOGLE_REFRESH_TOKEN")

        if client_id and client_secret and refresh_token:
            creds = Credentials(
                token=None,
                refresh_token=refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=client_id,
                client_secret=client_secret,
                scopes=SCOPES,
            )
            creds.refresh(Request())
            logger.info("Token obtained from environment variables")
            _save_token(creds)
        else:
            raise RuntimeError(
                "No valid OAuth credentials found. "
                "Please configure authorization via the Web UI redirect flow "
                "or define GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_REFRESH_TOKEN."
            )

    return creds


def get_authorization_url(redirect_uri: str) -> str:
    """Generate the Google login consent screen URL.

    Args:
        redirect_uri: The callback URL endpoint on our server.

    Returns:
        str: Google login link URL.
    """
    if not CLIENT_SECRET_PATH.exists():
        raise FileNotFoundError(
            f"No client_secret.json found in {CLIENT_SECRET_PATH.parent}. "
            "Please download your client credentials from Google Cloud Console."
        )

    flow = Flow.from_client_secrets_file(
        str(CLIENT_SECRET_PATH),
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )
    
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return authorization_url


def fetch_and_save_token(code: str, redirect_uri: str) -> Credentials:
    """Exchange the OAuth authorization code for credentials tokens.

    Args:
        code: The auth code from callback.
        redirect_uri: The redirect URI matching the request.

    Returns:
        Credentials: The authenticated credentials object.
    """
    flow = Flow.from_client_secrets_file(
        str(CLIENT_SECRET_PATH),
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )
    flow.fetch_token(code=code)
    creds = flow.credentials
    _save_token(creds)
    logger.info("OAuth token successfully exchanged and saved to token.json")
    return creds


def _save_token(creds: Credentials) -> None:
    """Persist credentials to token.json."""
    try:
        token_data = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes,
        }
        TOKEN_PATH.write_text(json.dumps(token_data, indent=2))
        logger.debug("Token saved to %s", TOKEN_PATH)
    except Exception as e:
        logger.warning(f"Failed to save token: {e}")


def build_service(service_name: str, version: str):
    """Build a Google API service client."""
    creds = get_credentials()
    return build(service_name, version, credentials=creds)


def get_calendar_service():
    return build_service("calendar", "v3")


def get_gmail_service():
    return build_service("gmail", "v1")


def get_docs_service():
    return build_service("docs", "v1")


def get_sheets_service():
    return build_service("sheets", "v4")
