# Two truths and a lie

A multiplayer party game for friends. Python (Flask) backend, plain HTML/JS front end.

## Run it
    pip install -r requirements.txt
    python app.py
Open http://localhost:5000, start a room, and share the 4-letter code.

## Play with friends on other devices
- Same Wi-Fi: open http://YOUR-LAPTOP-IP:5000 on their phones.
- Over the internet: deploy to Render or Railway with start command
  `gunicorn -w 1 --threads 8 app:app`  (keep ONE worker; game state is in memory).

## Rules
Everyone writes 2 truths and 1 lie. Each round, friends guess the lie.
Correct guess = +100 for the guesser. Each friend you fool = +100 for you.
