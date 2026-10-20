import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

export const DEFAULT_KEY_FILE = join(homedir(), ".secrets", "cursor_api_key_frontera");

export function resolveKeyFile(argv, env) {
  const flag = argv.indexOf("--key-file");
  if (flag >= 0) return argv[flag + 1] ?? "";
  return env.CURSOR_SDK_KEY_FILE ?? DEFAULT_KEY_FILE;
}

export function readKey(keyFile, env) {
  if (keyFile) {
    try {
      const key = readFileSync(keyFile, "utf8").trim();
      if (key) return key;
    } catch {
      // archivo ausente o ilegible: se cae a la variable de entorno
    }
  }
  return (env.CURSOR_API_KEY ?? "").trim();
}
