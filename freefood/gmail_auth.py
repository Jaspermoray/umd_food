"""
One-time Gmail login. Run:  python -m freefood.gmail_auth

Opens a browser to sign in to the bot's Gmail account and saves gmail_token.json
(read-only access). Paste that file's contents into the GMAIL_TOKEN GitHub secret.
"""
from google_auth_oauthlib.flow import InstalledAppFlow

from .gmail import SCOPES


def main() -> None:
    flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    with open("gmail_token.json", "w") as f:
        f.write(creds.to_json())
    print("Saved gmail_token.json. Next: pbcopy < gmail_token.json, then paste it into the")
    print("GMAIL_TOKEN secret at GitHub -> Settings -> Secrets and variables -> Actions.")


if __name__ == "__main__":
    main()
