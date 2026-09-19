"""服务级常量与 CUBIC 标准常量。

数学约定（与 RFC 8312 对齐）：

* 窗口以 MSS 段数为单位，时间以秒为单位；
* 乘性缩减因子 beta = 0.7，丢包瞬间窗口落到 beta * W_max；
* CUBIC 立方分支：  W_cubic(t) = C * (t - K)**3 + W_max
* 回到峰值所需时间： K = cbrt(W_max * (1 - beta) / C)
* TCP 友好线性对照： W_tcp(t)   = W_max * beta
                                + [3 * beta / (2 - beta)] * (t / RTT)
* 选取规则：        W_tcp(t) > W_cubic(t) 时退让到 TCP 友好分支，
                    否则采用 CUBIC 立方分支（低 BDP 场景下立方增长
                    比 Reno 线性增长慢，于是被线性值接管）。
"""

from __future__ import annotations

#: 乘性缩减因子：丢包后窗口保留 beta * W_max。
BETA = 0.7

#: CUBIC 立方系数默认值（RFC 8312 规定 C = 0.4，未做 RTT 缩放）。
DEFAULT_C = 0.4

#: 快速收敛（RFC 8312 第 4.6 节）窗口再缩减系数；本服务仅报告快速收敛
#: 是否开合，不改动请求中给出的峰值窗口。
FAST_CONVERGENCE_BETA = 0.85

#: TCP 友好线性项系数 3*beta/(2-beta)。beta=0.7 时为 21/13。
TCP_FRIENDLY_SLOPE = (3.0 * BETA) / (2.0 - BETA)

#: 分支名称（响应中原样回显，供上游画图与回归核对）。
BRANCH_CUBIC = "cubic"
BRANCH_TCP_FRIENDLY = "tcp_friendly"

#: 峰值点自洽性的相对容差：|t - K| 在此范围内时把立方窗口钳到
#: 精确的 W_max，保证「回到峰值时刻窗口恰好等于峰值」不被浮点误差
#: 或分支比较写歪。量级约 1e-12，正常采样时刻不会落进来。
PEAK_EPS_REL = 1e-12

SERVICE_NAME = "cubic-window-service"
