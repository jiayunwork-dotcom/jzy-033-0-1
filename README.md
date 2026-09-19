# TCP CUBIC 拥塞窗口核算服务

一个可独立运行的传输层仿真组件：上游把**一次丢包事件之后**的关键量交给它，
它负责算出任意时刻的 CUBIC 拥塞窗口（以 MSS 段数为单位）、此刻由
**CUBIC 立方支**还是 **TCP 友好线性支**主导，以及是否仍处于**快速收敛阶段**。
范围严格限定在 CUBIC 窗口演进这一件事，仅经 HTTP 对外提供；无状态、
不抓包、不含防火墙面板、不做令牌桶限速或排队队长。

- Python 3.12 + FastAPI
- 纯计算内核与 HTTP 层解耦，单点求值与轨迹推进共用同一套窗口函数
- 所有非法输入在开算前挡下，返回带 `error_type` 的结构化错误

## 窗口数学

以最近一次丢包时刻为 `t = 0`，丢包前峰值窗口为 `W_max`（MSS 段数），
乘性缩减因子固定 `β = 0.7`，立方系数为 `C`：

```
W_cubic(t) = C·(t − K)³ + W_max
K          = cbrt( (1 − β)·W_max / C )
```

- `t = K` 处曲线斜率 `3C(t−K)² = 0`：窗口先在峰值下方缓慢逼近，越过 K 后加速超过峰值；
- `t = 0` 时 `W_cubic(0) = β·W_max`，即乘性缩减点；
- 代码对 `t == K` 设有显式守卫，**该点窗口精确等于 `W_max`**，不经过浮点减法/乘方。

TCP 友好对照窗口为线性增长：

```
W_tcp(t) = β·W_max + [3β/(2−β)] · (t/RTT)
```

选支判据：`W_cubic(t) < W_tcp(t)` 时退让到 TCP 友好区（低带宽时延积、短 RTT
路径正是这种情形），采用线性对照值；否则采用立方值。平局取立方。

快速收敛判定：给定上一次记录峰值 `W_prev` 时，本次峰值下降
（`W_max < W_prev`）→ 快速收敛激活（`falling`）；持平或上升 → 关闭
（`rising`）；未提供历史峰值 → 无法判定（`unknown`）。

### 自洽性与行为不变量

- `t = K` 时 `W_cubic ≡ W_max`（精确等式，有测试守）；
- `t < K ⇒ W_cubic < W_max`，`t > K ⇒ W_cubic > W_max`（严格）；
- `W_max` 增大 ⇒ `K` 变长，重新超越旧峰值的时刻推后；
- `C` 加倍 ⇒ `K` 缩短为原来的 `1/∛2`；
- 快速收敛状态随峰值升降真实开合。

## 模块划分

| 模块 | 职责 |
| --- | --- |
| `app/cubic.py` | 窗口数学内核（纯函数，零 HTTP 依赖） |
| `app/errors.py` | 带 `error_type` 的结构化领域错误 |
| `app/validation.py` | 请求模型与开算前校验（含 NaN/Inf、零峰值） |
| `app/service.py` | 单点求值与轨迹推进编排（轨迹逐点复用单点求值器） |
| `app/presets.py` | 内置标准情形（只读）与预置核对算例 |
| `app/monitoring.py` | 线程安全的运行计数 |
| `app/main.py` | FastAPI 应用、异常处理与路由 |

## HTTP 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/evaluate` | 单点求值 |
| `POST` | `/trajectory` | 一串严格递增时刻的完整轨迹 |
| `GET` | `/presets` | 只读回显全部内置标准情形及检查点 |
| `GET` | `/presets/{id}` | 单个标准情形 |
| `GET` | `/health` | 存活探针 |
| `GET` | `/metrics` | 请求数、错误数、累计/平均时延、运行时长 |
| `GET` | `/docs` | Swagger UI |

### 单点求值

```bash
curl -s -X POST localhost:8000/evaluate \
  -H 'Content-Type: application/json' \
  -d '{"peak_window_mss":80,"elapsed_time_s":4,"rtt_s":0.5,
       "cubic_coefficient":0.375,"previous_peak_window_mss":100}'
```

```json
{
  "beta": 0.7, "elapsed_time_s": 4.0, "k_s": 4.0,
  "peak_window_mss": 80.0,
  "cubic_window_mss": 80.0,
  "tcp_friendly_window_mss": 68.92307692307692,
  "adopted_window_mss": 80.0, "branch": "cubic",
  "position": {"below_peak": false, "at_peak": true, "above_peak": false},
  "fast_convergence": {"active": true, "peak_trend": "falling"}
}
```

### 轨迹推进

```bash
curl -s -X POST localhost:8000/trajectory -H 'Content-Type: application/json' \
  -d '{"peak_window_mss":80,"rtt_s":0.5,"cubic_coefficient":0.375,
       "sample_times_s":[0,2,4,6,8]}'
```

每个采样点都带 `cubic_window_mss`、`tcp_friendly_window_mss`、
`adopted_window_mss`、`branch` 与位置/快速收敛信息。

### 预置核对算例

`GET /presets/canonical_recovery_demo`（`W_max=80, C=0.375, RTT=0.5s`，
`K` 恰为 4 秒）一眼可验曲线方向与峰值点：

| t (s) | W_cubic (MSS) | 位置 |
| ---:| ---:| --- |
| 0 | 56 = 0.7×80 | 乘性缩减点 |
| 2 | 77 | 峰值下方 |
| **4** | **80 = W_max** | **精确回到峰值（斜率为零）** |
| 6 | 83 | 峰值上方 |
| 8 | 104 | 加速越过峰值 |

另有低 BDP（TCP 友好支主导）、高 BDP（立方支主导）、峰值回升（快速收敛关闭）
三个标准情形。

### 非法输入

以下四类基础量非法时返回 HTTP 400 与可区分的 `error_type`，不抛 500、不返回空值：

| 情形 | error_type |
| --- | --- |
| `peak_window_mss <= 0`（含零窗口退化）/ NaN / Inf | `invalid_peak_window` |
| `cubic_coefficient <= 0` / NaN / Inf | `invalid_cubic_coefficient` |
| `elapsed_time_s < 0` / NaN / Inf | `invalid_elapsed_time` |
| `rtt_s <= 0` / NaN / Inf | `invalid_rtt` |
| 采样序列为空或非严格递增 | `invalid_sample_times` |
| 请求结构不符合 schema | `invalid_request_schema` |

## 本地运行

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Docker 一键启动

```bash
docker build -t cubic-window-service .
docker run --rm -p 8000:8000 cubic-window-service
# 或
docker compose up --build
```

基础镜像为 `python:3.12-slim`，容器内以非 root 用户运行，带 `/health` 健康检查。

## 测试

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
```

覆盖：峰值点精确等于峰值、峰值增大使 K 变长（及超越时刻推后）、立方系数加倍
使 K 变短、K 上下方严格小于/大于峰值、低 BDP 下 TCP 友好分支选中、四类非法输入
分别被结构化挡下（含零峰值与 NaN/Inf）、单点与轨迹同刻结果逐字段一致、
快速收敛随峰值升降开合、以及多线程并发请求互不串扰。
