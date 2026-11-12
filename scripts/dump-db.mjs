// Yerel veritabanının sıkıştırılmış yedeği: data/dumps/astraforce.dump
// Sunucuya kopyalayıp `scripts/restore-db.sh` ile yükleyin (veriyi yeniden indirmekten hızlı).
import { spawn } from "node:child_process";
import { createWriteStream, mkdirSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const outDir = join(root, "data", "dumps");
mkdirSync(outDir, { recursive: true });
const outFile = join(outDir, "astraforce.dump");

console.log(`Yedek alınıyor → ${outFile} (birkaç dakika sürebilir)`);
const proc = spawn(
  "docker",
  ["compose", "exec", "-T", "db", "pg_dump", "-U", "astra", "-d", "astraforce", "-Fc", "-Z", "6"],
  { cwd: root, stdio: ["ignore", "pipe", "inherit"] },
);
proc.stdout.pipe(createWriteStream(outFile));
proc.on("close", (code) => {
  if (code !== 0) {
    console.error(`pg_dump başarısız (çıkış kodu ${code})`);
    process.exit(code ?? 1);
  }
  const mb = statSync(outFile).size / 1024 / 1024;
  console.log(`Tamam: ${mb.toFixed(0)} MB`);
});
