export default function HowItWorks() {
  return (
    <div className="bg-panel border border-edge rounded-lg p-6 flex flex-col gap-6 max-w-3xl">
      <section>
        <h3 className="text-base font-bold text-neutral-100 mb-2">The pipeline</h3>
        <p className="text-sm text-neutral-300 leading-relaxed">
          Logs flow through Redis Streams end to end: an ingestion API publishes each entry, a
          rolling-window aggregator buckets them into throughput, latency, and error-rate
          features every few seconds, an ensemble detector scores each window, and flagged
          anomalies trigger an LLM incident agent — each stage a separate Docker service
          communicating only through Redis and Postgres, with no shared in-process state.
        </p>
      </section>

      <section>
        <h3 className="text-base font-bold text-neutral-100 mb-2">Why two detectors, not one</h3>
        <p className="text-sm text-neutral-300 leading-relaxed">
          An Isolation Forest scores each window on aggregate features like latency, error rate,
          and throughput, while a separate Markov transition model — a lightweight,
          DeepLog-inspired stand-in for an LSTM — scores the ordered sequence of endpoint and
          status transitions within the window. A window is flagged if either signal fires
          rather than averaging the two, since research on hybrid log anomaly detection
          generally finds sequence-based and feature-based signals catch different failure
          modes, and averaging risks one detector&apos;s confidence masking the other&apos;s alert.
        </p>
      </section>

      <section>
        <h3 className="text-base font-bold text-neutral-100 mb-2">
          Why extreme-value statistics, not mean+3σ
        </h3>
        <p className="text-sm text-neutral-300 leading-relaxed">
          The sequence model&apos;s scores are -log(probability) and naturally right-skewed
          rather than Gaussian, so a naive mean+3σ threshold both under-fires on genuinely rare
          sequences under a heavy tail and over-fires on routine tail variance — a real
          false-positive pattern found during testing. It was replaced with SPOT (Siffer et al.,
          KDD 2017): fitting a Generalized Pareto distribution to the tail of the baseline scores
          and deriving an extreme quantile from that, instead of assuming normality.
        </p>
      </section>

      <section>
        <h3 className="text-base font-bold text-neutral-100 mb-2">Incident generation</h3>
        <p className="text-sm text-neutral-300 leading-relaxed">
          A flagged window pulls its surrounding raw log slice with error entries prioritized,
          retrieves the most similar past incidents via pgvector cosine-KNN as few-shot context,
          and asks an LLM for a structured root cause, severity, and remediation that&apos;s
          validated against a schema with a safe fallback if parsing fails. The LLM call itself
          sits behind a circuit breaker with exponential backoff, and on failure the message is
          deliberately left unacknowledged rather than dropped, so it&apos;s automatically
          retried once the circuit recovers.
        </p>
      </section>

      <section>
        <h3 className="text-base font-bold text-neutral-100 mb-2">Resilience, actually tested</h3>
        <p className="text-sm text-neutral-300 leading-relaxed">
          Redis was killed mid-run to test this for real: the ingestion and query APIs degraded
          gracefully and auto-recovered, but the three stream-consumer workers crashed outright
          since no reconnect logic existed yet — fixed with exponential-backoff reconnection
          instead of a bare restart policy, since restarting would lose the detector&apos;s
          fitted model and force it to re-warm from scratch. The LLM API was also blackholed
          mid-run: the circuit breaker opened, correctly cycled half-open retries roughly every
          60 seconds without getting stuck, and closed itself the instant the API became
          reachable again, with zero incidents lost across the outage.
        </p>
      </section>

      <section>
        <h3 className="text-base font-bold text-neutral-100 mb-2">Infrastructure</h3>
        <p className="text-sm text-neutral-300 leading-relaxed">
          Everything runs self-hosted on a single GCP Compute Engine VM rather than a managed
          PaaS. PostgreSQL with the pgvector extension stores window metrics, anomalies, and
          incident embeddings; Redis Streams acts as the event bus connecting every service; and
          nightly Postgres backups upload to Cloud Storage under a service account scoped to
          only that one bucket. Google&apos;s Ops Agent ships CPU, memory, and disk metrics with
          alerting on resource exhaustion.
        </p>
      </section>

      <p className="text-sm text-muted">
        Source:{" "}
        <a
          href="https://github.com/roshan-nadavi/log-anomaly-engine"
          className="text-accent hover:underline"
          target="_blank"
          rel="noopener noreferrer"
        >
          github.com/roshan-nadavi/log-anomaly-engine
        </a>
      </p>
    </div>
  );
}
