# Orchestra: Member 4 Development Log

Here is a brief log of your weekly tasks and accomplishments.

## Week 1: GitHub Webhook Listener

### Day 1
- **Project Setup**: Created the project folder, set up a Python virtual environment, and installed key tools (`fastapi`, `uvicorn`, `requests`, `python-dotenv`).
- **Security Configuration**: Created a `.env` file to store a GitHub webhook secret and registered a GitHub OAuth app to get a Client ID.
- Created a FastAPI app (`main.py`) with a `POST /webhook` endpoint to receive incoming data.
- Tested the endpoint locally using `curl` and `uvicorn` to print raw request headers and JSON data directly to the terminal.
- **Signature Verification**: Added HMAC-SHA256 security to verify incoming requests. The app now rejects unauthorized traffic (`403 Forbidden`) missing a valid `X-Hub-Signature-256` header and reads the `X-GitHub-Event` header to identify the action type (like a `push` or `pull_request`).

### Day 2
- I set up and secured the `/webhook` endpoint to reject unauthorized traffic, while configuring it to identify specific GitHub actions like pushes or pull requests using the `X-GitHub-Event` header. 
- Since Prakash wasn't available, I tested it myself: I used an ngrok tunnel to expose the local FastAPI server and connected it to a new test repository on GitHub. 
- I then triggered a live `push` event and successfully verified that the server captured and printed the raw JSON payload. 
- Also learned about JSON parsing, which I will implement tomorrow. 
- When Prakash is available, I will ask him for the main server URL that we'll be using.

### Day 3
- **Checklist Compliance & Security**: Added explicit `print` statements for raw headers and body to the terminal for debugging. Ignored the `venv` and `.env` files using a newly created `.gitignore`.
- **Advanced Payload Parsing**: Extracted parsing logic into a dedicated `parse_event` function. It now captures extended payload details like the `branch` name, individual commit IDs and messages, and `pull_request` metadata.
- **Robustness**: Wrapped the parser in a `try/except` block to gracefully handle bad payloads (returning an error field) without crashing the server.
- **JSON Event Storage**: Switched from plain text logging to appending raw JSON objects directly to `events.json` line-by-line. Deleted the old `webhook_events.log` relic.
- **API Endpoints**: 
  - Added a `GET /events` route that reads `events.json` and outputs a pretty-printed, easily readable JSON array directly in the browser.
  - Added a `GET /health` endpoint for quick server status checks.

### Day 4
- **First live GitHub event**: Created a dummy GitHub repository (`webhook-test-repo`) and successfully hooked up the local ngrok tunnel.
- Pushed a commit to test the webhook and verified that the FastAPI server received, logged, and parsed the real JSON payload properly. Both terminal and GitHub delivery logs confirmed successful transmission.

### Day 5
- **Code Polish**: Added descriptive comments to `main.py` explaining each section to improve readability for the team.
- **Documentation**: Wrote a concise `README.md` with instructions on how to install, run, and test the webhook listener locally.
- Ready to push code with screenshots and demonstrate real-time event capture to the team.
