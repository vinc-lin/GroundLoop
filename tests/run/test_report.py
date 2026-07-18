from groundloop.run.report import render_run_markdown


def _min_card():
    return {"n_cases": 1, "bind": "mock",
            "overall": {"match": {"n": 1, "recall@1": 1.0, "recall@3": 1.0, "recall@5": 1.0},
                        "localize": {"as_run": {"file@1": 0.0}, "isolated": None},
                        "fix": {"n_gradeable": 0, "n_ungradeable_no_source": 1,
                                "resolved_rate_strict": {"value": None, "n": 0}}},
            "cases": []}


def test_scorecard_shows_mock_bind():
    md = render_run_markdown(_min_card())
    assert "bind: mock" in md and "not a real Gerrit change" in md
