export const VERSION = "0.2.0";
export const PROTOCOL = 2;
export const DEFAULT_MODEL = "composer-2.5";
export const FAST_PARAMS = Object.freeze([{ id: "fast", value: "true" }]);
export const MODEL_ALIASES = Object.freeze({ "composer-2.5-fast": ["composer-2.5", [{ id: "fast", value: "true" }]] });
export const DEFAULT_TIMEOUT_S = 120;
export const DEFAULT_MAX_EVENT_BYTES = 65536;
export const DEFAULT_MAX_RESULT_CHARS = 200000;
export const MIN_NODE = [22, 13];
export const STORES = Object.freeze(["ephemeral", "default", "dir"]);

export const EXIT = Object.freeze({
  OK: 0, BAD_REQUEST: 2, NO_KEY: 3, AUTH_INVALID: 4, NODE_TOO_OLD: 5, SDK_MISSING: 6,
  TIMEOUT: 7, USAGE_LIMIT: 8, SDK_ERROR: 9, CANCELLED: 10, NETWORK: 11, BUSY: 12,
});

export const FALLBACK_CODES = new Set([
  "NO_KEY", "AUTH_INVALID", "NODE_TOO_OLD", "SDK_MISSING", "TIMEOUT", "USAGE_LIMIT", "SDK_ERROR", "NETWORK",
]);

// Campos del request (one-shot y `op:"run"` en serve). Cualquier otro → BAD_REQUEST.
export const REQUEST_FIELDS = Object.freeze([
  "prompt", "system", "model", "cwd", "timeout_s", "stream", "steer_file", "cancel_file", "tools",
  "mcp", "mcp_servers", "setting_sources", "model_params", "http1",
  "session_id", "store", "store_dir", "max_event_bytes", "max_result_chars",
]);
export const SERVE_OPS = Object.freeze(["run", "steer", "cancel", "close", "ping", "shutdown"]);
const SERVE_EXTRA = { run: ["op", "id"], steer: ["op", "id", "target", "text"], cancel: ["op", "id", "target"],
  close: ["op", "id", "session_id"], ping: ["op", "id"], shutdown: ["op", "id"] };

export function capabilities(sdkVersion = null) {
  return {
    type: "capabilities", version: VERSION, protocol: PROTOCOL, sdk: sdkVersion,
    fields: [...REQUEST_FIELDS], modes: ["oneshot", "serve"], ops: [...SERVE_OPS],
    stores: [...STORES], model_aliases: Object.keys(MODEL_ALIASES), default_model_params: FAST_PARAMS,
  };
}

export class SidecarError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

function badRequest(message) {
  return new SidecarError("BAD_REQUEST", message);
}

function optionalString(value, field) {
  if (value === undefined || value === null) return null;
  if (typeof value !== "string" || value === "") throw badRequest(`${field} tiene que ser string no vacío`);
  return value;
}

function positiveInt(value, field, fallback) {
  if (value === undefined || value === null) return fallback;
  if (!Number.isInteger(value) || value <= 0) throw badRequest(`${field} tiene que ser entero > 0`);
  return value;
}

const isObj = (v) => v !== null && typeof v === "object" && !Array.isArray(v);

function parseJson(raw) {
  let body;
  try {
    body = JSON.parse(raw);
  } catch {
    throw badRequest("el request no es JSON válido");
  }
  if (!isObj(body)) throw badRequest("el request tiene que ser un objeto");
  return body;
}

function rejectUnknown(body, allowed) {
  const unknown = Object.keys(body).filter((key) => !allowed.includes(key));
  if (unknown.length) throw badRequest(`campos desconocidos: ${unknown.join(", ")}`);
}

export function resolveModel(model, params) {
  const alias = MODEL_ALIASES[model];
  const id = alias ? alias[0] : model;
  if (params) return { id, params };
  if (alias) return { id, params: alias[1] };
  return { id, params: id === DEFAULT_MODEL ? [...FAST_PARAMS] : null };
}

export function validateRequest(body, defaultCwd, extra = []) {
  rejectUnknown(body, [...REQUEST_FIELDS, ...extra]);
  if (typeof body.prompt !== "string" || body.prompt.trim() === "") throw badRequest("prompt es obligatorio");
  const timeout = body.timeout_s ?? DEFAULT_TIMEOUT_S;
  if (typeof timeout !== "number" || !(timeout > 0)) throw badRequest("timeout_s tiene que ser un número > 0");
  const stream = body.stream ?? false;
  if (typeof stream !== "boolean") throw badRequest("stream tiene que ser bool");
  if (body.tools !== undefined && body.tools !== null && !Array.isArray(body.tools)) throw badRequest("tools tiene que ser lista");
  // Passthroughs opt-in (FE-BOT 2026-10-20): sin ellos, MCP apagado y sin capas de settings.
  const mcp = body.mcp ?? false;
  if (typeof mcp !== "boolean") throw badRequest("mcp tiene que ser bool");
  if (body.mcp_servers != null && !isObj(body.mcp_servers)) throw badRequest("mcp_servers tiene que ser objeto");
  if (body.setting_sources != null && !Array.isArray(body.setting_sources)) throw badRequest("setting_sources tiene que ser lista");
  if (body.model_params != null && !Array.isArray(body.model_params)) throw badRequest("model_params tiene que ser lista");
  const http1 = body.http1 ?? false;
  if (typeof http1 !== "boolean") throw badRequest("http1 tiene que ser bool");
  const store = body.store ?? (body.store_dir ? "dir" : "ephemeral");
  if (!STORES.includes(store)) throw badRequest(`store tiene que ser ${STORES.join("|")}`);
  const storeDir = optionalString(body.store_dir, "store_dir");
  if (store === "dir" && !storeDir) throw badRequest("store dir necesita store_dir");
  const model = resolveModel(optionalString(body.model, "model") ?? DEFAULT_MODEL, body.model_params ?? null);
  return {
    prompt: body.prompt,
    system: optionalString(body.system, "system"),
    model: model.id,
    cwd: optionalString(body.cwd, "cwd") ?? defaultCwd,
    timeout_s: timeout,
    stream,
    steer_file: optionalString(body.steer_file, "steer_file"),
    cancel_file: optionalString(body.cancel_file, "cancel_file"),
    tools: body.tools ?? null,
    mcp,
    mcp_servers: body.mcp_servers ?? null,
    setting_sources: body.setting_sources ?? null,
    model_params: model.params,
    http1,
    session_id: optionalString(body.session_id, "session_id"),
    store,
    store_dir: storeDir,
    max_event_bytes: positiveInt(body.max_event_bytes, "max_event_bytes", DEFAULT_MAX_EVENT_BYTES),
    max_result_chars: positiveInt(body.max_result_chars, "max_result_chars", DEFAULT_MAX_RESULT_CHARS),
  };
}

export function parseRequest(raw, defaultCwd) {
  return validateRequest(parseJson(raw), defaultCwd);
}

export function parseServeLine(raw, defaultCwd) {
  const body = parseJson(raw);
  const op = body.op ?? "run";
  if (!SERVE_OPS.includes(op)) throw badRequest(`op desconocida: ${op}`);
  const id = body.id ?? null;
  if (id !== null && (typeof id !== "string" || !id)) throw badRequest("id tiene que ser string no vacío");
  if (op === "run") {
    if (!id) throw badRequest("run necesita id");
    const { op: _op, id: _id, ...rest } = body;
    return { op, id, request: validateRequest(rest, defaultCwd) };
  }
  rejectUnknown(body, SERVE_EXTRA[op]);
  if ((op === "steer" || op === "cancel") && (typeof body.target !== "string" || !body.target)) throw badRequest(`${op} necesita target`);
  if (op === "steer" && (typeof body.text !== "string" || !body.text)) throw badRequest("steer necesita text");
  if (op === "close" && (typeof body.session_id !== "string" || !body.session_id)) throw badRequest("close necesita session_id");
  return { op, id, target: body.target ?? null, text: body.text ?? null, session_id: body.session_id ?? null };
}

export function checkNodeVersion(version) {
  const [major, minor] = String(version).replace(/^v/, "").split(".").map(Number);
  return major > MIN_NODE[0] || (major === MIN_NODE[0] && minor >= MIN_NODE[1]);
}

const AUTH = /\b401\b|unauthori[sz]ed|invalid api key|authentication/i;
const LIMIT = /\b429\b|rate limit|usage limit|too many requests|quota/i;
const NETWORK = /fetch failed|ECONNREFUSED|ENOTFOUND|ETIMEDOUT|network/i;

export function classifyError(error) {
  const name = error?.name ?? "";
  const text = `${error?.message ?? ""} ${error?.code ?? ""}`;
  if (name === "AuthenticationError" || AUTH.test(text)) return "AUTH_INVALID";
  if (name === "RateLimitError" || LIMIT.test(text)) return "USAGE_LIMIT";
  if (name === "NetworkError" || NETWORK.test(text)) return "NETWORK";
  return "SDK_ERROR";
}

export function makeRedactor(secret) {
  if (!secret) return (text) => String(text);
  return (text) => String(text).split(secret).join("<redacted>");
}

/** Redactor con buffer: retiene el final de cada write hasta ver el resto, así una key partida no se escapa. */
export function makeStreamRedactor(secret, write) {
  const redact = makeRedactor(secret);
  const hold = secret ? secret.length - 1 : 0;
  let pending = "";
  return {
    write(chunk) {
      pending += chunk;
      const cut = pending.lastIndexOf("\n") + 1;
      let ready = pending.slice(0, cut);
      let rest = pending.slice(cut);
      if (rest.length > 65536) {
        ready += rest.slice(0, rest.length - hold);
        rest = rest.slice(rest.length - hold);
      }
      pending = rest;
      if (ready) write(redact(ready));
    },
    flush() {
      if (pending) write(redact(pending));
      pending = "";
    },
  };
}

export function publicUsage(usage) {
  if (!usage) return null;
  return {
    inputTokens: usage.inputTokens ?? 0,
    outputTokens: usage.outputTokens ?? 0,
    cacheReadTokens: usage.cacheReadTokens ?? 0,
    totalTokens: usage.totalTokens ?? 0,
  };
}

function trimStrings(value, limit) {
  if (typeof value === "string") return value.length > limit ? `${value.slice(0, limit)}…[+${value.length - limit}]` : value;
  if (Array.isArray(value)) return value.map((v) => trimStrings(v, limit));
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, trimStrings(v, limit)]));
  return value;
}

/** Evento grande: primero recorta los strings largos (se conserva la forma: type, tool_call, etc.); si igual no entra, data null + preview. */
export function truncateEvent(line, maxBytes) {
  const text = JSON.stringify(line);
  const bytes = Buffer.byteLength(text);
  if (bytes <= maxBytes) return line;
  for (const limit of [Math.floor(maxBytes / 4), Math.floor(maxBytes / 16), 64]) {
    const trimmed = { ...line, data: trimStrings(line.data ?? null, limit), truncated: true, bytes };
    if (Buffer.byteLength(JSON.stringify(trimmed)) <= maxBytes) return trimmed;
  }
  const preview = JSON.stringify(line.data ?? null).slice(0, Math.max(0, Math.floor(maxBytes / 2)));
  return { ...line, data: null, truncated: true, bytes, preview };
}

export function truncateText(text, maxChars) {
  const value = text ?? "";
  if (value.length <= maxChars) return { text: value };
  return { text: value.slice(0, maxChars), text_truncated: true, text_len: value.length };
}
