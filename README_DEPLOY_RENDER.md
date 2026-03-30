# Predal Verifier – Render deployment package

This package is ready to deploy to Render as a public web app.

## Files
- `app.py` - Flask app
- `requirements.txt` - Python dependencies
- `render.yaml` - Render Blueprint config
- `.python-version` - Python version for Render

## Fastest deployment
1. Create a new GitHub repository.
2. Upload all files from this folder to that repository.
3. Log in to Render.
4. Click **New > Blueprint**.
5. Connect the GitHub repository.
6. Confirm deployment.

Render will build the service and assign an `onrender.com` URL.

## Alternate manual deployment
If you use **New > Web Service** instead of Blueprint, use:
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app:app --workers 2 --threads 4 --timeout 180`

## Notes
- The app includes a `/healthz` endpoint for Render health checks.
- Free web services may sleep after inactivity depending on your Render plan.
- Uploaded PDFs are processed temporarily in memory / temp files during each request.

## Local run
```bash
python -m pip install -r requirements.txt
python app.py
```
