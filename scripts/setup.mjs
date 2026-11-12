// Tek komutla kurulum: `pnpm setup:all`
// 1) .env yoksa .env.example'dan oluşturur
// 2) Node paketlerini kurar (pnpm install)
// 3) Python ortamını kurar (uv sync -> Python 3.12 + paketler)
// 4) PostGIS konteynerini başlatır ve hazır olmasını bekler
import { spawnSync } from "node:child_process";
import { copyFileSync, existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

function step(title) {
  console.log(`\n\x1b[36m▶ ${title}\x1b[0m`);
}

function run(cmd, args, opts = {}) {
  // Argümanlar sabit ve güvenli; tek string olarak verilir (Node DEP0190 uyarısını önler).
  const res = spawnSync([cmd, ...args].join(" "), { stdio: "inherit", shell: true, cwd: root, ...opts });
  if (res.status !== 0) {
    console.error(`\n\x1b[31m✖ Komut başarısız: ${cmd} ${args.join(" ")}\x1b[0m`);
    process.exit(res.status ?? 1);
  }
}

function has(cmd) {
  return spawnSync(`${cmd} --version`, { stdio: "ignore", shell: true }).status === 0;
}

step("Gerekli araçlar kontrol ediliyor");
const missing = [];
if (!has("uv")) missing.push("uv  -> https://docs.astral.sh/uv/getting-started/installation/");
if (!has("docker")) missing.push("docker -> Docker Desktop kurun ve açın");
if (missing.length) {
  console.error("Eksik araçlar:\n  " + missing.join("\n  "));
  process.exit(1);
}
if (spawnSync("docker info", { stdio: "ignore", shell: true }).status !== 0) {
  console.error("Docker motoru çalışmıyor. Docker Desktop'ı açın ve 'Engine running' olmasını bekleyin.");
  process.exit(1);
}

step(".env dosyası");
const envPath = join(root, ".env");
if (!existsSync(envPath) || readFileSync(envPath, "utf8").trim() === "") {
  copyFileSync(join(root, ".env.example"), envPath);
  console.log(".env, .env.example'dan oluşturuldu.");
} else {
  console.log(".env zaten var, dokunulmadı.");
}

step("Node paketleri (pnpm install)");
run("pnpm", ["install"]);

step("Python ortamı (uv sync)");
run("uv", ["sync"], { cwd: join(root, "apps", "api") });

step("PostGIS veritabanı (docker compose)");
run("docker", ["compose", "up", "-d", "--build", "--wait"]);

step("Veritabanı şeması (migration)");
run("uv", ["run", "python", "-m", "app.migrate"], { cwd: join(root, "apps", "api") });

const env = readFileSync(envPath, "utf8");
if (/^FIRMS_MAP_KEY=\s*$/m.test(env)) {
  console.log("\n\x1b[33m! FIRMS_MAP_KEY boş. Veri çekmek için .env dosyasına NASA FIRMS anahtarınızı yazın.\x1b[0m");
}

console.log("\n\x1b[32m✔ Kurulum tamam. Başlatmak için: pnpm dev\x1b[0m");
console.log("  Web: http://localhost:3000   API: http://localhost:8000/docs");
console.log("  Veri yüklemek için: pnpm ingest all --country AZ   (durum: pnpm ingest status)");
