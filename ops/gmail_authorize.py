"""Interactive local OAuth consent only; never sends messages."""
import argparse
from pathlib import Path

from app.gmail_api import GmailError, SCOPE, read_private, write_private


def authorize(client_file: Path, token_file: Path) -> None:
    from google_auth_oauthlib.flow import InstalledAppFlow
    failed = False
    try:
        client = read_private(client_file)
        installed = client['installed']
        # Do not allow credential documents to redirect token exchange elsewhere.
        if installed['auth_uri'] != 'https://accounts.google.com/o/oauth2/auth' or installed['token_uri'] != 'https://oauth2.googleapis.com/token':
            raise GmailError('Unexpected OAuth endpoints')
        if token_file.exists():
            raise GmailError('Use a new token path for reauthorization')
        flow = InstalledAppFlow.from_client_config(client, scopes=[SCOPE], autogenerate_code_verifier=True)
        credentials = flow.run_local_server(host='127.0.0.1', port=0, open_browser=True,
            authorization_prompt_message='', success_message='Arbitrage authorization complete. Close this tab.',
            access_type='offline', prompt='consent', include_granted_scopes='false', timeout_seconds=300)
        if not credentials.refresh_token or set(credentials.granted_scopes or credentials.scopes) != {SCOPE}:
            raise GmailError('Send-only offline consent required')
        write_private(token_file, {'client_id': credentials.client_id, 'client_secret': credentials.client_secret,
                                  'refresh_token': credentials.refresh_token, 'scopes': [SCOPE]})
    except Exception:
        failed = True
    if failed:
        raise GmailError('Gmail authorization failed; check local setup and consent')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client-file', required=True, type=Path)
    parser.add_argument('--token-file', required=True, type=Path)
    args = parser.parse_args()
    try:
        authorize(args.client_file, args.token_file)
    except GmailError as error:
        print(str(error))
        return 1
    print('Authorization saved privately; no email sent.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
