# TCP CUBIC 拥塞窗口核算服务

一个可以独立跑起来的传输层仿真组件：上游把**一次丢包事件之后**的关键量
（丢包前峰值窗口 `W_max`、往返时延 `RTT`、立方系数 `C`、可选的上一次
峰值 `W_last_max`）交给它，它负责算出**任意时刻**的：

* CUBIC 立方窗口 `w_cubic`；
* TCP 友好线性对照窗口 `w_tcp`；
* 当前实际采用的窗口 `w` 与所处分支（`cubic` / `tcp_friendly`）；
* 是否仍处于快速收敛阶段（`fast_convergence`）。

仅经 HTTP 对外提供，服务无状态。**不**涉及抓包、防火墙面板、令牌桶
限速或排队队长。

## 数学模型（与 RFC 8312 对齐）

窗口单位为 MSS 段数，时间单位为秒，乘性缩减因子固定 `β = 0.7`：

```
W_cubic(t) = C · (t − K)³ + W_max          # 立方增长分支
K          = ∛( W_max · (1 − β) / C )      # 回到峰值所需时间
W_tcp(t)   = β·W_max + [3β/(2−β)] · t/RTT  # TCP 友好线性对照（β=0.7 时系数 21/13）
```

选取判据：

* `W_tcp(t) > W_cubic(t)`（低带宽时延积场景）→ 退让到 **TCP 友好区**，
  采用线性对照值；
* 否则采用 **CUBIC 立方值**。

快速收敛（RFC 8312 §4.6）：本次峰值 `W_max < W_last_max`（峰值下降）时
判定为开；持平、上升或没有历史峰值时为关。

### 自洽性锚点

* **`t = 0`**：立方窗口精确等于 `β·W_max`（丢包后起点）；
* **`t = K`**：`(t−K)=0`，曲线斜率为零，立方窗口**精确等于 `W_max`**
  （相对 1e-12 的时间容差带内直接钳为精确值，防止浮点开三次方的尾数
  偏差或分支比较写歪）；
* `t < K` 立方窗口严格小于峰值，`t > K` 严格大于峰值。

## 目录结构（按职责拆模块）

```
app/
├── config.py              # CUBIC 常量（β、默认 C、分支名、容差）
├── errors.py              # 带类型的结构化错误（四类非法输入各一码）
├── schemas.py             # 请求/响应 Pydantic 模型
├── presets.py             # 内置标准情形与可核对算例
├── monitor.py             # 线程安全的运行状态计数
├── routes.py              # HTTP 路由、异常处理器、监控中间件
├── main.py                # FastAPI 装配入口
└── window/
    ├── kernel.py          # 窗口数学内核（纯函数：K、立方/线性窗口、选取）
    ├── validation.py      # 入参校验（先挡后算）
    └── trajectory.py      # 轨迹推进（逐点调用同一个内核函数）
tests/                     # 自动化测试（48 个用例）
Dockerfile                 # python:3.12-slim 一键构建启动
docker-compose.yml
```

单点与轨迹两个接口共用 `app/window/kernel.py::evaluate`，不存在两套算法。

## 一键启动（Docker）

```bash
docker compose up --build
# 或
docker build -t cubic-window-service .
docker run --rm -p 8000:8000 cubic-window-service
```

服务监听 `http://0.0.0.0:8000`，交互式文档在 `http://localhost:8000/docs`。

## 接口

### `POST /api/v3/evaluate` — 单时刻求值

```bash
curl -sX POST localhost:8000/api/v3/evaluate \
  -H 'content-type: application/json' \
  -d '{"w_max": 100, "rtt": 1.0, "t": 4.217}'
```

```json
{
  "t": 4.217,
  "w_cubic": 99.9994, "w_tcp": 76.81, "w": 99.9994,
  "branch": "cubic", "tcp_friendly": false, "at_peak": false,
  "w_reduced": 70.0,
  "k": 4.2171633265087465,
  "fast_convergence": false,
  "w_max": 100.0, "c": 0.4, "rtt": 1.0, "w_last_max": null
}
```

低 BDP 示例（线性分支接管）：

```bash
curl -sX POST localhost:8000/api/v3/evaluate \
  -H 'content-type: application/json' \
  -d '{"w_max": 10, "rtt": 0.01, "t": 2.0}'
```

快速收敛判定（本次峰值 100 < 上次 140）：在请求中加
`"w_last_max": 140`，响应里 `"fast_convergence": true`。

### `POST /api/v3/trajectory` — 整条轨迹

```bash
curl -sX POST localhost:8000/api/v3/trajectory \
  -H 'content-type: application/json' \
  -d '{"w_max": 100, "rtt": 1.0, "times": [0, 2.1, 4.2171633265087465, 8.4]}'
```

每个采样点都带 `w_cubic` / `w_tcp` / `w` / `branch`，另有顶层的
`k` 与 `fast_convergence`。`times` 必须**严格递增且非负**。

### `GET /api/v3/standards` — 只读：标准常量、公式、错误码与预置算例

预置 `W_max=100, C=0.4, RTT=1s, W_last_max=140` 的可核对算例，采样时刻为
`0、K/2、K、3K/2、2K`：

| t | 含义 | w_cubic |
|---|---|---|
| 0 | 丢包起点，窗口先降到峰值下方 | 70（=0.7·100） |
| K/2 | 峰值下方缓慢逼近 | 96.25 |
| **K** | **曲线斜率为零，精确回到峰值** | **100** |
| 3K/2 | 越过峰值 | 103.75 |
| 2K | 越过峰值后加速 | 130 |

其中 `K = ∛(100·0.3/0.4) ≈ 4.2172s`。

### `GET /healthz` — 监控

```json
{"status": "ok", "uptime_seconds": 12.3, "requests_completed": 8,
 "errors": 1, "stateless": true}
```

## 错误处理（带类型，不抛未捕获异常）

任何基础量不合法都在开算前挡下，统一返回
`422 {"error": {"code": ..., "message": ..., "field": ...}}`：

| 非法情形 | error.code |
|---|---|
| 峰值窗口 `w_max <= 0`（含 `w_max = 0` 退化情形） | `invalid_wmax` |
| 立方系数 `c <= 0` | `invalid_c` |
| 时间 `t < 0`（轨迹中某采样点同理） | `invalid_time` |
| 往返时延 `rtt <= 0` | `invalid_rtt` |
| NaN / Infinity | `non_finite_number` |
| 轨迹采样时刻非严格递增 | `non_increasing_times` |
| 请求体不符合模型 | `malformed_request` |

## 本地开发与测试

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest                 # 48 个用例
uvicorn app.main:app --reload
```

测试覆盖：峰值点窗口精确等于峰值、增大峰值使 K 变长（重新超越峰值时刻
推后）、立方系数加倍使 K 缩短、越过/未越过峰值与峰值的严格大小关系、
低 BDP 下 TCP 友好分支被选中、四类非法输入分别被挡、单点与轨迹同刻
结果逐字段一致、快速收敛随峰值升降开合、以及并发多请求互不串扰。
