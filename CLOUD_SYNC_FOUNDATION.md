# Google Login and Cloud Sync Foundation

Status: **foundation implemented; live Google sign-in and Firestore deployment still pending.**

## What this batch adds

- Durable local SQLite conversation storage in `data/conversations.db`.
- Stable local device identity in `data/device_identity.json`.
- Student and tutor messages survive application restarts.
- The most recent bounded student/tutor turns are restored into the tutor session.
- Every local conversation/message write creates a durable sync-outbox event.
- Local chats can be explicitly claimed by a Firebase user ID after Google sign-in.
- Firebase Auth REST helpers exchange a Google OAuth ID/access token for a Firebase user session.
- Firestore REST sync writes only under `users/{uid}/conversations/...` using a Firebase ID token.
- Owner-isolated Firestore Security Rules are provided in `firebase/firestore.rules`.

## What this batch does not claim

- Google login is not yet wired into the visible Flet UI.
- No Firebase project has been created or configured automatically.
- No Firestore rules have been deployed.
- No real cloud upload/download has been accepted.
- Tokens are not stored by this foundation. The login batch must use encrypted Flet shared preferences or platform secure storage.
- Attachments and generated audio are not uploaded. Chat text and metadata are the first sync scope.
- Remote pull/conflict resolution and multi-device acceptance remain pending.

## Intended authentication flow

1. Flet opens Google OAuth through `GoogleOAuthProvider`.
2. Flet returns the Google OAuth access token and user profile.
3. `FirebaseAuthREST.exchange_google_access_token()` exchanges that credential for a Firebase ID/refresh token.
4. The local anonymous owner is explicitly re-keyed to the Firebase UID.
5. `ConversationSyncService` pushes durable outbox events with the Firebase ID token.
6. Firestore Security Rules allow access only below the authenticated user's own path.

## Required configuration for the next batch

Create a Firebase project, enable Google under Firebase Authentication, create a Firestore database, and create an OAuth client with the callback URL configured for the app. Copy `firebase/firebase_config.env.example` values into the local `.env`; never commit `.env`, a service-account key, or refresh tokens.

## Cloud data shape

```text
users/{firebaseUid}
  conversations/{conversationId}
    messages/{messageId}
```

Each document includes `ownerId`; rules require it to equal the authenticated Firebase UID. Local SQLite remains the source of immediate offline reads/writes, while the outbox makes network synchronization retryable.
