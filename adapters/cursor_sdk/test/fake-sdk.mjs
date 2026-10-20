// SDK fake para los tests del sidecar. Escenarios por FAKE_SDK_SCENARIO; opciones vistas por FAKE_SDK_ECHO_OPTIONS.
const scenario = () => process.env.FAKE_SDK_SCENARIO || "ok";
const leakKey = () => process.env.FAKE_SDK_SEEN_KEY_ECHO === "1";
const echo = () => process.env.FAKE_SDK_ECHO_OPTIONS === "1";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

class AuthenticationError extends Error { constructor(m) { super(m); this.name = "AuthenticationError"; } }
class RateLimitError extends Error { constructor(m) { super(m); this.name = "RateLimitError"; } }
class NetworkError extends Error { constructor(m) { super(m); this.name = "NetworkError"; } }

const usage = { inputTokens: 11, outputTokens: 2, cacheReadTokens: 5, cacheWriteTokens: 0, totalTokens: 18 };
globalThis.__fakeCreates = 0;
globalThis.__fakeConfigure = [];

export class JsonlLocalAgentStore {
  constructor(rootDir) { this.rootDir = rootDir; this.kind = "jsonl"; }
}

export const Cursor = {
  configure(options) { globalThis.__fakeConfigure.push(options); },
};

function optionsView(options, sendOptions, prompt, sends) {
  return JSON.stringify({
    model: options.model, disallowedTools: options.disallowedTools ?? null,
    mcpServers: Object.keys(options.mcpServers ?? {}), settingSources: options.local?.settingSources ?? null,
    store: options.local?.store ? { kind: options.local.store.kind, rootDir: options.local.store.rootDir } : null,
    systemPrompt: options.systemPrompt ?? null, tools: options.tools ?? null, configure: globalThis.__fakeConfigure,
    creates: globalThis.__fakeCreates, sends, prompt, sendModel: sendOptions?.model ?? null,
  });
}

function makeRun(options, prompt, sendOptions, sends) {
  let status = "running";
  let cancelled = false;
  const steers = [];
  const s = scenario();
  const long = s === "slow" || s === "steer" || s === "finish_on_cancel" || prompt.includes("SLOW");
  const run = {
    id: `run-fake-${sends}`,
    agentId: "agent-fake-1",
    get status() { return status; },
    async *stream() {
      yield { type: "status", status: "RUNNING" };
      if (s === "big") yield { type: "assistant", message: { role: "assistant", content: [{ type: "text", text: "x".repeat(200000) }] } };
      if (long) {
        for (let i = 0; i < 100 && !(cancelled && s !== "finish_on_cancel"); i++) {
          await sleep(50);
          if (steers.length > 0) break;
          if (s === "finish_on_cancel" && cancelled) break;
        }
      }
      yield { type: "assistant", message: { role: "assistant", content: [{ type: "text", text: "OK" }] } };
    },
    async wait() {
      if (cancelled && s !== "finish_on_cancel") { status = "cancelled"; return { id: run.id, status }; }
      if (s === "run_error") {
        status = "error";
        return { id: run.id, status, error: { message: `boom with ${options.apiKey}`, code: "internal" } };
      }
      status = "finished";
      let text = steers.length ? `OK steered:${steers.join("|")}` : "OK";
      if (s === "big") text = "y".repeat(300000);
      if (echo()) text = optionsView(options, sendOptions, prompt, sends);
      return { id: run.id, status, result: text, durationMs: 42, usage, model: options.model };
    },
    async cancel() { cancelled = true; },
    async steer(text) { steers.push(text); return "complete_delivered"; },
  };
  return run;
}

export const Agent = {
  async create(options) {
    globalThis.__fakeCreates += 1;
    if (leakKey()) process.stderr.write(`debug apiKey=${options.apiKey}\n`);
    const s = scenario();
    if (s === "split_key") {
      const k = options.apiKey;
      process.stderr.write(`debug partial=${k.slice(0, 10)}`);
      await sleep(20);
      process.stderr.write(`${k.slice(10)} fin\n`);
    }
    if (s === "stdout_noise") { console.log("[sdk] ruido en stdout"); process.stdout.write("12\n"); }
    if (s === "slow_create") await sleep(1500);
    if (s === "auth") throw new AuthenticationError(`invalid api key ${options.apiKey}`);
    if (s === "rate") throw new RateLimitError("You've hit your usage limit");
    if (s === "network") throw new NetworkError("fetch failed");
    if (s === "crash") throw new Error(`unexpected crash key=${options.apiKey}`);
    let sends = 0;
    let closed = false;
    return {
      agentId: `agent-fake-${globalThis.__fakeCreates}`,
      async send(prompt, sendOptions) {
        if (closed) throw new Error("agent closed");
        sends += 1;
        return makeRun(options, prompt, sendOptions, sends);
      },
      close() { closed = true; globalThis.__fakeClosed = (globalThis.__fakeClosed ?? 0) + 1; },
      async getUsage() {
        if (s === "usage_cost") return { usage, cost: { rawCostCents: 1, chargedCents: 0.5 }, runs: [] };
        const e = new Error("feature_unavailable"); e.code = "feature_unavailable"; throw e;
      },
    };
  },
};
