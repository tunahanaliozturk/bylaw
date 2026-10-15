# users-service

A small user service: accounts, password reset and avatars, on SQLite.

## Running the tests

```
python -m pytest
```

## Layout

- `app/users.py`: user records.
- `app/auth.py`: password hashing and reset tokens.
- `app/files.py`: avatars, stored under names the server chooses.
