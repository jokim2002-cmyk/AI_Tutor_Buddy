# Google Login and Cloud Sync

Status: **visible login and bidirectional sync code implemented; live Firebase configuration and two-device acceptance remain pending.**

## Implemented

- Durable local SQLite conversation storage in `data/conversations.db`.
- Stable local device identity in `data/device_identity.json`.
- Student and tutor messages survive application restarts.
- Every local write creates a durable sync-outbox event.
- Visible **Sign in with Google**, **Sync now**, and **Sign out** controls.
- Flet Google OAuth callback fixed to the configured local port (default `8550`).
- Google OAuth access-token exchange for a Firebase ID/refresh-token session.
- Firebase session refresh before cloud calls.
- Local anonymous chats are explicitly claimed by the authenticated Firebase UID.
- Owner-isolated Firestore upload and remote conversation/message download.
- Deterministic local/remote merge that preserves a newer unsynced local record.
- Encrypted OAuth-token persistence only when `GYANVERSE_AUTH_STORAGE_SECRET` is configured.
- Signed-out local chats remain separate from cloud-owned chats.
- Firestore Security Rules validate authenticated owner and document IDs.

## Not yet accepted

- No Firebase project or OAuth client is created automatically.
- Firestore rules still need to be deployed to the user's Firebase project.
- Live Google sign-in and Firestore upload/download need Windows acceptance.
- Cross-device Windows/Android conversation sync has not been tested.
- Delete propagation is not included yet.
- Attachments and generated audio are not uploaded; this phase syncs chat text and metadata only.
- Android OAuth acceptance remains pending until the APK phase.

## Data flow

1. The app writes chat data to local SQLite immediately.
2. Signed-in writes enter a durable local outbox.
3. `ConversationSyncService` uploads outbox records under `users/{uid}/conversations/...`.
4. The same service lists the signed-in user's remote conversations/messages and merges them locally.
5. Firestore REST requests use the Firebase ID token, leaving Security Rules authoritative.

See `GOOGLE_CLOUD_SYNC_SETUP.md` for Firebase Console and local environment configuration.
