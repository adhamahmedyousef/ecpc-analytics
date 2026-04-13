import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from collections import Counter, defaultdict
from flask import render_template
from flask import Flask, jsonify, request
from flask_cors import CORS


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "ICPCRoad"


app = Flask(__name__)
CORS(app)


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
            self.load()

    def load(self) -> None:
        self.raw_files.clear()
        self.problems.clear()
        self.contests.clear()
        self.mtimes.clear()

        if not self.data_dir.exists():
            return

        for path in sorted(self.data_dir.glob("*.json")):
            try:
                data = self._read_json_file(path)
                self.raw_files[path.name] = data
                self.mtimes[path.name] = path.stat().st_mtime
                self._ingest_file(path.name, data)
            except Exception as e:
                print(f"[WARN] Failed to load {path.name}: {e}")

        self._finalize_contests()

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
    contest_id = request.args.get("contest_id")
    topic = request.args.get("topic")
    difficulty = request.args.get("difficulty")
    q = request.args.get("q")
    day = request.args.get("day", type=int)

    items = store.search_problems(
        contest_id=contest_id,
        topic=topic,
        difficulty=difficulty,
        q=q,
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
    store.load()
    return jsonify({"ok": True, "message": "reloaded"})


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)