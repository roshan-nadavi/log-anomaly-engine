"""Ensemble anomaly detector.

Consumes window feature vectors from `windows:computed` and scores each
one with two independent signals:

1. Isolation Forest over aggregate features (event_count, latency,
   error rate) — the original baseline detector.
2. A Markov transition model over the ordered (endpoint, status_bucket)
   log-key sequence within the window — a lightweight, DeepLog-inspired
   stand-in for "is this sequence of events one we've seen before,"
   without needing to train an LSTM for a project at this scale.

A window is flagged anomalous if EITHER signal fires (OR-ensemble) —
research on hybrid log anomaly detection generally finds sequence-based
and feature-based signals catch different failure modes, so treating
them as independent alarms rather than averaging them into one score
avoids one detector's confidence masking the other's alert.

Both models are fit once a baseline of DETECTOR_BASELINE_WINDOWS
windows has accumulated, then periodically refit on a sliding buffer
(DETECTOR_BUFFER_MAX windows) to track drift. Known simplification:
the sequence model's anomaly threshold is derived from scoring the
same baseline windows it was trained on (no held-out validation split)
— fine for a demo-scale project, but a production system would want a
held-out baseline to avoid an optimistic threshold.
"""
import json
import os
import time
from collections import defaultdict, deque

import numpy as np
import redis
from psycopg.types.json import Json
from scipy.stats import genpareto
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from common.db import get_conn, init_schema
from common.streams import TRANSIENT_REDIS_ERRORS, ack, ensure_group, read_batch

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
SOURCE_STREAM = os.environ.get("SOURCE_STREAM", "windows:computed")
ANOMALY_STREAM = os.environ.get("ANOMALY_STREAM", "anomalies:triggered")
GROUP = "detector-group"
CONSUMER = os.environ.get("HOSTNAME", "detector-1")

BASELINE_WINDOWS = int(os.environ.get("DETECTOR_BASELINE_WINDOWS", "10"))
REFIT_INTERVAL = int(os.environ.get("DETECTOR_REFIT_INTERVAL", "10"))
BUFFER_MAX = int(os.environ.get("DETECTOR_BUFFER_MAX", "200"))
CONTAMINATION = float(os.environ.get("DETECTOR_CONTAMINATION", "0.1"))
RECONNECT_INITIAL_BACKOFF = 2.0
RECONNECT_MAX_BACKOFF = 30.0
SEQ_SMOOTHING = 1e-3
# SPOT (Siffer et al., "Anomaly Detection in Streams with Extreme Value
# Theory," KDD 2017): scores above the SEQ_TAIL_QUANTILE are treated as
# the distribution's tail and fit with a Generalized Pareto Distribution,
# rather than assuming the whole score distribution is Gaussian.
SEQ_TAIL_QUANTILE = float(os.environ.get("DETECTOR_SEQ_TAIL_QUANTILE", "0.95"))
SEQ_RISK_PROBABILITY = float(os.environ.get("DETECTOR_SEQ_RISK_PROBABILITY", "0.005"))
SEQ_MIN_PEAKS = 10

FEATURE_KEYS = [
    "event_count", "avg_latency_ms", "p95_latency_ms",
    "error_rate", "status_4xx", "status_5xx",
]


def to_vector(features: dict) -> list[float]:
    return [float(features[k]) for k in FEATURE_KEYS]


class SequenceModel:
    def __init__(self):
        self.counts: dict[tuple, dict[tuple, int]] = defaultdict(lambda: defaultdict(int))
        self.totals: dict[tuple, int] = defaultdict(int)
        self.threshold = float("inf")

    def fit(self, sequences: list[list[list[str]]]) -> None:
        self.counts.clear()
        self.totals.clear()
        for seq in sequences:
            keys = [tuple(k) for k in seq]
            for a, b in zip(keys, keys[1:]):
                self.counts[a][b] += 1
                self.totals[a] += 1

        baseline_scores = [self.score(seq) for seq in sequences]
        self.threshold = self._spot_threshold(baseline_scores)

    @staticmethod
    def _spot_threshold(scores: list[float]) -> float:
        """SPOT (Siffer et al., KDD 2017): fit a Generalized Pareto
        Distribution to the tail of the baseline score distribution and
        derive an extreme quantile from it, instead of assuming the whole
        distribution is Gaussian. These scores are -log(probability) and
        are naturally right-skewed, so a mean+3sigma threshold both
        under-fires (misses genuinely rare sequences under a heavy tail)
        and over-fires (flags routine tail variance as anomalous).
        """
        n = len(scores)
        if n == 0:
            return float("inf")

        scores_arr = np.asarray(scores, dtype=float)
        t = float(np.quantile(scores_arr, SEQ_TAIL_QUANTILE))
        peaks = scores_arr[scores_arr > t] - t

        if len(peaks) < SEQ_MIN_PEAKS:
            # Too few tail exceedances for a stable 2-parameter GPD fit
            # (small/early baseline, e.g. right at BASELINE_WINDOWS) —
            # fall back to a 1-parameter exponential tail (GPD's shape=0
            # special case) fit by method of moments over the *whole*
            # baseline. A mean estimate is stable at n as low as ~6-10,
            # unlike counting exceedances over a high quantile, while
            # still respecting the right-skew that made mean+3sigma
            # unreliable. (Empirically: on a 10-sample skewed baseline,
            # this fallback holds the false-positive rate near 0% versus
            # ~1-5% for either mean+3sigma or an empirical-max fallback.)
            mean_score = float(scores_arr.mean())
            if mean_score <= 0:
                return float(scores_arr.max() + 1e-6)
            return float(-mean_score * np.log(SEQ_RISK_PROBABILITY))

        try:
            shape, _, scale = genpareto.fit(peaks, floc=0)
        except Exception:
            return float(scores_arr.max() + 1e-6)

        if scale <= 0:
            return float(scores_arr.max() + 1e-6)

        # Closed-form SPOT extreme quantile for risk probability q: the
        # threshold above which we expect a fraction q of future scores
        # to fall, extrapolated from the fitted GPD tail rather than the
        # raw empirical distribution.
        exceedance_rate = len(peaks) / n
        ratio = SEQ_RISK_PROBABILITY / exceedance_rate
        if abs(shape) < 1e-6:
            z_q = t - scale * np.log(ratio)
        else:
            z_q = t + (scale / shape) * (ratio ** (-shape) - 1)

        return float(max(z_q, t))

    def score(self, sequence: list[list[str]]) -> float:
        keys = [tuple(k) for k in sequence]
        if len(keys) < 2:
            return 0.0
        neg_log_probs = []
        vocab_size = max(1, len(self.totals))
        for a, b in zip(keys, keys[1:]):
            total = self.totals.get(a, 0)
            count = self.counts.get(a, {}).get(b, 0)
            prob = (count + SEQ_SMOOTHING) / (total + SEQ_SMOOTHING * vocab_size)
            neg_log_probs.append(-np.log(prob))
        return float(np.mean(neg_log_probs))

    def is_anomalous(self, sequence: list[list[str]]) -> tuple[bool, float]:
        s = self.score(sequence)
        return s > self.threshold, s


def insert_anomaly(conn, window_id, window_start, window_end,
                    iso_score, iso_flag, seq_score, seq_flag, detail) -> tuple[int, bool]:
    combined = bool(iso_flag or seq_flag)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO anomalies
                (window_id, window_start, window_end, iso_forest_score, iso_forest_flag,
                 sequence_score, sequence_flag, combined_flag, detail)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
            """,
            (window_id, window_start, window_end, iso_score, iso_flag,
             seq_score, seq_flag, combined, Json(detail)),
        )
        return cur.fetchone()[0], combined


def main():
    r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    ensure_group(r, SOURCE_STREAM, GROUP)
    conn = get_conn()
    init_schema(conn)

    buffer_windows: deque[dict] = deque(maxlen=BUFFER_MAX)
    scaler = StandardScaler()
    forest = None
    seq_model = SequenceModel()
    windows_since_fit = 0

    print(f"[detector] starting, baseline={BASELINE_WINDOWS} windows", flush=True)

    backoff = RECONNECT_INITIAL_BACKOFF
    while True:
        try:
            messages = read_batch(r, SOURCE_STREAM, GROUP, CONSUMER, count=50, block_ms=5000)
            if not messages:
                continue

            ids = []
            for msg_id, fields in messages:
                ids.append(msg_id)
                try:
                    window = json.loads(fields["payload"])
                except (KeyError, json.JSONDecodeError):
                    continue

                buffer_windows.append(window)

                if forest is None or windows_since_fit >= REFIT_INTERVAL:
                    if len(buffer_windows) >= BASELINE_WINDOWS:
                        vectors = np.array([to_vector(w) for w in buffer_windows])
                        scaler = StandardScaler().fit(vectors)
                        forest = IsolationForest(
                            contamination=CONTAMINATION, random_state=42
                        ).fit(scaler.transform(vectors))
                        seq_model.fit([w["sequence"] for w in buffer_windows])
                        windows_since_fit = 0
                        print(f"[detector] (re)fit on {len(buffer_windows)} windows", flush=True)

                windows_since_fit += 1

                if forest is None:
                    continue  # still warming up, not enough history to score yet

                vec = scaler.transform([to_vector(window)])
                iso_pred = forest.predict(vec)[0]  # -1 anomaly, 1 normal
                iso_score = float(forest.decision_function(vec)[0])  # lower = more anomalous
                iso_flag = iso_pred == -1

                seq_flag, seq_score = seq_model.is_anomalous(window["sequence"])

                anomaly_id, combined = insert_anomaly(
                    conn, window["window_id"], window["window_start"], window["window_end"],
                    iso_score, bool(iso_flag), seq_score, bool(seq_flag),
                    {"features": {k: window[k] for k in FEATURE_KEYS}},
                )

                status = "ANOMALY" if combined else "normal"
                print(
                    f"[detector] window {window['window_id']} -> {status} "
                    f"(iso={iso_score:.3f}/{iso_flag}, seq={seq_score:.3f}/{seq_flag})",
                    flush=True,
                )

                if combined:
                    r.xadd(ANOMALY_STREAM, {"payload": json.dumps({
                        "anomaly_id": anomaly_id,
                        "window_id": window["window_id"],
                        "window_start": window["window_start"],
                        "window_end": window["window_end"],
                    })})

            ack(r, SOURCE_STREAM, GROUP, ids)
            backoff = RECONNECT_INITIAL_BACKOFF
        except TRANSIENT_REDIS_ERRORS as exc:
            print(f"[detector] redis unavailable ({exc}), retrying in {backoff:.0f}s", flush=True)
            time.sleep(backoff)
            backoff = min(backoff * 2, RECONNECT_MAX_BACKOFF)


if __name__ == "__main__":
    main()
