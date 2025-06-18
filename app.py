from flask import Flask

app = Flask(__name__)

@app.route('/')
def index():
    return "✅ Flask is running successfully on Render!"
