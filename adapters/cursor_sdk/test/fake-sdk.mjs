const scenario = () => process.env.FAKE_SDK_SCENARIO || "ok";
const leakKey = () => process.env.FAKE_SDK_SEEN_KEY_ECHO === "1";

class AuthenticationError extends Error { constructor(m) { super(m); this.name = "AuthenticationError"; } }
class RateLimitError extends Error { constructor(m) { super(m); this.name = "RateLimitError"; } }
class NetworkError extends Error { constructor(m) { super(m); this.name = "NetworkError"; } }

const usage = { inputTokens: 11, outputTokens: 2, cacheReadTokens: 5, cacheWriteTokens: 0, totalTokens: 18 };

function makeRun(options, prompt) {
  let status = "running";
  let cancelled = false;
  const steers = [];
  const run = {
    id: "run-fake-1",
    agentId: "agent-fake-1",
    get status() { return status; },
    async *stream() {
      yield { type: "status", status: "RUNNING" };
      if (scenario() === "slow" || scenario() === "steer") {
        for (let i = 0; i < 100 && !cancelled; i++) {
          await new Promise((r) => setTimeout(r, 50));
          if (scenario() === "steer" && steers.length > 0) break;
        }
      }
      yield { type: "assistant", message: { role: "assistant", content: [{ type: "text", text: "OK" }] } };
    },
    async wait() {
      if (cancelled) { status = "cancelled"; return { id: run.id, status }; }
      if (scenario() === "run_error") {
        status = "error";
        return { id: run.id, status, error: { message: `boom with ${options.apiKey}`, code: "internal" } };
      }
      status = "finished";
      const text = scenario() === "steer" ? `OK steered:${steers.join("|")}` : "OK";
      return { id: run.id, status, result: text, durationMs: 42, usage, model: options.model };
    },
    async cancel() { cancelled = true; },
    async steer(text) { steers.push(text); return "complete_delivered"; },
  };
  return run;
}

export const Agent = {
  async create(options) {
    if (leakKey()) process.stderr.write(`debug apiKey=${options.apiKey}\n`);
    const s = scenario();
    if (s === "auth") throw new AuthenticationError(`invalid api key ${options.apiKey}`);
    if (s === "rate") throw new RateLimitError("You've hit your usage limit");
    if (s === "network") throw new NetworkError("fetch failed");
    if (s === "crash") throw new Error(`unexpected crash key=${options.apiKey}`);
    globalThis.__fakeOptions = options;
    return {
      agentId: "agent-fake-1",
      async send(prompt) { return makeRun(options, prompt); },
      async getUsage() {
        if (s === "usage_cost") return { usage, cost: { rawCostCents: 1, chargedCents: 0.5 }, runs: [] };
        const e = new Error("feature_unavailable"); e.code = "feature_unavailable"; throw e;
      },
    };
  },
};
