export const DEFAULT_MODEL = "composer-2.5";
export const DEFAULT_TIMEOUT_S = 120;
export const MIN_NODE = [22, 13];

export const EXIT = Object.freeze({
  OK: 0, BAD_REQUEST: 2, NO_KEY: 3, AUTH_INVALID: 4, NODE_TOO_OLD: 5, SDK_MISSING: 6,
  TIMEOUT: 7, USAGE_LIMIT: 8, SDK_ERROR: 9, CANCELLED: 10, NETWORK: 11,
});

export const FALLBACK_CODES = new Set([
  "NO_KEY", "AUTH_INVALID", "NODE_TOO_OLD", "SDK_MISSING", "TIMEOUT", "USAGE_LIMIT", "SDK_ERROR", "NETWORK",
]);

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

export function parseRequest(raw, defaultCwd) {
  let body;
  try {
    body = JSON.parse(raw);
  } catch {
    throw badRequest("el request no es JSON válido");
  }
  if (body === null || typeof body !== "object" || Array.isArray(body)) throw badRequest("el request tiene que ser un objeto");
  if (typeof body.prompt !== "string" || body.prompt.trim() === "") throw badRequest("prompt es obligatorio");
  const timeout = body.timeout_s ?? DEFAULT_TIMEOUT_S;
  if (typeof timeout !== "number" || !(timeout > 0)) throw badRequest("timeout_s tiene que ser un número > 0");
  const stream = body.stream ?? false;
  if (typeof stream !== "boolean") throw badRequest("stream tiene que ser bool");
  if (body.tools !== undefined && body.tools !== null && !Array.isArray(body.tools)) throw badRequest("tools tiene que ser lista");
  return {
    prompt: body.prompt,
    system: optionalString(body.system, "system"),
    model: optionalString(body.model, "model") ?? DEFAULT_MODEL,
    cwd: optionalString(body.cwd, "cwd") ?? defaultCwd,
    timeout_s: timeout,
    stream,
    steer_file: optionalString(body.steer_file, "steer_file"),
    cancel_file: optionalString(body.cancel_file, "cancel_file"),
    tools: body.tools ?? null,
  };
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

export function publicUsage(usage) {
  if (!usage) return null;
  return {
    inputTokens: usage.inputTokens ?? 0,
    outputTokens: usage.outputTokens ?? 0,
    cacheReadTokens: usage.cacheReadTokens ?? 0,
    totalTokens: usage.totalTokens ?? 0,
  };
}
