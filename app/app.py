import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from collections import Counter, defaultdict
from flask import render_template
from flask import Flask, jsonify, request
from flask_cors import CORS

try:
    from dotenv import load_dotenv
    load_dotenv()                      # load .env if python-dotenv installed
except ImportError:                    # graceful fallback
    pass


# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ecpc-analytics")

# ---------------------------------------------------------------------------
# App & environment configuration
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "ICPCRoad"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-insecure-key")

_flask_debug = os.environ.get("FLASK_DEBUG", "0").strip()
app.config["DEBUG"] = _flask_debug in ("1", "true", "True")

# CORS — restrict to configured origins (defaults to same-origin / *).
_cors_origins = os.environ.get("CORS_ORIGINS", "*")
cors_origins = [o.strip() for o in _cors_origins.split(",") if o.strip()]
CORS(app, origins=cors_origins)

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address

    _rate_limit = os.environ.get("RATE_LIMIT", "60/minute")
    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=[_rate_limit],
        storage_uri="memory://",
    )
    logger.info("Rate limiting enabled: %s", _rate_limit)
except ImportError:
    limiter = None
    logger.warning("flask-limiter not installed — rate limiting disabled")

# ---------------------------------------------------------------------------
# Admin API key (used to gate /api/refresh)
# ---------------------------------------------------------------------------
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "")

# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------
@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'"
    )
    return response


class ContestStore:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.raw_files: Dict[str, Any] = {}
        self.problems: List[Dict[str, Any]] = []
        self.contests: Dict[str, Dict[str, Any]] = {}
        self.mtimes: Dict[str, float] = {}
        self.load()

    def _read_json_file(self, path: Path) -> Any:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _file_id(self, path: Path) -> str:
        return path.name

    def _needs_reload(self) -> bool:
        if not self.data_dir.exists():
            return False

        current_files = list(self.data_dir.glob("*.json"))
        if len(current_files) != len(self.mtimes):
            return True

        for p in current_files:
            key = self._file_id(p)
            mtime = p.stat().st_mtime
            if key not in self.mtimes or self.mtimes[key] != mtime:
                return True
        return False

    def maybe_reload(self) -> None:
        if self._needs_reload():
            logger.info("Data change detected, reloading contest data…")
            self.load()

    def load(self) -> None:
        self.raw_files.clear()
        self.problems.clear()
        self.contests.clear()
        self.mtimes.clear()

        if not self.data_dir.exists():
            logger.warning("Data directory does not exist: %s", self.data_dir)
            return

        for path in sorted(self.data_dir.glob("*.json")):
            try:
                data = self._read_json_file(path)
                self.raw_files[path.name] = data
                self.mtimes[path.name] = path.stat().st_mtime
                self._ingest_file(path.name, data)
            except Exception as e:
                logger.exception("Failed to load %s: %s", path.name, e)

        self._finalize_contests()
        logger.info(
            "Loaded %d contest files → %d contests, %d problems",
            len(self.raw_files), len(self.contests), len(self.problems),
        )

    def _contest_id_from_file(self, filename: str, data: Dict[str, Any]) -> str:
        stem = Path(filename).stem
        if data.get("title"):
            return data["title"]
        if "year" in data:
            if "Qualifications" in stem or "qualification" in stem.lower():
                return f'{data["year"]}-Q'
            return str(data["year"])
        return stem

    def _make_problem_url(self, contest_link: str, letter: str) -> str:
        if not contest_link:
            return ""
        return f"{contest_link}/problem/{letter}"

    def _normalize_problem(
        self,
        *,
        contest_id: str,
        title: str,
        year: Optional[int],
        is_qualification: bool,
        day: int,
        contest_link: str,
        problem: Dict[str, Any],
    ) -> Dict[str, Any]:
        letter = problem.get("letter")
        normalized = {
            "contest_id": contest_id,
            "title": title,
            "year": year,
            "is_qualification": is_qualification,
            "day": day,
            "letter": letter,
            "name": problem.get("name"),
            "solvers": problem.get("solvers", 0),
            "attempts": problem.get("attempts", 0),
            "solve_rate": problem.get("solve_rate", 0.0),
            "difficulty": problem.get("difficulty", "Unknown"),
            "primary_topic": problem.get("primary_topic", "Unknown"),
            "secondary_topics": problem.get("secondary_topics", []),
            "contest_link": contest_link,
            "problem_url": self._make_problem_url(contest_link, letter) if letter else contest_link,
            "global_index": problem.get("global_index"),
        }
        return normalized

    def _ingest_file(self, filename: str, data: Dict[str, Any]) -> None:
        contest_id = self._contest_id_from_file(filename, data)

        if "days" in data:
            title = data.get("title", contest_id)
            contest_link = data.get("contest_link", "")
            year = None
            for ch in title:
                if ch.isdigit():
                    year = int("".join([c for c in title if c.isdigit()][:4])) if any(c.isdigit() for c in title) else None
                    break

            contest = self.contests.setdefault(contest_id, {
                "contest_id": contest_id,
                "title": title,
                "contest_link": contest_link,
                "is_qualification": True,
                "days": {},
                "year": year,
            })

            for day_block in data.get("days", []):
                day_num = int(day_block.get("day", 0))
                day_link = day_block.get("contest_link", "") or contest_link

                contest["days"].setdefault(day_num, [])
                for problem in day_block.get("problems", []):
                    normalized = self._normalize_problem(
                        contest_id=contest_id,
                        title=title,
                        year=year,
                        is_qualification=True,
                        day=day_num,
                        contest_link=day_link,  
                        problem=problem,
                    )
                    contest["days"][day_num].append(normalized)
                    self.problems.append(normalized)
            return

        if "problems" in data:
            year = data.get("year")
            day_num = int(data.get("day", 0))
            title = f"ECPC{year}" if year is not None else contest_id
            contest_link = data.get("contest_link", "")

            contest = self.contests.setdefault(contest_id, {
                "contest_id": contest_id,
                "title": title,
                "contest_link": contest_link,
                "is_qualification": False,
                "days": {},
                "year": year,
            })

            contest["days"].setdefault(day_num, [])
            for problem in data.get("problems", []):
                normalized = self._normalize_problem(
                    contest_id=contest_id,
                    title=title,
                    year=year,
                    is_qualification=False,
                    day=day_num,
                    contest_link=contest_link,
                    problem=problem,
                )
                contest["days"][day_num].append(normalized)
                self.problems.append(normalized)

    def _finalize_contests(self) -> None:

        for contest in self.contests.values():
            days_dict = contest.get("days", {})
            sorted_days = sorted(days_dict.items(), key=lambda x: x[0])

            contest_problems = []
            day_summaries = []

            for day_num, problems in sorted_days:
                contest_problems.extend(problems)
                day_summaries.append(self._build_day_summary(contest, day_num, problems))

            contest["days"] = day_summaries
            contest["summary"] = self._build_contest_summary(contest, contest_problems)

        self.global_summary = self._build_global_summary()

    def _build_day_summary(self, contest: Dict[str, Any], day_num: int, problems: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not problems:
            return {
                "day": day_num,
                "total_problems": 0,
                "difficulty_counts": {},
                "avg_solve_rate": 0.0,
                "topic_counts": [],
                "hardest": [],
                "easiest": [],
            }

        difficulty_counts = Counter(p["difficulty"] for p in problems)
        topic_counts = Counter()

        for p in problems:
            topic_counts[p["primary_topic"]] += 1
            for s in p.get("secondary_topics", []):
                topic_counts[s] += 1
        avg_solve_rate = round(sum(p["solve_rate"] for p in problems) / len(problems), 2)

        hardest = sorted(problems, key=lambda p: (p["solve_rate"], p["solvers"]))[:3]
        easiest = sorted(problems, key=lambda p: (-p["solve_rate"], -p["solvers"]))[:3]

        return {
            "day": day_num,
            "total_problems": len(problems),
            "difficulty_counts": dict(difficulty_counts),
            "avg_solve_rate": avg_solve_rate,
            "topic_counts": topic_counts.most_common(10),
            "hardest": hardest,
            "easiest": easiest,
        }

    def _build_contest_summary(self, contest: Dict[str, Any], problems: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not problems:
            return {
                "total_problems": 0,
                "difficulty_counts": {},
                "topic_counts": [],
                "avg_solve_rate": 0.0,
                "hardest": [],
                "easiest": [],
            }

        difficulty_counts = Counter(p["difficulty"] for p in problems)
        topic_counts = Counter()

        for p in problems:
            topic_counts[p["primary_topic"]] += 1
            for s in p.get("secondary_topics", []):
                topic_counts[s] += 1
        avg_solve_rate = round(sum(p["solve_rate"] for p in problems) / len(problems), 2)

        hardest = sorted(problems, key=lambda p: (p["solve_rate"], p["solvers"]))[:10]
        easiest = sorted(problems, key=lambda p: (-p["solve_rate"], -p["solvers"]))[:10]

        return {
            "total_problems": len(problems),
            "difficulty_counts": dict(difficulty_counts),
            "topic_counts": topic_counts.most_common(15),
            "avg_solve_rate": avg_solve_rate,
            "hardest": hardest,
            "easiest": easiest,
        }

    def _build_global_summary(self) -> Dict[str, Any]:
        if not self.problems:
            return {
                "total_contests": 0,
                "total_problems": 0,
                "difficulty_counts": {},
                "topic_counts": [],
                "avg_solve_rate": 0.0,
            }

        difficulty_counts = Counter(p["difficulty"] for p in self.problems)
        topic_counts = Counter()

        for p in self.problems:
            topic_counts[p["primary_topic"]] += 1
            for s in p.get("secondary_topics", []):
                topic_counts[s] += 1
        avg_solve_rate = round(sum(p["solve_rate"] for p in self.problems) / len(self.problems), 2)

        return {
            "total_contests": len(self.contests),
            "total_problems": len(self.problems),
            "difficulty_counts": dict(difficulty_counts),
            "topic_counts": topic_counts.most_common(25),
            "avg_solve_rate": avg_solve_rate,
        }

    def get_contest_list(self) -> List[Dict[str, Any]]:
        self.maybe_reload()
        return [
            {
                "contest_id": c["contest_id"],
                "title": c["title"],
                "contest_link": c["contest_link"],
                "is_qualification": c["is_qualification"],
                "year": c.get("year"),
                "total_days": len(c.get("days", [])),
                "total_problems": c.get("summary", {}).get("total_problems", 0),
                "summary": c.get("summary", {}),
            }
            for c in sorted(self.contests.values(), key=lambda x: (x["is_qualification"], x.get("year", 0), x["contest_id"]))
        ]

    def get_contest(self, contest_id: str) -> Optional[Dict[str, Any]]:
        self.maybe_reload()
        return self.contests.get(contest_id)

    def get_day(self, contest_id: str, day: int) -> Optional[Dict[str, Any]]:
        contest = self.get_contest(contest_id)
        if not contest:
            return None
        for d in contest["days"]:
            if d["day"] == day:
                return d
        return None

    def search_problems(
        self,
        contest_id: Optional[str] = None,
        topic: Optional[str] = None,
        difficulty: Optional[str] = None,
        q: Optional[str] = None,
        day: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        self.maybe_reload()
        result = self.problems

        if contest_id:
            result = [p for p in result if p["contest_id"] == contest_id]
        if topic:
            topic_lower = topic.lower()
            result = [
                p for p in result
                if p["primary_topic"].lower() == topic_lower
                or any(topic_lower == s.lower() for s in p.get("secondary_topics", []))
            ]
        if difficulty:
            result = [p for p in result if p["difficulty"].lower() == difficulty.lower()]
        if day is not None:
            result = [p for p in result if p["day"] == day]
        if q:
            q_lower = q.lower()
            result = [
                p for p in result
                if q_lower in (p.get("name") or "").lower()
                or q_lower in (p.get("letter") or "").lower()
                or q_lower in (p.get("global_index") or "").lower()
            ]

        return result


store = ContestStore(DATA_DIR)


@app.get("/api/health")
def health():
    return jsonify({"ok": True})


@app.get("/api/contests")
def contests():
    return jsonify(store.get_contest_list())


@app.get("/contest/<contest_id>")
def contest_page(contest_id):
    return render_template("contest.html", contest_id=contest_id)

@app.get("/contest/<contest_id>/day/<int:day>")
def day_page(contest_id, day):
    return render_template("day.html", contest_id=contest_id, day=day)
@app.get("/api/problems")
def get_problems():
    contest_id = request.args.get("contest_id", "")[:100]
    topic = request.args.get("topic", "")[:100]
    difficulty = request.args.get("difficulty", "")[:50]
    q = request.args.get("q", "")[:200]
    day = request.args.get("day", type=int)

    items = store.search_problems(
        contest_id=contest_id or None,
        topic=topic or None,
        difficulty=difficulty or None,
        q=q or None,
        day=day,
    )

    return jsonify({
        "count": len(items),
        "items": items
    })
@app.get("/api/contests/<contest_id>")
def get_contest(contest_id):
    contest = store.get_contest(contest_id)
    
    if not contest:
        return jsonify({"error": "Contest not found"}), 404
    
    return jsonify(contest)

@app.get("/problems")
def problems_page():
    return render_template("problems.html")


@app.get("/api/stats/overview")
def stats_overview():
    return jsonify(store.global_summary)

@app.get("/api/overview")
def overview_alias():
    return jsonify(store.global_summary)


@app.get("/api/stats/day")
def stats_day():
    contest_id = request.args.get("contest_id")
    day = request.args.get("day", type=int)

    if not contest_id or day is None:
        return jsonify({"error": "contest_id and day are required"}), 400

    data = store.get_day(contest_id, day)
    if not data:
        return jsonify({"error": "Day not found"}), 404

    return jsonify(data)

@app.get("/")
def home():
    return render_template("index.html")

@app.get("/api/topics")
def topics():
    store.maybe_reload()
    cnt = Counter()
    for p in store.problems:
        cnt[p["primary_topic"]] += 1
        for s in p.get("secondary_topics", []):
            cnt[s] += 1

    return jsonify([
        {"topic": topic, "count": count}
        for topic, count in cnt.most_common()
    ])


@app.get("/api/refresh")
def refresh():
    key = request.headers.get("X-Admin-Key", "")
    if not ADMIN_API_KEY or key != ADMIN_API_KEY:
        logger.warning("Unauthorized /api/refresh attempt from %s", request.remote_addr)
        return jsonify({"error": "Forbidden"}), 403
    store.load()
    logger.info("Manual data refresh triggered by admin")
    return jsonify({"ok": True, "message": "reloaded"})


if __name__ == "__main__":
    _host = os.environ.get("HOST", "0.0.0.0")
    _port = int(os.environ.get("PORT", 5000))
    logger.info("Starting ECPC Analytics dev server (host=%s, port=%d, data_dir=%s)", _host, _port, DATA_DIR)
    app.run(debug=app.config["DEBUG"], host=_host, port=_port)