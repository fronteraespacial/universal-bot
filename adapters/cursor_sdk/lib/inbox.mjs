import { existsSync, readFileSync } from "node:fs";

export function steerReader(path) {
  let consumed = 0;
  return () => {
    if (!path || !existsSync(path)) return [];
    const lines = readFileSync(path, "utf8").split("\n");
    const complete = lines.slice(0, -1);
    const fresh = complete.slice(consumed);
    consumed = complete.length;
    return fresh.map(parseSteerLine).filter(Boolean);
  };
}

function parseSteerLine(line) {
  const trimmed = line.trim();
  if (!trimmed) return null;
  try {
    const value = JSON.parse(trimmed);
    return typeof value?.text === "string" && value.text ? value.text : null;
  } catch {
    return trimmed;
  }
}
