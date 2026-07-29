# Testing the iOS app on a phone

1. Generate a development token without committing it:

   ```bash
   openssl rand -hex 32
   ```

2. Add the result to `backend/.env`:

   ```text
   APP_API_KEY=<same-random-token>
   ```

3. Restart the backend yourself so its cached settings pick up the token, then
   start the HTTPS tunnel:

   ```bash
   ngrok http 8100
   ```

4. In Xcode, open **Product → Scheme → Edit Scheme → Run → Arguments** and add:

   ```text
   API_BASE_URL=https://your-domain.ngrok.app/api
   APP_API_KEY=<same-random-token>
   ```

   Keep both values enabled as environment variables. Xcode passes them only to
   the development process it launches; they are not committed to the project.

5. Select the connected iPhone as the run destination and press Run.

Debug builds use `goals-app.debug.entitlements` so a free Personal Team can
sign and install them. Release builds retain the Associated Domains entitlement
required for Plaid OAuth. Full Plaid OAuth testing on a physical device requires
an Apple Developer Program team that supports Associated Domains.

For the React development server, copy `frontend/.env.example` to
`frontend/.env.local`, set the same `APP_API_KEY`, and restart Vite yourself.
Vite injects the bearer header at its server-side proxy; the key is not included
in browser JavaScript.

`APP_API_KEY` is a development gate for private tunnel testing. A distributed
app needs real user authentication, short-lived tokens, authorization, and rate
limits because secrets embedded in client apps can be extracted.
