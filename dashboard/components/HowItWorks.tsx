export default function HowItWorks() {
  return (
    <div className="flex flex-col gap-4">
      <div className="bg-panel border border-edge rounded-lg p-4">
        <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted mb-3">The pipeline</h2>
        <p className="text-sm text-neutral-300 leading-relaxed">
          Logs flow through Redis Streams end to end: an ingestion API publishes each entry,
          a rolling-window aggregator buckets them into throughput/latency/error-rate features
          every few seconds, an ensemble detector scores each window, and flagged anomalies
          trigger an LLM incident agent. Every stage is a separate Docker service communicating
          only through Redis and Postgres — nothing shares in-process state.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-panel border border-edge rounded-lg p-4">
          <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted mb-3">
            Why two detectors, not one
          </h2>
          <p className="text-sm text-neutral-300 leading-relaxed mb-3">
            An Isolation Forest scores each window on aggregate features (latency, error rate,
            throughput). A separate Markov transition model — a lightweight, DeepLog-inspired
            stand-in for an LSTM — scores the ordered sequence of endpoint/status transitions
            within the window.
          </p>
          <p className="text-sm text-neutral-300 leading-relaxed">
            A window is flagged if <em>either</em> signal fires, not an average of the two.
            Research on hybrid log anomaly detection generally finds sequence-based and
            feature-based signals catch different failure modes — averaging them into one
            score risks one detector&apos;s confidence masking the other&apos;s alert.
          </p>
        </div>

        <div className="bg-panel border border-edge rounded-lg p-4">
          <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted mb-3">
            Why extreme-value statistics, not mean+3σ
          </h2>
          <p className="text-sm text-neutral-300 leading-relaxed mb-3">
            The sequence model&apos;s scores are -log(probability): naturally right-skewed, not
            Gaussian. A naive mean+3σ threshold both under-fires on genuinely rare sequences
            under a heavy tail and over-fires on routine tail variance — a real false-positive
            pattern found during testing.
          </p>
          <p className="text-sm text-neutral-300 leading-relaxed">
            It was replaced with SPOT (Siffer et al., KDD 2017): fit a Generalized Pareto
            distribution to the tail of the baseline scores and derive an extreme quantile from
            that, instead of assuming normality.
          </p>
        </div>

        <div className="bg-panel border border-edge rounded-lg p-4">
          <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted mb-3">
            Incident generation
          </h2>
          <p className="text-sm text-neutral-300 leading-relaxed mb-3">
            A flagged window pulls its surrounding raw log slice (error entries prioritized),
            retrieves the most similar past incidents via pgvector cosine-KNN as few-shot
            context, and asks an LLM for a structured root cause, severity, and remediation —
            validated against a schema, with a safe fallback if parsing fails.
          </p>
          <p className="text-sm text-neutral-300 leading-relaxed">
            The LLM call sits behind a circuit breaker with exponential backoff. On failure the
            message is deliberately left unacknowledged rather than dropped, so it&apos;s
            automatically retried once the circuit recovers.
          </p>
        </div>

        <div className="bg-panel border border-edge rounded-lg p-4">
          <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted mb-3">
            Resilience, actually tested
          </h2>
          <p className="text-sm text-neutral-300 leading-relaxed mb-3">
            Redis was killed mid-run: the ingestion/query APIs degraded gracefully and
            auto-recovered, but the three stream-consumer workers crashed outright — no
            reconnect logic existed yet. Fixed with exponential-backoff reconnection instead of
            a bare restart policy, since restarting loses the detector&apos;s fitted model and
            has to re-warm from scratch.
          </p>
          <p className="text-sm text-neutral-300 leading-relaxed">
            The LLM API was also blackholed mid-run: the circuit breaker opened, correctly
            cycled half-open retries every ~60s without getting stuck, and closed itself the
            instant the API became reachable again — zero incidents lost across the outage.
          </p>
        </div>
      </div>

      <div className="bg-panel border border-edge rounded-lg p-4">
        <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted mb-3">
          Infrastructure
        </h2>
        <p className="text-sm text-neutral-300 leading-relaxed">
          Self-hosted end to end on a single GCP Compute Engine VM — no managed PaaS. GitHub
          Actions builds all seven service images, pushes them to GHCR, and SSHes into the VM
          to deploy on every push to <code className="text-accent">main</code>, no manual steps.
          Nightly Postgres backups upload to Cloud Storage under a least-privilege service
          account; Google&apos;s Ops Agent ships CPU/memory/disk metrics with alerting on
          resource exhaustion.
        </p>
        <p className="text-sm text-muted mt-3">
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
    </div>
  );
}
