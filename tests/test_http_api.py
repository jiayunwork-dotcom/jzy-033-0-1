"""HTTP 层测试：结构化错误、单点/轨迹一致性、接口回显、并发隔离。"""

from __future__ import annotations

import concurrent.futures

from fastapi.testclient import TestClient

from app.main import app

CANON_BODY = {
    "peak_window_mss": 80,
    "rtt_s": 0.5,
    "cubic_coefficient": 0.375,
    "previous_peak_window_mss": 100,
}

COMPARED_FIELDS = (
    "elapsed_time_s",
    "k_s",
    "cubic_window_mss",
    "tcp_friendly_window_mss",
    "adopted_window_mss",
    "branch",
)


def _eval(client: TestClient, body: dict) -> dict:
    response = client.post("/evaluate", json=body)
    assert response.status_code == 200, response.text
    return response.json()


class TestStructuredHttpErrors:
    def test_four_invalid_categories_over_http(self, client: TestClient) -> None:
        cases = [
            ({"peak_window_mss": 0, "elapsed_time_s": 1, "rtt_s": 0.1}, "invalid_peak_window"),
            ({"peak_window_mss": 1, "elapsed_time_s": 1, "rtt_s": 0.1,
              "cubic_coefficient": 0}, "invalid_cubic_coefficient"),
            ({"peak_window_mss": 1, "elapsed_time_s": -2, "rtt_s": 0.1}, "invalid_elapsed_time"),
            ({"peak_window_mss": 1, "elapsed_time_s": 1, "rtt_s": -0.1}, "invalid_rtt"),
        ]
        for body, expected_type in cases:
            response = client.post("/evaluate", json=body)
            assert response.status_code == 400
            payload = response.json()
            assert payload["error_type"] == expected_type
            assert payload["message"]

    def test_zero_peak_is_rejected_not_zero_window(self, client: TestClient) -> None:
        response = client.post(
            "/evaluate",
            json={"peak_window_mss": 0, "elapsed_time_s": 0, "rtt_s": 0.1},
        )
        assert response.status_code == 400
        assert response.json()["error_type"] == "invalid_peak_window"

    def test_schema_error_is_structured(self, client: TestClient) -> None:
        response = client.post("/evaluate", json={"elapsed_time_s": 1})
        assert response.status_code == 400
        assert response.json()["error_type"] == "invalid_request_schema"

    def test_trajectory_non_increasing_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/trajectory",
            json={**CANON_BODY, "sample_times_s": [0.0, 4.0, 2.0]},
        )
        assert response.status_code == 400
        assert response.json()["error_type"] == "invalid_sample_times"

    def test_trajectory_empty_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/trajectory", json={**CANON_BODY, "sample_times_s": []}
        )
        assert response.status_code == 400
        assert response.json()["error_type"] == "invalid_sample_times"


class TestEvaluateEndpoint:
    def test_peak_point_through_http(self, client: TestClient) -> None:
        payload = _eval(client, {**CANON_BODY, "elapsed_time_s": 4.0})
        assert payload["k_s"] == 4.0
        assert payload["cubic_window_mss"] == 80.0
        assert payload["position"]["at_peak"] is True
        assert payload["fast_convergence"] == {"active": True, "peak_trend": "falling"}

    def test_low_bdp_branch_through_http(self, client: TestClient) -> None:
        payload = _eval(
            client,
            {"peak_window_mss": 10, "elapsed_time_s": 0.5, "rtt_s": 0.01},
        )
        assert payload["branch"] == "tcp_friendly"
        assert payload["adopted_window_mss"] == payload["tcp_friendly_window_mss"]


class TestSingleVsTrajectoryConsistency:
    def test_same_times_identical_results(self, client: TestClient) -> None:
        times = [0.0, 1.25, 2.5, 4.0, 5.75, 8.0]
        traj = client.post(
            "/trajectory", json={**CANON_BODY, "sample_times_s": times}
        ).json()

        assert traj["k_s"] == 4.0
        assert len(traj["points"]) == len(times)
        for t, point in zip(times, traj["points"]):
            single = _eval(client, {**CANON_BODY, "elapsed_time_s": t})
            for field in COMPARED_FIELDS:
                assert point[field] == single[field], (t, field)
            assert point["position"] == single["position"]
            assert point["fast_convergence"] == single["fast_convergence"]

    def test_consistency_with_varied_inputs(self, client: TestClient) -> None:
        # 低 BDP / 高 BDP / 默认系数各跑一遍，防止分支不同的点出现两套算法
        for params in [
            {"peak_window_mss": 10, "rtt_s": 0.01},
            {"peak_window_mss": 10000, "rtt_s": 0.2},
            {"peak_window_mss": 33.3, "rtt_s": 0.123, "cubic_coefficient": 0.67},
        ]:
            times = [0.0, 0.3, 1.7, 4.2]
            traj = client.post("/trajectory", json={**params, "sample_times_s": times}).json()
            for t, point in zip(times, traj["points"]):
                single = _eval(client, {**params, "elapsed_time_s": t})
                for field in COMPARED_FIELDS:
                    assert point[field] == single[field]


class TestPresetsAndOps:
    def test_presets_readonly_listing(self, client: TestClient) -> None:
        payload = client.get("/presets").json()
        assert payload["count"] >= 1
        ids = {p["preset_id"] for p in payload["presets"]}
        assert "canonical_recovery_demo" in ids
        demo = next(p for p in payload["presets"] if p["preset_id"] == "canonical_recovery_demo")
        checkpoint_map = {c["elapsed_time_s"]: c["cubic_window_mss"] for c in demo["checkpoints"]}
        assert checkpoint_map == {0.0: 56.0, 2.0: 77.0, 4.0: 80.0, 6.0: 83.0, 8.0: 104.0}

    def test_preset_detail_and_unknown(self, client: TestClient) -> None:
        ok = client.get("/presets/canonical_recovery_demo")
        assert ok.status_code == 200 and ok.json()["k_s"] == 4.0
        missing = client.get("/presets/does-not-exist")
        assert missing.status_code == 404
        assert missing.json()["error_type"] == "preset_not_found"

    def test_health_and_metrics(self, client: TestClient) -> None:
        assert client.get("/health").json() == {"status": "ok"}
        before = client.get("/metrics").json()
        client.post("/evaluate", json={"peak_window_mss": 1, "elapsed_time_s": 0, "rtt_s": 0.1})
        client.post("/evaluate", json={"peak_window_mss": 0, "elapsed_time_s": 0, "rtt_s": 0.1})
        # 下面的 /metrics 自身也会被中间件计为一次（成功）请求
        after = client.get("/metrics").json()
        assert after["requests_total"] == before["requests_total"] + 3
        assert after["errors_total"] == before["errors_total"] + 1
        assert after["uptime_s"] >= 0.0


class TestConcurrencyIsolation:
    def test_parallel_requests_do_not_cross_wires(self) -> None:
        # 多组差异显著的参数并发打单点接口；每个响应必须严格对应自己的入参。
        cases = [
            {"peak_window_mss": 80, "elapsed_time_s": 4.0, "rtt_s": 0.5,
             "cubic_coefficient": 0.375, "want_window": 80.0, "want_branch": "cubic"},
            {"peak_window_mss": 10, "elapsed_time_s": 0.5, "rtt_s": 0.01,
             "want_window": None, "want_branch": "tcp_friendly"},
            {"peak_window_mss": 100, "elapsed_time_s": 0.0, "rtt_s": 0.2,
             "want_window": 70.0, "want_branch": "cubic"},
            {"peak_window_mss": 250, "elapsed_time_s": 9.9, "rtt_s": 0.05,
             "cubic_coefficient": 0.5, "want_window": None, "want_branch": "tcp_friendly"},
        ]

        def worker(case: dict) -> tuple[dict, dict]:
            local_client = TestClient(app)
            body = {k: v for k, v in case.items() if k.startswith(("peak", "elapsed", "rtt", "cubic"))}
            response = local_client.post("/evaluate", json=body)
            assert response.status_code == 200, response.text
            return case, response.json()

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(worker, cases * 8))

        for case, payload in results:
            assert payload["peak_window_mss"] == float(case["peak_window_mss"])
            assert payload["elapsed_time_s"] == case["elapsed_time_s"]
            assert payload["branch"] == case["want_branch"]
            if case["want_window"] is not None:
                assert payload["adopted_window_mss"] == case["want_window"]

    def test_parallel_trajectory_and_single_agree(self) -> None:
        times = [0.0, 2.0, 4.0, 8.0]

        def worker(t: float) -> tuple[float, float, str]:
            local_client = TestClient(app)
            single = local_client.post(
                "/evaluate", json={**CANON_BODY, "elapsed_time_s": t}
            ).json()
            return t, single["adopted_window_mss"], single["branch"]

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            singles = dict((t, (w, b)) for t, w, b in pool.map(worker, times))

        with TestClient(app) as client:
            traj = client.post(
                "/trajectory", json={**CANON_BODY, "sample_times_s": times}
            ).json()

        for point in traj["points"]:
            window, branch = singles[point["elapsed_time_s"]]
            assert point["adopted_window_mss"] == window
            assert point["branch"] == branch
