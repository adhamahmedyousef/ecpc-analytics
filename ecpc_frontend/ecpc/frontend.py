"""
ECPC Analytics — Frontend Flask server
Serves Jinja2 templates; API calls are proxied or called directly from JS.
Run alongside app.py (backend on :5000), this frontend on :5001.
Or integrate both into one file if preferred.
"""

from flask import Flask, render_template, redirect, url_for
from flask_cors import CORS

app = Flask(__name__)
CORS(app)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/problems")
def problems():
    return render_template("problems.html")


@app.route("/contest/<path:contest_id>")
def contest(contest_id):
    return render_template("contest.html", contest_id=contest_id)


@app.route("/contest/<path:contest_id>/day/<int:day>")
def contest_day(contest_id, day):
    return render_template("day.html", contest_id=contest_id, day=day)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)
