import { fileURLToPath } from "node:url";
import { dirname } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Pin the file-tracing root to this project. Without it, Next picks up an
  // unrelated lockfile in a parent directory and warns.
  outputFileTracingRoot: __dirname,
};

export default nextConfig;
