# Google Login and Firestore Sync Setup

Status: code implemented; live Firebase project configuration and Windows acceptance are still pending.

## What this phase does

- Shows a visible **Sign in with Google** control.
- Uses Flet's Google OAuth authorization-code flow.
- Exchanges the Google OAuth access token for a Firebase ID/refresh-token session.
- Keeps chat writes local-first in SQLite.
- Pushes the durable outbox to owner-isolated Firestore paths.
- Pulls the signed-in user's conversations/messages and merges them into local SQLite.
- Keeps signed-out local chats separate from authenticated cloud-owned chats.
- Never bundles a service-account key in the app.

## Firebase console setup

1. Create or select a Firebase project.
2. Enable **Authentication > Sign-in method > Google**.
3. Create a Cloud Firestore database.
4. Deploy `firebase/firestore.rules` before using real student data.
5. In Google Cloud Console, create an OAuth 2.0 **Web application** client.
6. Add this authorized redirect URI exactly:

   `http://localhost:8550/oauth_callback`

7. Copy `firebase/firebase_config.env.example` values into the local `.env` file.
8. Generate a long random `GYANVERSE_AUTH_STORAGE_SECRET`. It is used only to encrypt the saved Flet OAuth token. If omitted, login works for the current run but "Remember me" is disabled.

## Security boundaries

- Firebase Web API keys and OAuth client IDs identify the project/client; they are not service-account private keys.
- Keep the OAuth client secret and auth-storage secret outside Git.
- Firestore requests use the signed-in user's Firebase ID token, so Firestore Security Rules remain authoritative.
- Chat text is synced. Audio cache and homework attachments are not uploaded in this phase.

## Current acceptance limits

- Live Google sign-in requires the user's Firebase/Google configuration.
- Windows OAuth and cross-device sync must be manually tested after configuration.
- Android OAuth acceptance remains pending until the APK phase.
