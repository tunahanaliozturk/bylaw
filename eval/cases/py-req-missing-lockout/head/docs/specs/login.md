# Sign in

Users sign in with their email address and password.

## Acceptance criteria

- [ ] `login` returns the user when the email and password match.
- [ ] `login` returns `None` when they do not.
- [ ] After five failed attempts in a row the account is locked, and `login` returns `None` even with the right password.
