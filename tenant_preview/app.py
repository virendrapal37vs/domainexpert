"""Isolated onboarding prototype. No imports of OpenAlgo or broker order APIs."""
import os
import re
from functools import wraps

from flask import Flask, jsonify, render_template_string, request, session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect, generate_csrf
from sqlalchemy.exc import IntegrityError

from tenant_preview.store import PreviewStore


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.getenv("DOMAINXPERT_PREVIEW_SESSION_KEY"),
        PREVIEW_DATABASE=os.getenv("DOMAINXPERT_PREVIEW_DATABASE", "preview-data/onboarding.db"),
        PREVIEW_ENCRYPTION_KEY=os.getenv("DOMAINXPERT_PREVIEW_ENCRYPTION_KEY"),
        SESSION_COOKIE_NAME="domainxpert_preview", SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict", SESSION_COOKIE_SECURE=False,
        MAX_CONTENT_LENGTH=8192, WTF_CSRF_TIME_LIMIT=1800,
        PERMANENT_SESSION_LIFETIME=1800,
    )
    if config:
        app.config.update(config)
    if not app.secret_key or len(app.secret_key) < 32:
        raise RuntimeError("Set a separate preview session key of at least 32 characters")
    if not app.config["PREVIEW_ENCRYPTION_KEY"]:
        raise RuntimeError("Set a separate Fernet preview encryption key")
    store = PreviewStore(app.config["PREVIEW_DATABASE"], app.config["PREVIEW_ENCRYPTION_KEY"])
    app.extensions["preview_store"] = store
    CSRFProtect(app)
    limits = Limiter(get_remote_address, app=app, storage_uri="memory://", default_limits=["60 per minute"])

    @app.after_request
    def headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; frame-ancestors 'none'; form-action 'self'"
        return response

    app.extensions["preview_limiter"] = limits

    def require_user(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not isinstance(session.get("preview_user_id"), int):
                return jsonify(message="Sign in first"), 401
            return fn(*args, **kwargs)
        return wrapped

    def body():
        value = request.get_json(silent=True)
        return value if isinstance(value, dict) else {}

    def text(data, name, maximum):
        value = data.get(name)
        if not isinstance(value, str) or not value or len(value) > maximum:
            raise ValueError("Invalid " + name)
        return value

    def email(data):
        value = text(data, "email", 120).strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Invalid email")
        return value

    @app.errorhandler(ValueError)
    def invalid(error):
        return jsonify(message=str(error)), 400

    @app.get("/")
    def home():
        return render_template_string(PAGE)

    @app.get("/preview/csrf")
    def csrf():
        return jsonify(csrf_token=generate_csrf())

    @app.post("/preview/register")
    @limits.limit("5 per minute")
    def register():
        data = body()
        address = email(data)
        password = text(data, "password", 128)
        if len(password) < 12:
            raise ValueError("Use a password of at least 12 characters")
        token = text(data, "invitation", 128)
        try:
            store.register(address, password, token)
        except (ValueError, IntegrityError):
            return jsonify(message="Registration unavailable: check invitation and email"), 400
        return jsonify(message="Account created. Sign in to save your Groww credentials."), 201

    @app.post("/preview/login")
    @limits.limit("5 per minute")
    def login():
        data = body()
        uid = store.login(email(data), text(data, "password", 128))
        if uid is None:
            return jsonify(message="Invalid email or password"), 401
        session.clear()
        session.permanent = True
        session["preview_user_id"] = uid
        return jsonify(message="Signed in. Trading is disabled in this preview.")

    @app.post("/preview/logout")
    def logout():
        session.clear()
        return jsonify(message="Signed out")

    @app.route("/preview/credentials", methods=["GET", "PUT", "DELETE"])
    @require_user
    def credentials():
        uid = session["preview_user_id"]  # Never accept an owner from the request.
        if request.method == "GET":
            return jsonify(broker="groww", configured=store.has_credentials(uid))
        if request.method == "DELETE":
            store.delete_credentials(uid)
            return jsonify(message="Your saved credentials were deleted")
        data = body()
        store.save_credentials(uid, text(data, "api_key", 4096), text(data, "api_secret", 4096))
        return jsonify(message="Your credentials were encrypted and saved. No broker request was sent.")

    return app


PAGE = '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DomainXpert Trade · Onboarding Preview</title>
<style>body{margin:0;background:#0d1020;color:#eef0ff;font:16px system-ui}main{max-width:920px;margin:48px auto;padding:20px}h1{letter-spacing:-1px}.notice{padding:18px;border:1px solid #6e61ac;border-radius:12px;background:#211c3c}section{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:20px;margin-top:24px}form{background:#171b30;padding:24px;border-radius:16px}label{display:block;margin:16px 0 6px}input,button{box-sizing:border-box;width:100%;padding:12px;border:1px solid #424867;border-radius:8px;background:#0d1020;color:#fff}button{margin-top:20px;background:#8475ed;cursor:pointer;font-weight:700}small{color:#b7bddb}#message{padding:20px;white-space:pre-wrap}a{color:#a99aff}</style>
<main><small>DOMAINXPERT TRADE</small><h1>Your account. Your broker credentials.</h1>
<p class="notice">Development preview · Account creation and encrypted credential storage only. Trading, broker connection and strategy execution are disabled. Use test credentials.</p>
<section><form id="register"><h2>Create your profile</h2><label>Email</label><input name="email" type="email" required autocomplete="email"><label>Password</label><input name="password" type="password" minlength="12" maxlength="128" required autocomplete="new-password"><label>Invitation code</label><input name="invitation" type="password" required autocomplete="off"><button>Create account</button></form>
<form id="login"><h2>Sign in</h2><label>Email</label><input name="email" type="email" required autocomplete="username"><label>Password</label><input name="password" type="password" required autocomplete="current-password"><button>Sign in</button><button type="button" id="logout">Sign out</button></form>
<form id="credentials"><h2>Your Groww credentials</h2><small>Stored encrypted, never returned to your browser.</small><label>API key</label><input name="api_key" type="password" required autocomplete="off"><label>API secret</label><input name="api_secret" type="password" required autocomplete="off"><button>Save credentials</button><button type="button" id="status">Check saved status</button><button type="button" id="delete">Delete my credentials</button></form></section>
<p id="message" role="status" aria-live="polite"></p></main>
<script>async function call(path,method='GET',data){const token=await fetch('/preview/csrf').then(r=>r.json());const response=await fetch('/preview/'+path,{method,headers:{'Content-Type':'application/json','X-CSRFToken':token.csrf_token},body:data?JSON.stringify(data):undefined});let result;try{result=await response.json()}catch{throw Error('Request rejected. Refresh the page and try again.')}if(!response.ok)throw Error(result.message||'Request rejected');document.getElementById('message').textContent=result.message||(result.configured?'Your credentials are saved.':'No credentials saved for your account.');return result}function run(work){work.catch(e=>document.getElementById('message').textContent=e.message)}for(const id of ['register','login','credentials'])document.getElementById(id).onsubmit=e=>{e.preventDefault();const form=e.currentTarget;run(call(id,id==='credentials'?'PUT':'POST',Object.fromEntries(new FormData(form))).then(()=>form.reset()))};document.getElementById('logout').onclick=()=>run(call('logout','POST'));document.getElementById('status').onclick=()=>run(call('credentials'));document.getElementById('delete').onclick=()=>run(call('credentials','DELETE'));</script></html>'''
