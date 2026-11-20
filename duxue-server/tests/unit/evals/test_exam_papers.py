import json

import pytest

from evals.exams.grading import CHOICES, WEIGHTS, checked
from evals.exams.papers import SOURCES, tasks
from evals.exams.score import summarize
from evals.exams.transport import digest, write


def test_every_marked_question_has_one_task_and_a_valid_attachment_range():
    for subject in SOURCES:
        covered = []
        for first, last, p1, p2 in tasks(subject):
            covered.extend(range(first, last + 1))
            assert 1 <= p1 <= p2 < p1 + 4
        assert covered == [i for i, w in enumerate(WEIGHTS[subject], 1) if w]
        assert sum(WEIGHTS[subject]) == (150 if subject in {"math", "chinese"} else 100)
        assert set(CHOICES.get(subject, "")) <= set("ABCD")


def test_physics_q13_includes_pages_4_and_5():
    physics = {first: (first, last, p1, p2) for first, last, p1, p2 in tasks("physics")}
    assert physics[13] == (13, 13, 4, 5)
    assert physics[14] == (14, 14, 5, 5)


@pytest.mark.parametrize(
    "rows",
    [
        [{"number": 1, "points": 3}, {"number": 1, "points": 3}],
        [{"number": 1, "points": 4}, {"number": 2, "points": 0}],
        [{"number": 1, "points": float("nan")}, {"number": 2, "points": 0}],
    ],
)
def test_grader_rejects_incomplete_or_invalid_marks(rows):
    with pytest.raises(ValueError):
        checked(rows, {1: 3, 2: 3})


def test_pending_answer_and_changed_evidence_not_counted(tmp_path):
    run = tmp_path / "run"
    out = tmp_path / "grades"
    run.mkdir()
    out.mkdir()
    file = run / "math-01.json"
    write(file, {"status": "answered", "answer": {"content": "D", "act": "explain"}})
    write(
        out / file.name,
        {
            "answer_sha256": digest(file),
            "version": "v",
            "rows": [{"number": 1, "points": 4, "reason": "D"}],
        },
    )
    assert summarize(run, out, "v")["math"]["earned"] == 4
    write(file, {"status": "submitted"})
    assert summarize(run, out, "v")["math"]["pending"] == 150
    assert json.loads((out / "totals.json").read_text())["math"]["graded"] == 0


def test_first_submission_uses_student_pdf_only_and_is_not_replayed(tmp_path):
    import hashlib

    import httpx
    import pymupdf

    from evals.exams.transport import deliver

    data = tmp_path / "math"
    data.mkdir()
    for role, text in [("paper", "STUDENT QUESTION"), ("key", "HIDDEN GOLD")]:
        with pymupdf.open() as doc:
            doc.new_page().insert_text((30, 60), text)
            doc.save(data / (role + ".pdf"))
    posts, uploads = [], []

    def endpoint(request):
        if request.url.path.endswith("upload-url"):
            return httpx.Response(
                200,
                json={
                    "upload_url": "http://127.0.0.1/upload",
                    "headers": {},
                    "oss_key": "test/student.jpg",
                },
            )
        if request.method == "PUT":
            uploads.append(hashlib.sha256(request.content).hexdigest())
            return httpx.Response(204)
        posts.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "content": "D",
                "mode": "guardian_explain",
                "act": "explain",
                "state_token": "must not be archived",
            },
        )

    dest = tmp_path / "answer.json"
    with httpx.Client(
        base_url="http://127.0.0.1", transport=httpx.MockTransport(endpoint)
    ) as client:
        for _ in range(2):
            deliver(
                client,
                ("user", "guardian"),
                tmp_path,
                dest,
                "math",
                (1, 1, 1, 1),
                "first question",
            )
    assert posts == [
        {
            "mode": "guardian_explain",
            "content": "first question",
            "attachment_keys": ["test/student.jpg"],
        }
    ]
    with pymupdf.open(data / "paper.pdf") as doc:
        image = (
            doc[0]
            .get_pixmap(matrix=pymupdf.Matrix(1.8, 1.8))
            .tobytes("jpeg", jpg_quality=90)
        )
    assert uploads == [hashlib.sha256(image).hexdigest()]
    assert "state_token" not in dest.read_text()
    assert json.loads(dest.read_text())["status"] == "answered"


def test_clean_geography_source_has_pinned_reversed_publisher_ids():
    from pathlib import Path

    from evals.exams import prepare

    index = json.loads(Path(prepare.__file__).with_name("sources.json").read_text())
    assert index["geography"]["paper"]["pages"] == 8
    assert index["geography"]["key"]["pages"] == 17
    assert index["geography"]["paper"]["url"].endswith("1751942106558037131.pdf")


def test_interrupted_submission_is_retained_for_separate_recovery(tmp_path):
    from evals.exams.transport import close_interrupted

    lost = tmp_path / "math-01.json"
    good = tmp_path / "math-02.json"
    write(lost, {"status": "submitted", "questions": [1, 1]})
    write(good, {"status": "answered", "questions": [2, 2]})
    close_interrupted(tmp_path)
    assert json.loads(lost.read_text())["status"] == "delivery_unknown"
    assert json.loads(good.read_text())["status"] == "answered"


def test_second_reader_uses_only_pinned_original_lines_for_challenged_score(
    tmp_path, monkeypatch
):
    import pymupdf

    from evals.exams import review

    root = tmp_path / "data"
    run = tmp_path / "run"
    grades = tmp_path / "grades"
    for path in (root / "politics", run, grades):
        path.mkdir(parents=True)
    with pymupdf.open() as doc:
        for _ in range(24):
            doc.new_page()
        doc.save(root / "politics/key.pdf")
    file = run / "politics-21.json"
    write(
        file,
        {
            "subject": "politics",
            "questions": [21, 21],
            "status": "answered",
            "answer": {"act": "explain", "content": "Intro\nOriginal argument\nAdvice"},
        },
    )
    row = {"number": 21, "points": 0, "evidence": "", "parts": []}
    write(
        grades / file.name,
        {
            "answer_sha256": digest(file),
            "version": "v",
            "rows": [row],
            "reviews": [{"old_rows": [row]}],
            "verified_question_maximum": 10,
        },
    )
    evidence = {
        file.name: {"answer_sha256": digest(file), "lines": [2], "reviewer": "test"}
    }

    def judge(prompt, payload, images):
        assert payload["answer"]["content"] == "Original argument"
        assert payload["question_maxima"] == {21: 10}
        return {"rows": [dict(row, points=5)]}

    monkeypatch.setattr(review, "ask", judge)
    assert review.adjudicate(root, run, grades, evidence=evidence) == 1
    assert review.adjudicate(root, run, grades, evidence=evidence) == 0
    assert json.loads((grades / file.name).read_text())["rows"][0]["points"] == 5
